---
name: Indexar repo
description: Indexa el código de un repositorio en el grafo de Neo4j (Tree-sitter) para el RepoMap anti-alucinación
---

## Objetivo

Construir (o reindexar) el grafo de código de un repositorio en Neo4j usando
`memory/indexer.py`. El agente consulta este grafo para conocer la estructura
(clases, funciones, imports) sin cargar todo el código en contexto.

## Workflow

1. Ejecuta `python -m memory.indexer --repo <ruta> --summary`.
2. Usa `--reset` solo si quieres reconstruir el grafo desde cero.
3. Para consultar la estructura ya indexada, usa Cypher contra Neo4j
   (labels `CodeFile`, `Class`, `Function`, `Module`).

## Referencias

- `memory/indexer.py` — implementación del indexador.
- `memory/schemas.py` — esquema del grafo (constraints e índices).
