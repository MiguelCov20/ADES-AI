---
name: Memoria
description: Lee y escribe en la capa de memoria de ADES-AI (grafo temporal Graphiti, hechos Mem0, documentos Cognee)
---

## Objetivo

Usar la capa de memoria (anti-alucinación) de ADES-AI, formada por tres sistemas:

- **Graphiti** (grafo temporal sobre Neo4j): entidades y relaciones con historial temporal.
- **Mem0** (hechos/preferencias del usuario, en Qdrant): preferencias y decisiones.
- **Cognee** (KG de documentos, en Neo4j): conocimiento a partir de documentos.

## Workflow

- Grafo temporal: `python -m memory.graphiti_client add "<texto>"` y `search "<consulta>"`.
- Hechos: `python -m memory.mem0_client add "<texto>" --user <id>` y `search "<consulta>" --user <id>`.
- Documentos: `python -m memory.cognee_client add "<texto o archivo>"`, `cognify` y `search "<consulta>"`.

## Notas

- Graphiti requiere llamar `build_indices_and_constraints()` (ya lo hace el cliente).
- Cognee requiere el plugin APOC en Neo4j (ya configurado en docker-compose).
- Embeddings locales: `nomic-embed-text` (Ollama).
