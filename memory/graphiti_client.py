"""Cliente Graphiti (grafo temporal sobre Neo4j) - ADES-AI, Fase 2.

Graphiti construye un grafo de conocimiento temporal e incremental sobre el
Neo4j existente: extrae entidades y relaciones de texto con un LLM, las
embebe y las almacena sabiendo cuándo cambiaron. Es el pilar anti-alucinación.

Configuración por defecto:
  - LLM: OpenCode Go (deepseek-v4-pro / flash)  -> endpoint OpenAI-compatible
  - Embeddings: nomic-embed-text (local, Ollama)
  - Neo4j: variables de entorno (.env)

Uso:
    python memory/graphiti_client.py add "texto a ingerir" [--name N]
    python memory/graphiti_client.py search "consulta" [--num N]
"""
import argparse
import asyncio
import datetime as dt
import os
import re
import sys

from dotenv import load_dotenv
from openai import AsyncOpenAI

from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIClient, LLMConfig
from graphiti_core.embedder import OpenAIEmbedder
from graphiti_core.embedder.openai import OpenAIEmbedderConfig
from graphiti_core.cross_encoder import OpenAIRerankerClient

# ---------------------------------------------------------------------------
# Parche de bug de graphiti-core 0.31.2 (compatibilidad con Neo4j 5.23).
# La query bulk de nodos de Neo4j usa "SET n:$(node.labels)" (labels
# dinámicos), que Neo4j no soporta. La reemplazamos por una query correcta
# que guarda los labels como propiedad ("SET n = node" ya los incluye).
# ---------------------------------------------------------------------------
import graphiti_core.utils.bulk_utils as _bulk_utils
from graphiti_core.driver.driver import GraphProvider as _GP

_ORIGINAL_NODE_BULK = _bulk_utils.get_entity_node_save_bulk_query


def _fixed_node_bulk(provider, nodes, has_aoss=False):
    if provider == _GP.NEO4J:
        save_embedding_query = (
            'WITH n, node CALL db.create.setNodeVectorProperty(n, "name_embedding", node.name_embedding)'
            if not has_aoss else ''
        )
        return (
            "UNWIND $nodes AS node "
            "MERGE (n:Entity {uuid: node.uuid}) "
            "SET n = node "
            + save_embedding_query
            + " RETURN n.uuid AS uuid"
        )
    return _ORIGINAL_NODE_BULK(provider, nodes, has_aoss)


_bulk_utils.get_entity_node_save_bulk_query = _fixed_node_bulk

# Forzar UTF-8 en la consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

OPENCODE_BASE = "https://opencode.ai/inference/go/openai/v1"
OLLAMA_BASE = "http://localhost:11434/v1"


GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _llm_backend() -> tuple[str, str, dict, str, str]:
    """(base_url, api_key, headers, modelo, modelo_pequeño) según GRAPHITI_PROVIDER.

    Por defecto `ollama` (gpt-oss:20b local, $0, sin cuotas). Antes era siempre
    OpenCode Go: al agotarse la cuota del plan, el timeline de decisiones dejaba de
    escribir en Graphiti (RateLimitError en los tests live).
    """
    prov = os.getenv("GRAPHITI_PROVIDER", "ollama").lower()
    if prov == "opencode":
        return (OPENCODE_BASE, os.getenv("OPENCODE_API_KEY", ""),
                {"x-opencode-session": "ades-graphiti", "User-Agent": "ades-ai/1.0"},
                os.getenv("GRAPHITI_MODEL", "deepseek-v4-pro"),
                os.getenv("GRAPHITI_SMALL_MODEL", "deepseek-v4.1-flash"))
    if prov == "gemini":
        return (GEMINI_OPENAI_BASE, os.getenv("GOOGLE_API_KEY", ""), {},
                os.getenv("GRAPHITI_MODEL", "gemini-flash-lite-latest"),
                os.getenv("GRAPHITI_SMALL_MODEL", "gemini-flash-lite-latest"))
    model = os.getenv("GRAPHITI_MODEL", "gpt-oss:20b-ctx16k")
    return (OLLAMA_BASE, "ollama", {}, model, os.getenv("GRAPHITI_SMALL_MODEL", model))


def build_graphiti() -> Graphiti:
    """Construye Graphiti: LLM configurable (GRAPHITI_PROVIDER) + nomic local + Neo4j."""
    base, key, headers, model, small = _llm_backend()
    llm_client = AsyncOpenAI(base_url=base, api_key=key, default_headers=headers or None)
    cfg = LLMConfig(api_key=key, model=model, small_model=small, base_url=base)
    if base == OLLAMA_BASE:
        # Modelos locales: cliente genérico (salida JSON) en vez de structured outputs
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        llm = OpenAIGenericClient(config=cfg, client=llm_client)
    else:
        llm = OpenAIClient(config=cfg, client=llm_client)

    # Embeddings -> nomic-embed-text (local, Ollama)
    embedder_client = AsyncOpenAI(base_url=OLLAMA_BASE, api_key="ollama")
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            api_key="ollama",
            base_url=OLLAMA_BASE,
        ),
        client=embedder_client,
    )

    # Cross-encoder / reranker (usado en search avanzado) -> mismo backend
    reranker = OpenAIRerankerClient(
        config=LLMConfig(api_key=key, model=small, base_url=base),
        client=llm_client,
    )

    return Graphiti(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
    )


def _utc(when: "dt.datetime | float | None") -> dt.datetime:
    """Normaliza un instante (datetime, epoch o None=ahora) a datetime UTC con zona."""
    if when is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(when, (int, float)):
        return dt.datetime.fromtimestamp(float(when), dt.timezone.utc)
    if when.tzinfo is None:
        return when.replace(tzinfo=dt.timezone.utc)
    return when


def safe_group_id(name: str) -> str:
    """Convierte un nombre de proyecto en un group_id válido para Graphiti
    (solo letras, dígitos, '-' y '_')."""
    g = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "").strip("-")
    return g or "default"


async def _add(g: Graphiti, text: str, name: str, source: str,
               reference_time: dt.datetime | None = None,
               group_id: str | None = None) -> dict:
    await g.build_indices_and_constraints()
    kwargs = {}
    if group_id:
        kwargs["group_id"] = group_id
    try:
        result = await g.add_episode(
            name=name,
            episode_body=text,
            source_description=source,
            reference_time=_utc(reference_time),
            **kwargs,
        )
    finally:
        await g.close()
    return {
        "nodes": len(result.nodes),
        "edges": len(result.edges),
        "episode": getattr(getattr(result, "episode", None), "uuid", None),
    }


def add_text(text: str, name: str = "episodio", source: str = "usuario",
             reference_time: "dt.datetime | float | None" = None,
             group_id: str | None = None) -> dict:
    """Ingiere un texto en el grafo temporal (síncrono).

    `reference_time` (datetime o epoch) es el momento real del episodio; por
    defecto, ahora. `group_id` aísla los episodios (p.ej. por proyecto).
    """
    g = build_graphiti()
    return asyncio.run(_add(g, text, name, source, reference_time, group_id))


def _iso(v) -> str | None:
    return v.isoformat() if isinstance(v, dt.datetime) else (str(v) if v else None)


async def _search(g: Graphiti, query: str, num: int,
                  group_ids: list[str] | None = None) -> list[dict]:
    await g.build_indices_and_constraints()
    try:
        edges = await g.search(query, num_results=num, group_ids=group_ids)
    finally:
        await g.close()
    out = []
    for e in edges:
        out.append({
            "source": e.source_node_uuid,
            "target": e.target_node_uuid,
            "fact": getattr(e, "fact", None) or (getattr(e, "name", None)),
            "valid_at": _iso(getattr(e, "valid_at", None)),
            "invalid_at": _iso(getattr(e, "invalid_at", None)),
            "created_at": _iso(getattr(e, "created_at", None)),
            "group_id": getattr(e, "group_id", None),
        })
    return out


def search(query: str, num: int = 10, group_ids: list[str] | None = None) -> list[dict]:
    """Busca en el grafo temporal (síncrono). `group_ids` filtra por grupos."""
    g = build_graphiti()
    return asyncio.run(_search(g, query, num, group_ids))


async def _clear(g: Graphiti, group_ids: list[str]) -> None:
    from graphiti_core.utils.maintenance.graph_data_operations import clear_data
    try:
        await clear_data(g.driver, group_ids=group_ids)
    finally:
        await g.close()


def clear_group(group_id: str) -> None:
    """Borra todos los nodos/aristas/episodios de un group_id (útil en tests)."""
    if not group_id:
        raise ValueError("group_id vacío: no se borra el grafo entero")
    asyncio.run(_clear(build_graphiti(), [group_id]))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Cliente Graphiti (Fase 2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="ingiere texto en el grafo temporal")
    p_add.add_argument("text")
    p_add.add_argument("--name", default="episodio")
    p_add.add_argument("--source", default="usuario")

    p_search = sub.add_parser("search", help="busca en el grafo temporal")
    p_search.add_argument("query")
    p_search.add_argument("--num", type=int, default=10)

    args = ap.parse_args(argv)

    if args.cmd == "add":
        r = add_text(args.text, args.name, args.source)
        print(f"[OK] nodos={r['nodes']} aristas={r['edges']}")
    elif args.cmd == "search":
        results = search(args.query, args.num)
        print(f"[OK] {len(results)} resultados:")
        for r in results:
            print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
