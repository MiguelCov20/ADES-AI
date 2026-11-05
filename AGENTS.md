# AGENTS.md — ADES-AI

Instrucciones permanentes para cualquier agente (OpenCode, Cline, subagentes, LangGraph) que trabaje en este repositorio. Mantén este archivo **CORTO**: se carga siempre en contexto (capa 1 de contexto, se cachea).

## Qué es ADES-AI
Ecosistema de desarrollo autónomo multi-agente. Combina 3 "cerebros" (nube, GPU local, memoria) y asigna cada tarea al modelo óptimo para ahorrar ~90% de tokens.

## Fuente de verdad
- `docs/plan_ecosistema_ia.md` — plan maestro, roadmap por fases y decisiones. Léelo antes de tocar arquitectura.
- `docs/catalogo_herramientas.md` — herramientas externas con URLs verificadas.

## Reglas de trabajo
1. Antes de cambiar arquitectura, lee el plan y confirma la fase.
2. No inventes APIs, clases ni librerías: valida contra el grafo de código (Neo4j/Graphiti) o la documentación.
3. Cada tarea delegada a un subagente debe tener contexto acotado (bounded work).
4. Sigue el stack decidido en el plan (sección 4). Los cambios de decisión se registran en el plan.
5. QA nunca ejecuta código fuera de un contenedor Docker (sandbox).

## Seguridad
- NUNCA hagas commit de claves ni secretos. `.env` está en `.gitignore`.
- Antes de commitear, ejecuta: `python environment/scan_secrets.py`.
- Si una clave queda expuesta: rótala en el panel del proveedor y actualiza `.env`.
- Para activar el escaneo automático en cada commit: `cp environment/pre-commit .git/hooks/pre-commit`.

## Modelos (cerebros)
- Nube razonamiento: **Gemini** (arquitectura / PM). Modelo configurable con `GEMINI_MODEL` (por defecto `gemini-flash-latest`; alternativas `gemini-4-argon` o `gemini-flash-lite-latest`).
- Nube código: **OpenCode Go — DeepSeek V4**.
- Local (GPU 16GB): `gpt-oss:20b` (código), `Qwen3.8 27B` (razonamiento), `Llama-3.2-3B` (router), `nomic-embed-text` (embeddings).

## Comandos útiles
- `docker compose up -d` — levanta Neo4j + Qdrant + Redis.
- `start_ecosystem.bat` — arranque rápido (Windows).
- `python agents/orquestador.py` — prueba del nodo PM (LangGraph).
