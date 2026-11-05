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


def build_graphiti() -> Graphiti:
    """Construye una instancia de Graphiti apuntando a OpenCode Go + Ollama + Neo4j."""
    opencode_key = os.getenv("OPENCODE_API_KEY", "")

    # LLM (extracción de entidades/relaciones) -> OpenCode Go (DeepSeek V4)
    llm_client = AsyncOpenAI(
        base_url=OPENCODE_BASE,
        api_key=opencode_key,
        default_headers={"x-opencode-session": "ades-graphiti", "User-Agent": "ades-ai/1.0"},
    )
    llm = OpenAIClient(
        config=LLMConfig(
            api_key=opencode_key,
            model=os.getenv("GRAPHITI_MODEL", "deepseek-v4-pro"),
            small_model=os.getenv("GRAPHITI_SMALL_MODEL", "deepseek-v4.1-flash"),
            base_url=OPENCODE_BASE,
        ),
        client=llm_client,
    )

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

    # Cross-encoder / reranker (usado en search avanzado) -> OpenCode Go
    reranker = OpenAIRerankerClient(
        config=LLMConfig(api_key=opencode_key, model="deepseek-v4-pro", base_url=OPENCODE_BASE),
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


async def _add(g: Graphiti, text: str, name: str, source: str) -> dict:
    await g.build_indices_and_constraints()
    result = await g.add_episode(
        name=name,
        episode_body=text,
        source_description=source,
        reference_time=dt.datetime.now(dt.timezone.utc),
    )
    return {
        "nodes": len(result.nodes),
        "edges": len(result.edges),
    }


def add_text(text: str, name: str = "episodio", source: str = "usuario") -> dict:
    """Ingiere un texto en el grafo temporal (síncrono)."""
    g = build_graphiti()
    return asyncio.run(_add(g, text, name, source))


async def _search(g: Graphiti, query: str, num: int) -> list[dict]:
    await g.build_indices_and_constraints()
    edges = await g.search(query, num_results=num)
    out = []
    for e in edges:
        out.append({
            "source": e.source_node_uuid,
            "target": e.target_node_uuid,
            "fact": getattr(e, "fact", None) or (getattr(e, "name", None)),
        })
    return out


def search(query: str, num: int = 10) -> list[dict]:
    """Busca en el grafo temporal (síncrono)."""
    g = build_graphiti()
    return asyncio.run(_search(g, query, num))


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
