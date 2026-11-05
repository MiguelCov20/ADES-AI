"""Cliente Mem0 (hechos personales/preferencias) - ADES-AI, Fase 2.

Mem0 extrae y recuerda "hechos" del usuario (preferencias, decisiones) con la
mejor precisión en LongMemEval. Los guarda en Qdrant (vectorial) y los
recupera por similitud semántica.

Configuración por defecto:
  - LLM (extracción): OpenCode Go (deepseek-v4-pro), endpoint OpenAI-compatible
  - Embeddings: nomic-embed-text (local, Ollama, 768 dims)
  - Vector store: Qdrant (http://localhost:6333, colección "mem0")

Uso:
    python memory/mem0_client.py add "texto" [--user USUARIO]
    python memory/mem0_client.py search "consulta" [--user USUARIO]
"""
import argparse
import os
import sys

from dotenv import load_dotenv

# Forzar UTF-8 en la consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

OPENCODE_BASE = "https://opencode.ai/inference/go/openai/v1"
EMBED_DIMS = 768  # nomic-embed-text


# ---------------------------------------------------------------------------
# Parche: OpenCode Go requiere el header "x-opencode-session" en cada llamada.
# Mem0 crea su cliente OpenAI sin headers, así que envolvemos el constructor
# para inyectar el header. Solo afecta al LLM de Mem0 (el embedder usa Ollama).
# ---------------------------------------------------------------------------
import mem0.llms.openai as _mem0_openai
from openai import OpenAI as _RealOpenAI


def _opencode_client(*args, **kwargs):
    headers = dict(kwargs.get("default_headers") or {})
    headers.setdefault("x-opencode-session", "ades-mem0")
    headers.setdefault("User-Agent", "ades-ai/1.0")
    kwargs["default_headers"] = headers
    return _RealOpenAI(*args, **kwargs)


_mem0_openai.OpenAI = _opencode_client


def _config() -> dict:
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "url": os.getenv("QDRANT_URL", "http://localhost:6333"),
                "collection_name": "mem0",
                "embedding_model_dims": EMBED_DIMS,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "api_key": os.getenv("OPENCODE_API_KEY", ""),
                "openai_base_url": OPENCODE_BASE,
                "model": os.getenv("MEM0_MODEL", "deepseek-v4-pro"),
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": "nomic-embed-text",
                "embedding_dims": EMBED_DIMS,
                "ollama_base_url": "http://localhost:11434",
            },
        },
    }


def build_memory():
    from mem0 import Memory
    return Memory.from_config(_config())


def add(text: str, user_id: str = "default_user") -> dict:
    """Extrae y guarda hechos de un texto (síncrono)."""
    m = build_memory()
    result = m.add(text, user_id=user_id)
    return result


def search(query: str, user_id: str = "default_user") -> list:
    """Busca hechos por similitud semántica (síncrono)."""
    m = build_memory()
    return m.search(query, filters={"user_id": user_id}).get("results", [])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Cliente Mem0 (Fase 2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="guarda hechos de un texto")
    p_add.add_argument("text")
    p_add.add_argument("--user", default="default_user")

    p_search = sub.add_parser("search", help="busca hechos")
    p_search.add_argument("query")
    p_search.add_argument("--user", default="default_user")

    args = ap.parse_args(argv)

    if args.cmd == "add":
        result = add(args.text, args.user)
        results = result.get("results", [result])
        print(f"[OK] {len(results)} recuerdo(s) guardados:")
        for r in results:
            mem = r.get("memory", r)
            print(f"  - {mem}")
    elif args.cmd == "search":
        results = search(args.query, args.user)
        print(f"[OK] {len(results)} resultado(s):")
        for r in results:
            if isinstance(r, dict):
                mem = r.get("memory", r)
                score = r.get("score")
                print(f"  - {mem}" + (f"  (score={score})" if score is not None else ""))
            else:
                print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
