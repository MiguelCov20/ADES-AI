# AGENTS.md — memory/ (Capa de memoria anti-alucinación)

Convenciones locales de la capa de memoria. Completa al `AGENTS.md` raíz.

- **Tres sistemas, un propósito** (anti-alucinación): Graphiti (grafo temporal Neo4j), Mem0 (hechos/preferencias en Qdrant), Cognee (KG de documentos en Neo4j).
- **`indexer.py`** (Tree-sitter → Neo4j) construye el RepoMap del código. Es determinista, sin LLM. CLI: `python -m memory.indexer --repo <ruta> [--reset]`.
- **`schemas.py`** define nodos/relaciones/constraints del grafo (`CodeFile`, `Class`, `Function`, `Module`).
- Los clientes (`graphiti_client.py`, `mem0_client.py`, `cognee_client.py`) son wrappers **síncronos** (`asyncio.run`) sobre APIs async.
- Config por `.env`: `NEO4J_*`, `QDRANT_URL`, `OPENCODE_API_KEY`, `GEMINI_MODEL`.
- Notas de integración (bugs parcheados): graphiti-core 0.31.2 necesita monkeypatch (query bulk de Neo4j) y `build_indices_and_constraints()`; Cognee 1.6.6 no soporta Qdrant (usa LanceDB) y requiere el plugin APOC; OpenCode Go exige header `x-opencode-session`.
