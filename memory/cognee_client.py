"""Cliente Cognee (KG de documentos) - ADES-AI, Fase 2.

Cognee convierte documentos y repositorios en grafos de conocimiento (KG).
Extrae entidades y relaciones con un LLM y las almacena en Neo4j, con
búsqueda vectorial vía LanceDB. Integra con LangGraph y Neo4j.

Configuración por defecto:
  - LLM (extracción): Ollama local (gpt-oss:20b) — sin clave ni header.
  - Embeddings: fastembed local (nomic-embed-text-v1.5, 768 dims).
  - Graph DB: Neo4j (requiere el plugin APOC, ya añadido a docker-compose).
  - Vector DB: LanceDB (local).

Nota: Cognee 1.6.6 NO soporta Qdrant como vector store (usa LanceDB/PGVector).

Uso:
    python -m memory.cognee_client add "texto o ruta de archivo"
    python -m memory.cognee_client cognify
    python -m memory.cognee_client search "consulta"
"""
import argparse
import asyncio
import os
import sys

# Forzar UTF-8 en la consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()


def _setup_env() -> None:
    """Configura Cognee vía variables de entorno (antes de importarlo)."""
    os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
    os.environ.setdefault("LLM_PROVIDER", "ollama")
    os.environ.setdefault("LLM_MODEL", "gpt-oss:20b")
    os.environ.setdefault("LLM_ENDPOINT", "http://localhost:11434")
    os.environ.setdefault("LLM_API_KEY", "ollama")  # no se usa, la validación lo exige
    os.environ.setdefault("EMBEDDING_PROVIDER", "fastembed")
    os.environ.setdefault("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
    os.environ.setdefault("EMBEDDING_DIMENSIONS", "768")
    os.environ.setdefault("GRAPH_DATABASE_PROVIDER", "neo4j")
    os.environ.setdefault("GRAPH_DATABASE_URL", os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    os.environ.setdefault("GRAPH_DATABASE_USERNAME", os.getenv("NEO4J_USERNAME", "neo4j"))
    os.environ.setdefault("GRAPH_DATABASE_PASSWORD", os.getenv("NEO4J_PASSWORD", ""))
    os.environ.setdefault("VECTOR_DB_PROVIDER", "lancedb")


_setup_env()

import cognee  # noqa: E402


def add(data: str, dataset_name: str = "main_dataset") -> None:
    """Ingiere texto o una ruta de archivo/URL (síncrono)."""
    asyncio.run(cognee.add(data, dataset_name=dataset_name))


def cognify() -> None:
    """Construye el grafo de conocimiento a partir de los datos ingeridos."""
    asyncio.run(cognee.cognify())


def search(query: str) -> list:
    """Busca en el KG y devuelve respuestas (síncrono)."""
    return asyncio.run(cognee.search(query))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Cliente Cognee (Fase 2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("add", help="ingiere texto o archivo").add_argument("data")
    sub.add_parser("cognify", help="construye el KG")
    p_s = sub.add_parser("search", help="busca en el KG")
    p_s.add_argument("query")

    args = ap.parse_args(argv)

    if args.cmd == "add":
        add(args.data)
        print("[OK] datos ingeridos. Ejecuta 'cognify' para construir el grafo.")
    elif args.cmd == "cognify":
        cognify()
        print("[OK] grafo de conocimiento construido.")
    elif args.cmd == "search":
        results = search(args.query)
        print(f"[OK] {len(results)} resultado(s):")
        for r in results:
            print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
