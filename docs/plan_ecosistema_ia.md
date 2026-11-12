# PLAN DE TRABAJO: Ecosistema Completo de IA para Programación (ADES-AI v2.0)

> **Estado:** **v1.1** — Fases 0-10 + Fase 12 (integración, 7 bugs corregidos, 31 features) verificadas con tests y KPIs medidos · **KPI 5 NO cumplido** (requiere vLLM) · **Fecha:** 11 de Noviembre de 2026
> **Proyecto:** ADES-AI (Autonomous Development Ecosystem with Artificial Intelligence)
> **Este documento es la fuente de verdad del proyecto.** Léelo al inicio de cualquier sesión para retomar el contexto sin repetirlo.

---

## 0. Contexto y recursos disponibles

**Recursos del desarrollador:**
- 🟢 **Gemini Plus** (Google) → razonamiento y arquitectura en nube (modelos 2026: serie Gemini 4 / Flash)
- 🟢 **OpenCode Go** → endpoint OpenAI-compatible con modelos DeepSeek V4 (`deepseek-v4.1-flash`, `deepseek-v4-pro`)
- 🟢 **GPU 16GB VRAM** → LLMs locales (sweet spot 2026: modelos ~20-27B cuantizados, o MoE con offload)

**Estado actual del proyecto (v1.1 — verificado el 11/11/2026):**

| Componente | Estado | Detalle |
|---|---|---|
| `docker-compose.yml` | ✅ Verificado | Neo4j (APOC) + Qdrant + Redis + **Bifrost configurado** (virtual keys con scope) |
| `docker-compose.langfuse.yml` | ✅ Verificado | Langfuse v4 completo (Postgres + ClickHouse + Redis + MinIO); el anterior (solo Postgres) no podía arrancar |
| `core/` | ✅ Nuevo | Pasarela LLM única (fallback en cascada, timeout duro, circuit breaker, presupuesto, caché, Langfuse), sandbox Docker, GPU manager, multi-proyecto |
| `agents/` | ✅ Integrado | La fábrica usa roster, router, memoria, RepoMap, validador anti-alucinación, sandbox y MCP (antes eran módulos aislados) |
| `memory/` | ✅ Completo | + validador anti-alucinación, memoria cross-proyecto, vacunas, timeline, consolidación |
| `cache/` | ✅ Corregido | Caché semántico sin falsos positivos (umbral 0.95, contexto exacto, similitud solo sobre la pregunta) |
| `registry/` | ✅ Completo | + ratings, conflictos, pinning/rollback, escaneo en sandbox, cuarentena |
| `evals/` | ✅ Completo | + benchmark, LLM Council, regression detector, A/B, auditoría anti-IA; tracing real a Langfuse |
| `automation/` | ✅ Nuevo | Watchdog, prefetch, voz (texto), ModelPool/serving, auto-skills, automejora |
| `dashboard/` + `ades_cli.py` | ✅ Nuevo | Panel web en vivo y CLI unificado `ades` |
| `tests/` + `kpis/` | ✅ Nuevo | 230 tests (unitarios + live) y mediciones reproducibles de los KPIs |

**Punto clave:** la v1.0 tenía todos los módulos, pero desconectados entre sí, y ningún KPI estaba medido. La v1.1 los integra, corrige los bugs que impedían alcanzar los KPIs y los mide con datos reales (sección 8). Los KPIs 1-4 se cumplen. El **KPI 5 no**, porque vLLM no puede ejecutarse en Windows + AMD. Pendiente: Fase 11 y la deuda técnica registrada en la Fase 10.

---

## 1. Visión: el ecosistema de 3 cerebros + 4 capas de contexto

Un ecosistema **híbrido** que asigna cada tarea al modelo óptimo según costo/latencia/capacidad, y que administra el contexto en capas para ahorrar ~90% de tokens.

```
🧠 CEREBRO 1 — NUBE (razonamiento pesado)
   Gemini (Argon/Flash)      → Arquitectura, planificación, System 2
   OpenCode Go (DeepSeek V4) → Código complejo, refactors, review
   Claude Haiku 5.5 / Luna   → Routing barato ($0.10/M, clasificación/sumarios)
        ↓  (baja latencia, alto costo)
🧠 CEREBRO 2 — LOCAL (GPU 16GB, costo $0)
   gpt-oss:20b / Qwen3.8 27B → codificación iterativa, agentes, autocompletado
        ↓
🧠 CEREBRO 3 — MEMORIA (contexto infinito sin quemar tokens)
   Neo4j + Graphiti (grafo temporal) + Qdrant (vectorial) + Mem0 (hechos) + Cognee (KG documentos)
```

Y **4 capas de contexto** (la clave del ahorro del 90%):

```
Capa 1 — AGENTS.md          → instrucciones permanentes (siempre en caché, cortas)
Capa 2 — SKILL.md           → procedimientos bajo demanda (progressive disclosure)
Capa 3 — Grafo/RepoMap      → esqueleto del código (3k tokens, no 100k)
Capa 4 — Subagentes         → contexto aislado por tarea (bounded work)
```

---

## 2. Núcleo del ecosistema: OpenCode como orquestador central

**Decisión clave de la investigación:** tu cuenta **OpenCode Go** y tu entorno actual ya corren sobre **OpenCode** (~202k estrellas, MIT), que en 2026 es EL agente open-source de referencia: agnóstico de proveedor, con **Skills**, **Plugins**, **subagentes**, **MCP** y **LSP** nativos. El ecosistema debe girar en torno a OpenCode + un backend LangGraph para la "fábrica" autónoma.

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Harness/agente principal** | **OpenCode** (ya lo usas) | Claude Code / Codex CLI / Cline |
| **Skills framework** | **Obra Superpowers** (247k ⭐) | Superpowers + oh-my-opencode |
| **Multi-agente plugin** | **oh-my-opencode** | — |
| **Motor de la fábrica autónoma** | **LangGraph** (backend Python) | CrewAI / MetaGPT / ChatDev 2.0 |

> OpenCode es tu **capa de interacción diaria** (planear, editar, ejecutar con subagentes). LangGraph es el **motor de la fábrica autónoma** (PM → Arquitecto → Developer ⇄ QA), que corre desatendido.

---

## 3. Capas del ecosistema (recomendado + alternativas)

### 3.1 Capa de Inferencia Local (GPU 16GB) — MODELOS ACTUALIZADOS 2026

> ⚠️ **Corrección crítica al plan anterior:** los modelos cambiaron. Qwen2.5-Coder-14B ya es generación pasada. Para 16GB VRAM en 2026:

| Rol | ⭐ Recomendado | Alternativa | Notas |
|---|---|---|---|
| **Runtime (1 usuario)** | **Ollama** | LM Studio / llama.cpp | Simple, OpenAI-compatible, carga bajo demanda |
| **Runtime (producción)** | **vLLM** (PagedAttention) | — | 10-24x más throughput concurrente; para cuando la fábrica tenga muchos agentes |
| **Código principal** | **gpt-oss:20b** | Qwen3-Coder 30B (MoE, offload) | Mejor coding model que cabe en 16GB (178-190 tok/s) |
| **General + razonamiento** | **Qwen3.8 27B** (IQ3_S ≈ 13.8GB) | Gemma 4 12B / Devstral Small | Thinking nativo, multimodal, agéntico |
| **Router/compresor rápido** | **Llama-3.2-3B** | Gemma 4 4B | Clasifica tareas y comprime contexto ($0) |
| **Embeddings** | **nomic-embed-text** | bge-m3 / Gemini text-embedding-004 | Para Qdrant y GraphRAG |

> **Regla de oro 16GB:** NUNCA dos modelos grandes a la vez. Residente: 1 modelo grande (20-27B) + 1 pequeño (3B). El resto en disco, cargan bajo demanda. Con **vLLM** puedes servir el modelo grande a múltiples agentes concurrentes sin saturar la GPU.

### 3.2 Capa Cloud — MODELOS ACTUALIZADOS 2026

| Rol | ⭐ Recomendado | Alternativa | Cuándo usarlo |
|---|---|---|---|
| **Arquitectura/PM** | **Gemini (tu plan Plus)** | — | PRDs, diseño de sistemas, decisiones difíciles |
| **Código nube** | **OpenCode Go: deepseek-v4-pro** | deepseek-v4.1-flash | Refactors grandes, debugging profundo |
| **Routing ultra-barato** | **Claude Haiku 5.5 / GPT-6 Luna** ($0.10/M) | Gemini Flash | Clasificación, sumarios, extracción de hechos |
| **Prompt caching** | **Gemini nativo + header `x-opencode-session`** | — | Contexto estático al inicio = hasta -90% en input |

> Ya implementaste el `x-opencode-session` para cacheo ✅. Modelos actualizados: Gemini usa `GEMINI_MODEL` (configurable, por defecto `gemini-flash-latest`). Prompt caching (estático primero) implementado en Fase 7 (`cache/prompt_cache.py`).

### 3.3 Capa de Memoria (anti-alucinaciones) — MEJORADA

La investigación revela que el RAG vectorial puro quedó atrás; 2026 combina **grafo temporal + hechos + documentos**:

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Grafo de código (temporal)** | **Graphiti (Zep)** sobre Neo4j | LightRAG | ✅ (Fase 2) |
| **Grafo/vectorial base** | **Neo4j 5.23** | Memgraph | ✅ Ya en Docker |
| **Vectorial (semántica)** | **Qdrant** | Pinecone / Chroma | ✅ Ya en Docker |
| **Hechos personales (largo plazo)** | **Mem0** | Zep / Letta | ✅ (Fase 2) |
| **KG de documentos + MCP** | **Cognee** (Apache 2.0) | Microsoft GraphRAG | ✅ (Fase 2) |
| **Indexador código → grafo** | **Tree-sitter** → Graphiti/Neo4j | Aider RepoMap | ✅ (Fase 2) |

**Por qué esta combinación:**
- **Graphiti** (Apache 2.0, sobre Neo4j): construye el grafo de tu código de forma **incremental y temporal** — sabe qué clases existen, sus relaciones, y cuándo cambiaron. Anti-alucinación estructural real.
- **Mem0**: extrae "hechos" del usuario (preferencias, decisiones) con la mejor precisión en LongMemEval (93.4%).
- **Cognee**: convierte docs/repos en grafo de conocimiento, y trae **servidor MCP** (`cognee-mcp`) + integraciones con Claude Code/Cursor/LangGraph/Neo4j.
- **Qdrant**: búsqueda vectorial rápida como complemento.

### 3.4 Capa de Orquestación

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Motor de grafos (fábrica)** | **LangGraph** | CrewAI / OpenAI Agents SDK / MetaGPT | ✅ Grafo completo (Fase 3) |
| **Orquestación multiagente OpenCode** | **oh-my-opencode** | Obra Superpowers | ✅ (Fase 4) |

LangGraph gana por **ciclos** (Dev ⇄ QA hasta pasar), checkpoints, recuperación y human-in-the-loop. `oh-my-opencode` orquesta flotas de agentes (Sisyphus, Oracle, Librarian, Explore, Atlas, Prometheus, Metis, Momus) con modo "ultrawork" y enrutamiento por categoría.

### 3.5 Capa de Agentes (la "Software Factory" + enjambre)

**Agente 0 — Reclutador (meta-agente, el primero en crearse):** crea, modifica y elimina a los demás agentes según lo que pidas (*"Crea un agente especializado en UX/UI"*). Para cada agente elige el **LLM óptimo** (nube OpenCode Go vs local), le asigna **skills**, **herramientas MCP**, **permisos** y **acceso a memoria**, y lo registra en `agents/roster.json` (el registro de agentes). Funciona igual que el Tool Registry, pero para agentes.

**Roster inicial de agentes (primer arranque sólido):**

| Agente | LLM asignado | Función |
|---|---|---|
| **Reclutador** | deepseek-v4-pro (nube) | meta-agente: crea/gestiona al resto |
| **PM** | Gemini (nube) | requerimiento → PRD + tickets |
| **Arquitecto** | Gemini (nube) | diseño de sistemas y stack |
| **Dev Backend** | gpt-oss:20b (local) | APIs y servicios (Python/FastAPI) |
| **Dev Frontend** | Qwen3.8 (local) | UI (React/Next.js) |
| **QA/Tester** | local + nube | pruebas en sandbox Docker + LAM, feedback (bucle cerrado con Dev) |
| **Code Reviewer** | deepseek-v4-pro (nube) | revisión de diffs (seguridad/calidad) |
| **DevOps** | deepseek-v4.1-flash (nube) | CI/CD, Docker, despliegue |
| **Explorador** | Llama-3.2-3B (local) | explorar código y documentación |

**Flujo de la fábrica (LangGraph):** Reclutador → PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps.

**Enjambre de subagentes (OpenCode + oh-my-opencode):** cada tarea se delega a subagentes con contexto acotado (Explore para investigar código, Librarian para memoria, Oracle para planificar), evitando contaminar el contexto principal.

> **Nota:** el Reclutador puede crear agentes adicionales bajo demanda (UX/UI, datos, seguridad, etc.) y asignarles el modelo más barato que cumpla su tarea, respetando tu presupuesto de tokens.

### 3.6 Capa de Skills (NUEVA — la gran novedad 2026)

Las **Skills** (archivos `SKILL.md`) son capacidades reutilizables que se cargan **solo bajo demanda**, con *progressive disclosure*: el agente lee por etapas en vez de tragarse todo. Esto es ahorro de tokens estructural, no cosmético.

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Instrucciones permanentes** | **AGENTS.md** (estándar cross-tool) | CLAUDE.md | ✅ Creado |
| **Framework de skills** | **Obra Superpowers** (247k ⭐) | Superpowers | ✅ (Fase 4) |
| **Skills propias** | `.opencode/skills/` | `.claude/skills/` | ✅ (Fase 4) |

**Obra Superpowers** aporta un ciclo completo: `brainstorming` → `writing-plans` → TDD → `subagent-driven-development` → `systematic-debugging` → verificación. Incluye la "regla del 1%" (si hay 1% de probabilidad de que una skill aplique, úsala).

### 3.7 Capa MCP (herramientas del agente)

47k+ servidores MCP activos en 2026. Para escalar, añade un **gateway**:

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Gateway MCP (escala/seguridad)** | **Bifrost** (Maxim AI, Go, open source) | Cloudflare / Kong AI Gateway |
| **Servidores prioritarios** | filesystem, git, GitHub, memory, sequential-thinking | — |
| **Web/QA** | **Firecrawl MCP** + Playwright | — |
| **Memoria GraphRAG** | **cognee-mcp** | — |
| **DB** | Supabase/Postgres MCP | — |

> Configurables en `mcp_servers/mcp_config.json`, consumibles por OpenCode, Cline y tu backend LangGraph por igual.

### 3.8 Capa de IDE/Interfaz

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Agente principal** | **OpenCode** (terminal/desktop/IDE) | Claude Code |
| **Editor agentico (VS Code)** | **Cline** | Cursor / Windsurf / RooCode |
| **Terminal (git-aware)** | **Aider** | — |
| **Autónomo (issues → PR)** | **OpenHands** | Devin |

### 3.9 Capa de Evaluación y Observabilidad

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Trazabilidad + eval OSS** | **Langfuse** (MIT, OpenTelemetry, self-host) | LangSmith / MLflow |
| **Eval de RAG** | **Ragas** / **DeepEval** | — |
| **Red-team/seguridad** | **Promptfoo** | — |
| **Eval-first comercial** | **Braintrust** (free tier) | — |

Registra cada llamada, costo en tokens, latencia y calidad. Sin esto, optimizar tokens es adivinar.

### 3.10 Capa de Optimización de Tokens (LA ESTRATEGIA DEL 90%)

⚠️ **Dato honesto de la investigación:** el 90% sostenido solo se logra **apilando todas** las técnicas (70-80% es lo realista con una buena implementación; 90% en cargas repetitivas bien cacheadas). Estrategia en orden de impacto:

| # | Técnica | Ahorro | Herramienta |
|---|---|---|---|
| 1 | **Prompt caching** | 70-90% input | Gemini nativo + `x-opencode-session` |
| 2 | **Model routing** | 60-80% | Router local (Llama-3.2-3B) → Haiku 5.5/Luna ($0.10) → local $0 → pesado |
| 3 | **Semantic caching** | 40-70% | **Redis + GPTCache** (respuestas repetidas no pagan) |
| 4 | **Context engineering / Skills** | 30-50% | AGENTS.md corto + SKILL.md bajo demanda |
| 5 | **RepoMaps / GraphRAG** | 90% del código | Tree-sitter → Graphiti/Neo4j (esqueleto, no código) |
| 6 | **Compresión de prompt** | 30-50% | **LLMLingua-2** / **SuperCompress** (MCP) |
| 7 | **Subagentes acotados** | reduce contexto principal | subagents con tareas delimitadas |
| 8 | **Local $0** | 100% de tareas iterativas | gpt-oss:20b / Qwen3.8 |

**Repo de referencia:** `pleasedodisturb/awesome-llm-token-optimization` (catálogo curado de estrategias y papers).

### 3.11 Capa de Seguridad y Despliegue

| Rol | ⭐ Recomendado | Notas |
|---|---|---|
| **Sandbox** | Docker (contenedor efímero por agente) | QA NUNCA ejecuta fuera de contenedor |
| **Secretos** | `.env` + `python-dotenv` + rotación | **Rotar keys expuestas en el repo** |
| **Config global** | AGENTS.md (+ `.cursorignore`) | Reglas permanentes, se cachean |
| **MCP seguro** | Bifrost gateway | Autenticación y scope por tool call |

### 3.12 Capa de Registro de Herramientas Integrables (el "marketplace" del ecosistema)

El **Tool Registry** es la pieza que te permite llegar a tu espacio de trabajo y decir *"integra X en el proyecto Y"* sin tener que buscar herramientas cada vez. Es un catálogo persistente de repos de GitHub (skills, MCPs, herramientas, plugins, modelos y apps) que los agentes pueden **integrar bajo demanda**, **activar/desactivar por proyecto**, y **hacer crecer recursivamente** (*"agrega tal repo a ADES-AI"*).

**Cómo funciona:**
1. **Catálogo** (`registry/catalog.json`): lista versionada de repos con metadatos (tipo, URL, descripción, método de instalación, estado, licencia).
2. **Estado** (`registry/state.json`): qué herramientas están activas y en qué proyecto, con su commit/versión.
3. **Integrador** (skill del agente): aplica la integración según el tipo de herramienta.
4. **Toggle**: activar/desactivar sin desinstalar — solo cambia lo que se carga en contexto (ahorro de tokens).

**Métodos de integración por tipo:**

| Tipo | Acción del integrador |
|---|---|
| `skill` | copiar a `.opencode/skills/<id>/` |
| `mcp` | añadir entrada a `mcp_servers/mcp_config.json` con `"enabled": true/false` |
| `tool` / `cli` | instalar binario o añadir dependencia |
| `plugin` | registrar en `opencode.json` → `plugins` |
| `model` | `ollama pull <modelo>` |
| `app` | añadir servicio a `docker-compose.yml` |

**Comandos de voz (lo que le dices al agente):**
- *"Integra `<herramienta>` en `<proyecto>`"* → busca en el catálogo y la integra
- *"Activa / desactiva `<herramienta>`"* → alterna el estado sin desinstalar
- *"Agrega `<url-de-github>` a ADES-AI"* → añade el repo al catálogo (recursivo)
- *"¿Qué herramientas hay para `<tarea>`?"* → búsqueda en el catálogo
- *"Lista herramientas integradas"* → estado actual

**Repos piloto (los primeros del catálogo):**

| ID | Repo | Tipo | Qué aporta |
|---|---|---|---|
| `ecc` | `affaan-m/ECC` (org `ECC-Tools`) | skill | Framework de skills/reglas/hooks/seguridad para agentes (274k ⭐) |
| `llm-council` | `karpathy/llm-council` | app | Consejo multi-LLM: varios modelos se revisan entre sí (LLM-as-judge) |
| `llmfit` | `AlexsJones/llmfit` | tool | Recomienda qué modelo corre en tu hardware (38k ⭐) |
| `web-llm` | `mlc-ai/web-llm` | sdk | Inferencia de LLMs en el navegador (WebGPU) |

---

## 4. Stack recomendado — resumen ejecutivo

| Capa | ⭐ Decisión final |
|---|---|
| Harness principal | **OpenCode** (ya lo usas) |
| Skills | **Obra Superpowers** + skills propias (`AGENTS.md` + `SKILL.md`) |
| Multi-agente OpenCode | **oh-my-opencode** |
| Motor fábrica | **LangGraph** |
| Runtime local | **Ollama** (→ **vLLM** al escalar) |
| Coding local | **gpt-oss:20b** (alt: Qwen3.8 27B) |
| Router/compresor | **Llama-3.2-3B** + **LLMLingua-2** |
| Embeddings | **nomic-embed-text** |
| Nube arquitectura | **Gemini (Plus)** |
| Nube código | **OpenCode Go (DeepSeek V4)** |
| Nube routing barato | **Claude Haiku 5.5 / GPT-6 Luna** |
| Grafo código | **Graphiti** sobre **Neo4j** ✅ |
| Vectorial | **Qdrant** ✅ |
| Hechos largo plazo | **Mem0** |
| KG documentos | **Cognee** (+ MCP) |
| Semantic cache | **Redis + GPTCache** |
| Indexador | **Tree-sitter → Graphiti/Neo4j** |
| MCP | filesystem, git, GitHub, memory, sequential-thinking, Firecrawl, cognee-mcp + **Bifrost** |
| Editor | **Cline (VS Code)** + Aider + OpenHands |
| Observabilidad | **Langfuse** (+ DeepEval/Ragas/Promptfoo) |
| Evaluación | LLM-as-a-Judge |
| Registro de herramientas | **Tool Registry** (`registry/catalog.json` + `state.json`) |

---

## 5. Roadmap por fases (reestructurado)

### FASE 0 — Cimientos y seguridad (estado: 100% ✅)
- [x] Docker (Neo4j + Qdrant)
- [x] LangGraph con nodo PM
- [x] **Rotar keys expuestas** en `.env` (GEMINI + OPENCODE) — claves rotadas y actualizadas en `.env` (no versionado), `.gitignore` corregido y scanner de secretos (`environment/scan_secrets.py`)
- [x] Corregir `docker-compose.yml` (eliminar `version:` deprecada; añadir Redis)
- [x] Crear `AGENTS.md` raíz (corto, permanente)

### FASE 1 — Cerebro local (GPU) (estado: 100% ✅ — vLLM se difiere a Fase 9)
- [x] Instalar **Ollama** + modelos: `gpt-oss:20b` (13GB), `qwen3.8:27b-iq3` (GGUF local IQ3-MIX, 12GB), `llama3.2:3b` (2GB), `nomic-embed-text` (274MB)
- [x] Script `environment/setup_ollama.ps1` (+ `environment/benchmark_local.py`)
- [x] Benchmark gpt-oss:20b vs Qwen3.8: **gpt-oss 93.8 tok/s** vs qwen3.8 26.5 tok/s (con thinking). Ambos 100% GPU vía ROCm
- [ ] (Opcional, Fase 9+) instalar **vLLM** para servir el modelo a muchos agentes — se difiere

> **Nota de hardware (Fase 1):** la GPU real es una **AMD Radeon RX 9070 XT (16GB)**, no NVIDIA como asumía el plan. Ollama la usa vía **ROCm** (`compute=gfx1201`). El tag `IQ3_S` de Qwen3.8 no existe en el registro; se importa `Qwen3.8-27B-IQ3-MIX.gguf` local con `ollama create`. Para 16GB, acotar `num_ctx` (~8192) para que los modelos de 12-13GB quepan en VRAM.

### FASE 2 — Memoria completa (el pilar anti-alucinación) (estado: 100% ✅)
- [x] Levantar **Graphiti** (sobre Neo4j existente) — `memory/graphiti_client.py` (con monkeypatch de bug de graphiti-core 0.31.2 para Neo4j 5.23)
- [x] Integrar **Mem0** (hechos personales/preferencias) — `memory/mem0_client.py` (Qdrant + nomic-embed-text + OpenCode Go)
- [x] Levantar **Cognee** + `cognee-mcp` (KG de documentos) — `memory/cognee_client.py` (Neo4j + APOC + Ollama local + LanceDB)
- [x] Implementar **indexador Tree-sitter → Graphiti/Neo4j** (`memory/indexer.py`)
- [x] Script para (re)indexar un repo bajo demanda — `python -m memory.indexer --repo <ruta> [--reset]`

> **Notas de Fase 2:** (1) `graphiti-core` 0.31.2 tiene un bug en la query bulk de Neo4j (`SET n:$(node.labels)`); se corrige con monkeypatch en `graphiti_client.py` y hay que llamar `build_indices_and_constraints()` antes de ingerir. (2) Mem0 v2 cambió `search()` a `filters={'user_id': ...}`. (3) Cognee 1.6.6 **no soporta Qdrant** (usa LanceDB/PGVector) y **requiere el plugin APOC** en Neo4j (añadido a `docker-compose.yml` con `NEO4J_PLUGINS=["apoc"]`); su LLM usa Ollama local para evitar el header de OpenCode Go.

### FASE 3 — Fábrica multiagente (LangGraph) (estado: 100% ✅)
- [x] Crear el **Agente Reclutador** (meta-agente) — `agents/reclutador.py`
- [x] Crear el **roster inicial de agentes** (9 agentes) — `agents/roster.json` + `agents/roster.py`
- [x] Refactorizar `orquestador.py` → grafo completo — `agents/orquestador.py` + nodos `pm/arquitecto/developer/qa/reviewer.py`
- [x] **Router** (Llama-3.2-3B) — `agents/router.py` (clasifica tarea → modelo, con fallback heurístico)
- [x] Bucle cerrado Dev⇄QA con checkpoint — `add_conditional_edges` + `MemorySaver`
- [x] Actualizar nombres de modelo (Gemini 2026, deepseek-v4) — sin nombres desactualizados; `GEMINI_MODEL` configurable

> **Notas de Fase 3:** (1) La fábrica corre end-to-end con modelos reales: PM/Arquitecto→Gemini, Developer/QA→`gpt-oss:20b` (local), Reviewer→`deepseek-v4-pro`, DevOps→`deepseek-v4.1-flash`; Gemini es intermitente (503/429 transitorios de Google). (2) El Reclutador asigna LLM por rol (UX→qwen3.8, backend→gpt-oss:20b, revisor/arquitecto→deepseek-v4-pro, explorador→llama3.2:3b). (3) El router usa llama3.2:3b y cae a heurístico si el modelo local no responde.

### FASE 4 — Skills y subagentes (OpenCode) (estado: 100% ✅)
- [x] Instalar **Obra Superpowers** (plugin) + **oh-my-opencode** (skills) — clonados en `.opencode/vendor/` (gitignored) y referenciados en `opencode.json`
- [x] Crear skills propias en `.opencode/skills/` — `indexar-repo`, `memoria`, `benchmark-local`, `fabrica`
- [x] Configurar subagentes (Explore, Librarian, Oracle) con contexto acotado — `.opencode/agents/{explore,librarian,oracle}.md`
- [x] Definir `AGENTS.md` anidados por carpeta — `agents/`, `memory/`, `environment/`

> **Notas de Fase 4:** (1) Obra Superpowers se instala como **plugin** (`plugins` en `opencode.json`), no como skills; se clonó a `.opencode/vendor/superpowers` (v7.0.2) y se referencia localmente. (2) oh-my-opencode (OmO) es un CLI standalone; se integraron sus skills compatibles con OpenCode (`github-triage`, `pre-publish-review`, `work-with-pr`) vía el array `skills`. (3) Las skills propias y las de oh-my-opencode ya son descubiertas por OpenCode en runtime. (4) `.opencode/vendor/` está **gitignored** (no se versionan ~12.9k archivos); si se pierde (cambio de rama, `git clean`, borrado manual), re-clónalo con `environment/setup_fase4.ps1`.

### FASE 5 — Registro de Herramientas Integrables (Tool Registry) (estado: 100% ✅)
- [x] Crear `registry/catalog.json` (esquema de metadatos) + `registry/state.json`
- [x] Implementar el **integrador** (`registry/integrator.py`) con los 6 métodos de integración
- [x] Registrar los **4 repos piloto**: `ecc` (skill), `llm-council` (app), `llmfit` (tool), `web-llm` (sdk)
- [x] Implementar los comandos de voz (`registry/cli.py`: list / search / add / integrate / activate / deactivate)
- [x] Probar el flujo recursivo: *"Agrega `<repo>` a ADES-AI"* — `add <url>` deriva el id y lo registra

> **Notas de Fase 5:** (1) El integrador mapea tipo→método: `skill`→clonar a `.opencode/skills/`, `mcp`→`mcp_config.json`, `tool`/`cli`/`sdk`→`registry/tools/`, `plugin`→`opencode.json`, `model`→`ollama pull`, `app`→`docker-compose.yml`. (2) `integrate --dry-run` devuelve el plan sin efectos secundarios. (3) `sdk` (web-llm) se integra como `tool` (dependencia), ya que el plan no define un método específico para SDKs.

### FASE 6 — MCP + gateway (estado: 100% ✅)
- [x] Crear `mcp_servers/mcp_config.json` (7 servidores)
- [x] Levantar MCP: filesystem, git, GitHub, memory, sequential-thinking, Firecrawl, cognee-mcp
- [x] Instalar **Bifrost** como gateway (auth + scope) — servicio `gateway` en `docker-compose.yml` + `mcp_servers/gateway/README.md`
- [x] Conectar orquestador a MCP (Developer lee/escribe archivos reales) — `mcp_servers/client.py`

> **Notas de Fase 6:** (1) El cliente MCP (`mcp_servers/client.py`) usa el SDK oficial `mcp` y se probó contra el servidor `filesystem` real (npx): lista 14 herramientas y lee archivos del proyecto. (2) Bifrost se instaló como contenedor `maximhq/bifrost` (puerto 8080, Web UI en `http://localhost:8080`); provee auth/scope, failover y caché semántico. (3) Los secretos (GitHub/Firecrawl) se pasan con placeholders `${VAR}`; el cliente omite los no definidos. (4) `cognee-mcp` es un servidor **SSE** (no stdio): se arranca con Docker (`cognee/cognee-mcp:main`, `TRANSPORT_MODE=sse`) y se expone en `http://127.0.0.1:8001/sse` (resuelto en Fase 10 con soporte `sse_client`).

### FASE 7 — Optimización de tokens (objetivo 90%) (estado: 100% ✅)
- [x] **Prompt caching**: reordenar contexto (estático primero) — `cache/prompt_cache.py`
- [x] **Semantic caching**: Redis + GPTCache para respuestas repetidas — `cache/semantic_cache.py` (Redis + embeddings, umbral 0.60)
- [x] **RepoMaps** en uso real — `memory/repomap.py` (esqueleto desde Neo4j; **99.9% menos** que el código completo)
- [x] **LLMLingua-2** para compresión de RAG y prompts — `cache/prompt_compressor.py` (requiere `use_llmlingua2=True`)
- [x] **Model routing** fino: hit-rate y costo/tarea — `cache/token_metrics.py`

> **Notas de Fase 7:** (1) El caché semántico usa Redis + `nomic-embed-text` (coseno) con umbral 0.60; GPTCache quedó instalado como alternativa de producción. (2) El RepoMap se genera desde el grafo de código (Fase 2) y mide el ahorro real. (3) LLMLingua-2 requiere la flag `use_llmlingua2=True` (sin ella usa el code path de LLaMA y falla con BERT). (4) **Conflicto de dependencias resuelto**: `llmlingua` sube `huggingface-hub` a 2.x, incompatible con cognee/fastembed/litellm (`<2.0`); se fijó `huggingface-hub<1.0` + `transformers<5.0,>=4.26` en `requirements.txt`. (5) El umbral de similitud y los costos por modelo son aproximados/configurables.

### FASE 8 — Evaluación y observabilidad (estado: 100% ✅)
- [x] Levantar **Langfuse** — `docker-compose.langfuse.yml` (postgres + langfuse) + `evals/tracing.py` (SDK con fallback a JSONL)
- [x] Suite **LLM-as-a-Judge** para cada agente — `evals/judge.py` + `evals/cases/casos.json`
- [x] **Ragas/DeepEval** para calidad de RAG — `evals/rag_eval.py` (faithfulness / answer_relevance / context_relevance vía juez)
- [x] **Promptfoo** para red-team/seguridad — `evals/promptfooconfig.yaml`
- [x] Dashboard de costo en tokens por agente — `evals/dashboard.py` (sobre `cache/token_metrics.py`)

> **Notas de Fase 8:** (1) Langfuse self-host usa un stack mínimo (postgres + langfuse); para escala se añaden ClickHouse/MinIO/Redis según la guía oficial. El tracing funciona con fallback a `evals/traces.jsonl` si no hay servidor Langfuse. (2) El juez usa DeepSeek V4 (OpenCode Go) y devuelve score 1-10 + verdict PASS/FAIL + rationale. (3) RAG eval es ligero (juez propio); **Ragas/DeepEval no se instalaron** para evitar conflictos de dependencias con cognee/fastembed/litellm (mismo motivo que en Fase 7). (4) Promptfoo corre con `npx promptfoo eval -c evals/promptfooconfig.yaml`.

### FASE 9 — Escalado, autonomía y fine-tuning (estado: 100% ✅ — el punto opcional pasa a Fase 11)
- [x] Migrar local a **vLLM** — `environment/setup_vllm.sh` (documentado; aplica cuando la fábrica exija concurrencia en Linux+CUDA/ROCm)
- [x] Workflow **OpenHands**: issue de GitHub → PR automático — `environment/setup_openhands.md`
- [x] Fine-tuning de un SLM (Qwen 3B/8B) vía **Unsloth** — `environment/finetune_unsloth.py` (documentado; requiere NVIDIA/CUDA)
- [→] (Opcional) Agentes en entorno simulado (Godot/Phaser) — **movido a Fase 11 (v2.0)**

> **Notas de Fase 9:** (1) vLLM y Unsloth requieren **Linux + NVIDIA/CUDA**; en la máquina de desarrollo (Windows + AMD RX 9070 XT) se sigue usando Ollama vía ROCm, por lo que estos scripts son artefactos documentados para el entorno de despliegue/entrenamiento (nube o host CUDA). (2) OpenHands corre vía Docker y complementa a la fábrica LangGraph (issue externo → PR vs requerimiento interno).

### FASE 10 — Completar integraciones y deuda técnica pendiente (estado: 100% ✅)
- [x] Añadir soporte **SSE** al cliente MCP (`mcp_servers/client.py`): `sse_client` junto a `stdio_client`
- [x] Conectar **cognee-mcp** de punta a punta — imagen Docker `cognee/cognee-mcp:main` (`TRANSPORT_MODE=sse`) → `http://127.0.0.1:8001/sse`; probado (6 herramientas)
- [x] Implementar el método `app` del integrador del Tool Registry — añade el servicio a `docker-compose.yml`
- [x] Acotar `num_ctx` en los nodos de la fábrica — `extra_body={"num_ctx": 8192}` (configurable vía `OLLAMA_NUM_CTX`)

#### Deuda técnica pendiente (registrada en v1.1, 11/11/2026)
- [ ] **KPI 5 / vLLM**: desplegar y medir `environment/vllm/docker-compose.{rocm,cuda}.yml` en un host Linux (ROCm o CUDA). Nunca se ejecutó: las imágenes, los ids de HF y el reparto de `gpu_memory_utilization` están sin verificar.
- [ ] **Voz (#28)**: la entrada de audio real (`listen()`) no se probó; no hay `SpeechRecognition` ni `faster-whisper` instalados. Solo funciona la vía de texto.
- [ ] **Tareas programadas**: `schedule_nightly()` (#7), `watchdog.install_task()` (#3) y el toast de Windows solo se probaron en dry-run.
- [ ] **Automejora (#32)**: no se ha ejecutado de punta a punta con el `check_prompt_change` real (los tests inyectan el evaluador).
- [ ] **Backlog (#2)**: `work_background()` (proceso desacoplado) no se probó con modelos reales; `work()` sí.
- [ ] **Registry**: definir el comando de arranque de los MCP que vienen de git (quedan `enabled:false`); la imagen real de `llm-council` (hoy es placeholder en el perfil `registry`); el escaneo de herramientas que no vienen de git (modelos/npm) es solo revisión manual; nada se probó contra GitHub real (clones `--depth 1`, fetch de refs remotos).
- [ ] **Graphiti en el timeline**: con el LLM local tarda ~60-90 s por episodio; en la fábrica se registra en un hilo daemon, así que si el proceso CLI termina antes, el episodio puede perderse (el registro local SQLite sí queda).
- [ ] **Benchmark (#17)**: discrimina poco (los 3 modelos sacan 2/2); faltan tareas más difíciles o multiarchivo. `casos.json` tiene pocos casos para el regression detector.
- [ ] **Auditoría anti-IA (#24)**: la lista anti-typosquatting es offline y curada a mano (no consulta PyPI).
- [ ] **Umbrales** calibrados con pocas muestras: caché semántico 0.95, `recall` 0.62, vacunas 0.80, dedupe 0.95.
- [ ] **Sandbox**: la imagen solo trae fastapi/pydantic/httpx/requests/sqlalchemy/pytest/bandit. El código que importe otras librerías, o el propio ADES-AI, no puede probarse ahí (por eso el watchdog sobre ADES-AI entero fallaría).
- [ ] **Ollama**: el servidor usa contexto por defecto de 65536. Las variantes `-ctx16k` (`environment/setup_ollama_ctx.ps1`) son obligatorias con Bifrost; llamar directo a `/api/*` sin `num_ctx` dispara la VRAM.
- [ ] **Cuotas de nube**: durante las pruebas se agotó la cuota de OpenCode Go (429 "usage limit"). La cascada lo absorbe, pero conviene vigilarla (`ades tokens`).
- [ ] `shutil.rmtree(onerror=...)` está obsoleto desde Python 3.12 (registry). Ruido "Event loop is closed" de httpx al cerrar `asyncio.run` en Windows (Graphiti).

> **Notas de Fase 10 (resuelta):** (1) `cognee-mcp` es un servidor **SSE** (no stdio): se arranca con Docker (`cognee/cognee-mcp:main`, `TRANSPORT_MODE=sse`) en `http://127.0.0.1:8001/sse` — **NO** `cognee-cli serve`, que conecta a Cognee Cloud. (2) El método `app` inserta el servicio antes de `volumes:` preservando los comentarios (imagen `{id}:latest` placeholder). (3) `num_ctx` se acotó a 8192 vía `extra_body` en `agents/llm.py`.

### FASE 11 — Agentes en entorno simulado (v2.0)
- [ ] Agentes en entorno simulado (Godot/Phaser) — movido desde Fase 9 (opcional)

> **Nota:** el usuario quiere algo **muy complejo** — animaciones, zonas de trabajo, agentes visibles, etc. — por lo que se difiere a una **Fase 11 o versión 2.0** del ecosistema.

### FASE 12 — Integración, correcciones y features avanzadas (v1.1) (estado: ✅ verificada, salvo lo indicado)
Auditoría del 11/11/2026: los módulos existían pero no estaban conectados y ningún KPI se había medido. Hecho y verificado:
- [x] **7 bugs corregidos** (todos con test):
  1. La fábrica se colgaba >25 min ante un 503 de Gemini: ahora hay timeout duro, fallback en cascada y circuit breaker.
  2. El parser de QA marcaba FAIL cualquier texto con "error": ahora lee el veredicto solo de la primera línea.
  3. El caché semántico con umbral 0.60 daba falsos positivos.
  4. El integrador `app` rompía el `docker-compose.yml`.
  5. `x-opencode-session` se regeneraba en cada llamada, así que el prompt caching nunca acertaba.
  6. `_add_mcp` generaba entradas rotas.
  7. El Reclutador asignaba mal los modelos (PM/Arquitecto a DeepSeek; "docker" a llama3.2:3b).
- [x] **Bugs encontrados durante la verificación**:
  - El tracing a Langfuse fallaba en silencio (API v2 sobre el SDK 5.x).
  - El compose de Langfuse no podía arrancar.
  - El caché embebía contexto+pregunta: con un RepoMap largo, dos tareas distintas compartían respuesta (lo detectó el KPI 1).
  - Qwen3.8 rechazaba dos mensajes de sistema.
  - El router y la vía Bifrost cargaban modelos con 65536 de contexto (llama3.2:3b llegó a ocupar 10 GB).
  - El test de timeline fallaba de forma intermitente por guiones Unicode en las fechas.
  - El sandbox truncaba la salida de bandit.
  - Los subcomandos `ades bench/council/ab/audit/regression` no tenían `main()`.
- [x] **Integración**:
  - Todas las llamadas LLM pasan por `core.llm_gateway`.
  - QA ejecuta los tests en el sandbox Docker (`--network none`) con tests de aceptación propios.
  - Validador anti-alucinación contra Neo4j.
  - La fábrica usa RepoMap, memoria, vacunas y timeline.
  - Los archivos aprobados se escriben vía MCP filesystem.
  - Todo pasa por Bifrost, con virtual keys `ades-factory` (todo) y `ades-local` (solo Ollama).
  - Las métricas van a SQLite y Langfuse.
- [x] **31 features** de la sección 6 implementadas; ver allí el estado de cada una (2 quedan parciales).
- [x] **Tests**: `python -m pytest -q` → **230 passed, 0 failed** (11/11/2026, unitarios + live con Docker, Ollama, Neo4j, Redis, Langfuse y nube). **KPIs** medidos con `kpis/` (sección 8).

---

## 6. Características avanzadas del ecosistema (Features)

Las 33 features que amplían el plan. Cada una está etiquetada por prioridad (🔴 esencial · 🟡 alto valor · 🟢 opcional) y mapeada a la fase donde se implementa. *(10 🔴 esenciales · 15 🟡 alto valor · 8 🟢 opcionales)*

> **Estado de implementación (v1.1, verificado el 11/11/2026):** ✅ implementada y probada: 31 · ⚠️ parcial: 2 (#28 entrada de audio, #30 vLLM no ejecutado) · ❌ no implementada: 0. "Probada" significa que tiene tests que pasan (unitarios y/o live); las limitaciones de cada una están en su línea y en la Fase 10.

### A. Autonomía — "Software Factory" avanzada
1. 🔴 **Project Bootstrapper** — *"Crea un proyecto de X"* → PM + Arquitecto generan estructura, dependencias, CI y README en un comando. *(Fase 3)* → ✅ `agents/bootstrap.py` (`ades bootstrap`): proyecto + PRD/tickets + esqueleto (README, CI, Dockerfile, tests) + git + indexado. Test unitario con PM simulado
2. 🔴 **Backlog auto-gestionado (ticket-driven)** — el PM mantiene un kanban persistente de tickets; los Developers trabajan solos en background hasta agotarlos. *(Fase 3)* → ✅ `agents/backlog.py`: kanban persistente por proyecto y worker que agota tickets (reintento y luego `failed`). Test unitario; `work_background()` sin probar en vivo (Fase 10)
3. 🟡 **Agente "Watchdog" 24/7** — corre en background, vigila el repo por cambios rotos y alerta sin que lo pidas. *(Fase 3)* → ✅ `automation/watchdog.py`: detecta el cambio, compila, corre los tests en el sandbox y alerta. Test live con bug real; toast y schtasks solo en dry-run
4. 🟡 **Self-Healing pipeline** — si QA falla, reintenta con estrategia distinta (otro modelo, más contexto, otra librería) antes de rendirse. *(Fase 3)* → ✅ `agents/developer.py`: 5 estrategias por iteración (base → más contexto → otro modelo local → nube barata → nube pesada). Verificado en vivo (demo-api se corrigió en la iteración 3)
5. 🟡 **Multi-proyecto simultáneo** — un workspace con N proyectos, cada uno con su memoria, agentes y estado. *(Transversal)* → ✅ `core/projects.py`: workspace con N proyectos, cada uno con su estado, backlog, presupuesto, métricas y RepoMap

### B. Memoria permanente avanzada
6. 🔴 **Memoria cross-proyecto** — lo aprendido en el proyecto A (ej: "prefieres FastAPI") se reutiliza automáticamente en B. *(Fase 2)* → ✅ `memory/knowledge.py`: memoria global entre proyectos con embeddings; sync con Mem0 opcional. Test live
7. 🟡 **Consolidación nocturna (Reflection)** — proceso batch que resume el día, extrae lecciones y compacta la memoria. *(Fase 2)* → ✅ `memory/reflection.py`: deduplica, extrae lecciones con LLM y compacta. Test live; `schedule_nightly` solo en dry-run
8. 🟡 **"Vacuna" contra bugs** — cada bug resuelto se guarda como patrón para no repetirlo jamás. *(Fase 2)* → ✅ `memory/vaccine.py`: firma normalizada del error + corrección; QA la consulta y aprende al pasar. Test live
9. 🟢 **Timeline de decisiones** — con Graphiti: *"¿por qué decidimos X en marzo?"* con historial temporal. *(Fase 2)* → ✅ `memory/timeline.py`: episodios en Graphiti con fecha real + registro local; `why()` responde citando fechas. Test live (Graphiti con LLM local)

### C. Optimización de tokens
10. 🔴 **Token Budget Governor** — tope de gasto por tarea/proyecto; el router se adapta (local → barato → pesado). *(Fase 7)* → ✅ `core/budget.py`: presupuesto USD/tokens por proyecto con niveles any → cheap → local, aplicado en la pasarela. Tests
11. 🟡 **Cache Hit-Rate Dashboard** — métrica en vivo de cuánto estás ahorrando. *(Fase 7)* → ✅ `dashboard/app.py`: hit-rate, tokens y costo por minuto, refresco cada 3 s. Verificado en navegador con datos reales
12. 🟢 **Prefetch contextual predictivo** — precarga el contexto probable antes de pedirlo. *(Fase 7)* → ✅ `automation/prefetch.py`: predice contexto con el grafo (o léxico), lo precalienta con TTL y mide el hit-rate. Test live

### D. Tool Registry — extensiones
13. 🟡 **Marketplace interno con ratings** — puntuar/etiquetar herramientas ya probadas. *(Fase 5)* → ✅ `registry/ratings.py`: votos 1-5, tags y top. Tests
14. 🟡 **Detector de conflictos** — avisa si dos herramientas compiten (ej: dos MCP filesystem). *(Fase 5)* → ✅ `registry/conflicts.py`: capacidad, MCP, puerto y skill; bloquea `activate`/`integrate`. Tests
15. 🟡 **Version pinning + rollback** — fijar commit/versión de cada herramienta y revertir si rompe. *(Fase 5)* → ✅ `registry/versioning.py`: commit registrado, pin, update con historial y rollback. Tests con repos git locales
16. 🔴 **Instalación en sandbox + escaneo de seguridad** — auditar el repo (estilo AgentShield/Oathe) antes de activarlo. *(Fase 5)* → ✅ `registry/scanner.py` + `quarantine.py`: clon en cuarentena, reglas propias y bandit en Docker, con veredicto. Tests live

### E. Evaluación y calidad
17. 🟡 **Benchmark harness local** — mide a los agentes contra tareas estándar (estilo SWE-bench). *(Fase 8)* → ✅ `evals/benchmark.py`: 7 tareas con tests ocultos en el sandbox; pass@1, tokens y costo. Test live (discrimina poco, ver Fase 10)
18. 🔴 **LLM Council como juez por defecto** — el piloto `llm-council` integrado para decisiones difíciles y evaluación. *(Fase 8)* → ✅ `evals/council.py`: 3 miembros, revisión cruzada anónima y chairman (mediana + mayoría); por defecto con `ADES_JUDGE=council`. Test live
19. 🟡 **Regression detector** — detecta si un cambio de prompt/modelo empeora la calidad de salida. *(Fase 8)* → ✅ `evals/regression.py`: baseline frente a candidato con sign test + bootstrap. Test live

### F. Multi-modelo / enrutamiento
20. 🔴 **Brain Selector automático** — analiza la complejidad y elige modelo + reasoning effort (más fino que el router básico). *(Fase 3)* → ✅ `agents/router.py`: complejidad → modelo + reasoning effort + cascada, respetando el presupuesto. Tests
21. 🟡 **Fallback en cascada** — si un modelo falla, escala solo al siguiente (local → flash → pro). *(Fase 3)* → ✅ `core/llm_gateway.py`: cascada hasta local + timeout duro + circuit breaker. Tests; observado en vivo (503/504 de Gemini y 429 de OpenCode absorbidos)
22. 🟢 **A/B testing de modelos** — compara dos modelos en la misma tarea y reporta el ganador. *(Fase 8)* → ✅ `evals/ab_test.py`: win-rate, costo y latencia. Test live

### G. Seguridad y gobernanza
23. 🔴 **Secrets scanner continuo** — detecta keys expuestas antes del commit. *(Fase 0)* → ✅ (`environment/scan_secrets.py` + hook pre-commit)
24. 🟢 **Auditoría anti-IA** — revisa vulnerabilidades inyectadas por otras IAs (reporte §7.4). *(Fase 9)* → ✅ `evals/ai_audit.py`: reglas AST + bandit en el sandbox; integrada en el nodo Reviewer (verificado en runs reales). Test live
25. 🟢 **Modo "cuarentena"** — herramientas no verificadas solo corren aisladas hasta aprobación. *(Fase 5)* → ✅ `registry/quarantine.py`: sin aprobación explícita (`approve`) no se puede activar ni integrar. Tests

### H. Interfaz / UX
26. 🟡 **CLI unificado `ades`** — un solo comando para todo: `ades start`, `ades integrate X`, `ades status`, `ades tokens`. *(Transversal)* → ✅ `ades_cli.py` / `ades.bat`: start, status, tokens, run, bootstrap, backlog, budget, tools, memory, dashboard y más. Tests
27. 🟡 **Dashboard web de control** — panel para ver agentes, tokens, memoria y herramientas activas. *(Fase 8)* → ✅ `dashboard/app.py` (FastAPI): agentes, tokens, proyectos y backlog, registry, GPU y últimas llamadas. Verificado en navegador
28. 🟢 **Control por voz** — extiende los comandos de voz del registry a todo el ecosistema. *(Transversal)* → ⚠️ `automation/voice.py`: parser en lenguaje natural (reglas + llama3.2:3b) → comando `ades`, probado en vivo. **La entrada de audio no está probada** (faltan dependencias)

### I. Inferencia local
29. 🟡 **GPU Memory Manager** — carga/descarga modelos según demanda para no quedarte sin VRAM. *(Fase 1)* → ✅ `core/gpu_manager.py`: descarga los modelos grandes antes de cargar otro (regla de 16 GB). Tests; en el KPI 5 nunca hubo 2 modelos grandes a la vez
30. 🟢 **vLLM multi-model serving** — sirve varios modelos según el tráfico. *(Fase 9)* → ⚠️ `automation/model_serving.py` + `environment/vllm/`: ModelPool multi-backend probado en vivo contra Ollama; compose de vLLM generado. **vLLM nunca se ejecutó** (Windows + AMD)

### J. Automejora / recursividad
31. 🔴 **Auto-skill Generator** — genera una `SKILL.md` automáticamente de las tareas que repites (inspirado en ECC). *(Fase 4)* → ✅ `automation/skill_generator.py`: agrupa tareas repetidas → SKILL.md en staging → `publish`. Test live
32. 🟢 **Ecosistema automejorable** — los agentes proponen mejoras a sus propios prompts/skills y el sistema las evalúa antes de aplicarlas. *(Fase 9)* → ✅ `automation/self_improve.py`: propone un prompt, lo evalúa y solo lo aplica si mejora sin regresión (prompts versionados). Test live con evaluador inyectado; ver Fase 10
33. 🔴 **Agente Reclutador (meta-agente)** — crea, modifica y elimina agentes a pedido, eligiendo el LLM óptimo (nube vs local) y asignando skills, herramientas MCP y permisos. *(Fase 3)* → ✅ (`agents/reclutador.py`: crear, **modificar** (`update`) y eliminar; mapeo corregido)

---

## 7. Estructura de directorios objetivo

```
ADES-AI/
├── agents/                    # Fábrica LangGraph (Fase 3)
│   ├── orquestador.py         # Grafo completo (PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps)
│   ├── pm.py · arquitecto.py · developer.py · qa.py · reviewer.py
│   ├── reclutador.py          # Reclutador (meta-agente)
│   ├── router.py              # Router (Llama-3.2-3B selector)
│   ├── llm.py                 # Fábrica de LLMs (gemini / opencode / ollama)
│   ├── roster.py + roster.json # Registro de agentes
│   └── AGENTS.md
├── memory/                    # Memoria (Fase 2)
│   ├── indexer.py · schemas.py   # Tree-sitter → Neo4j
│   ├── graphiti_client.py        # Grafo temporal
│   ├── mem0_client.py            # Hechos personales
│   ├── cognee_client.py          # KG de documentos
│   ├── repomap.py                # RepoMap (Fase 7)
│   └── AGENTS.md
├── mcp_servers/               # MCP + gateway (Fase 6)
│   ├── mcp_config.json        # 7 servidores (stdio + SSE)
│   ├── client.py              # Cliente MCP (stdio + sse_client)
│   └── gateway/README.md      # Bifrost
├── cache/                     # Optimización de tokens (Fase 7)
│   ├── prompt_cache.py        # Prompt caching (estático primero)
│   ├── semantic_cache.py      # Redis + embeddings
│   ├── prompt_compressor.py   # LLMLingua-2
│   └── token_metrics.py       # hit-rate + costo
├── registry/                  # Tool Registry (Fase 5)
│   ├── catalog.json · state.json
│   ├── registry.py · integrator.py · cli.py
├── evals/                     # Evaluación (Fase 8)
│   ├── judge.py               # LLM-as-a-Judge
│   ├── rag_eval.py · tracing.py · dashboard.py
│   ├── promptfooconfig.yaml
│   └── cases/casos.json
├── environment/               # Scripts (Fases 0-9)
│   ├── setup_ollama.ps1 · setup_fase4.ps1 · setup_vllm.sh
│   ├── benchmark_local.py · scan_secrets.py · pre-commit
│   ├── setup_openhands.md · finetune_unsloth.py
│   └── AGENTS.md
├── .opencode/                 # Skills y subagentes (Fase 4)
│   ├── skills/ (indexar-repo, memoria, benchmark-local, fabrica)
│   └── agents/ (explore, librarian, oracle)
├── core/                      # Núcleo (v1.1): llm_gateway, sandbox, budget, gpu_manager,
│                              #   metrics_store, projects, config
├── automation/                # watchdog, prefetch, voice, model_serving, skill_generator, self_improve
├── dashboard/app.py           # Panel web en vivo (FastAPI)
├── kpis/                      # Mediciones de KPIs (tokens, loop, halluc, scale)
├── tests/                     # pytest (unitarios + `-m live`)
├── ades_cli.py · ades.bat     # CLI unificado `ades`
├── docs/
│   ├── plan_ecosistema_ia.md      # ESTE documento
│   └── catalogo_herramientas.md   # Descripción y URLs
├── docker-compose.yml         # Neo4j + Qdrant + Redis + Bifrost
├── docker-compose.langfuse.yml # Langfuse self-host
├── opencode.json              # plugins + skills
├── AGENTS.md · README.md · requirements.txt · .env
```

---

## 8. Criterios de éxito (KPIs)

- **Ahorro de tokens:** ≥ 70% medible en Langfuse tras Fase 7; ≥ 90% en flujos repetitivos cacheados
- **Costo local:** $0 por tareas de codificación iterativa
- **Ciclo Dev⇄QA:** corrección de errores en bucle cerrado sin intervención humana
- **Anti-alucinación:** agente no referencia clases inexistentes (validado contra Graphiti/Neo4j)
- **Escalabilidad:** fábrica sirve N agentes concurrentes vía vLLM + Bifrost sin saturar GPU

### Resultados medidos (v1.1, 11/11/2026)
Reproducibles con `python -m kpis.<script>`; los JSON quedan en `.ades/_global/kpis/`. Todas las llamadas son reales (Langfuse, Ollama, Docker, Neo4j, Gemini/OpenCode).

| KPI | Resultado | Estado |
|---|---|---|
| **1. Ahorro de tokens ≥70% (Langfuse)** | `kpi_tokens`: 6 tareas reales sobre el repo. Tokens leídos de Langfuse: base 100% del código de los paquetes en el prompt, modelo de nube y sin caché; ADES con RepoMap + snippets del grafo, router y caché. **Corrida final: −78.7% de tokens totales y −100% de tokens de pago y de costo**, con calidad del juez 10.0 frente a 9.83. Corrida anterior: −81.5% (9.67 frente a 9.5). | ✅ Cumplido |
| **1b. ≥90% en flujos repetitivos** | La misma carga repetida: 6/6 desde el caché semántico, **−100% de tokens**. Es repetición exacta; las paráfrasis solo aciertan si superan una similitud de 0.95. | ✅ Cumplido |
| **2. Costo local $0 en codificación iterativa** | `kpi_loop`: 3 requerimientos con la fábrica real (`ADES_SELF_HEAL_CLOUD=0`). **Developer + QA: $0.00 en todas las llamadas**. PM, Arquitecto, Reviewer y DevOps (no iterativos) costaron $0.0005-0.001 por run. | ✅ Cumplido |
| **3. Dev⇄QA en bucle cerrado sin humano** | `kpi_loop` final: **3/3 runs en estado ok con todos los tests en verde en el sandbox Docker** (14, 11 y 35 tests); 1 run se corrigió solo en la iteración 3. Antes de los arreglos de esta fase, 1 de 3 había fallado (test de QA mal escrito y mensajes de Pydantic v1). Muestra pequeña (3). | ✅ Cumplido |
| **4. Sin clases inexistentes (validado contra Neo4j)** | `kpi_halluc`: 8 tareas que obligan a usar APIs internas. **8/8 entregas finales sin referencias inexistentes**, verificado además de forma independiente importando los módulos reales y usando `hasattr`. Sin mapa del repo, el mismo modelo alucinó en 4/8 tareas. | ✅ Cumplido |
| **5. N agentes concurrentes vía vLLM + Bifrost sin saturar GPU** | `kpi_scale`: 12 agentes simultáneos (8 locales gpt-oss:20b + 4 de nube) **a través de Bifrost**: 12/12 correctos, VRAM máx. 12.75/16 GB, sin offload a CPU y nunca 2 modelos grandes a la vez. **Pero vLLM no puede ejecutarse en Windows + AMD RX 9070 XT**: la prueba usa Ollama como backend. | ❌ **No cumplido** tal como está redactado (falta vLLM; ver Fase 10) |

---

## 9. Cómo usar este archivo en futuras conversaciones

1. **Al iniciar una sesión nueva:** *"Lee `docs/plan_ecosistema_ia.md` y continuemos con la Fase X"*
2. **Retomar a medias:** *"Estoy en la Fase 2, quiero implementar el indexador Tree-sitter"*
3. **Actualizar progreso:** *"Marca como completadas las tareas terminadas y actualiza el diagnóstico"*
4. **Cambiar decisiones:** edita la tabla correspondiente (sección 3 o 4). Este archivo ES la fuente de verdad.
5. **Compartir contexto:** pásalo a Cline/Aider/OpenHands; al estar en el repo se beneficia del prompt caching.

### Frases de arranque recomendadas

- **Arrancar fase:** `Lee docs/plan_ecosistema_ia.md y ejecuta la Fase 1 completa.`
- **Continuar:** `Lee docs/plan_ecosistema_ia.md, dime en qué fase estoy y continúa con la siguiente tarea pendiente.`
- **Revisar estado:** `Lee docs/plan_ecosistema_ia.md y haz un diagnóstico del avance real vs roadmap.`

---

## 10. Fuentes clave de la investigación (para verificación futura)

- **Agentes de código:** OpenCode (`anomalyco/opencode`), Cline, Aider, RooCode, Qwen Code, Kilo Code; Claude Code/Codex (propietarios)
- **Skills:** Obra `obra/superpowers` (247k ⭐), `oh-my-opencode`, estándar `SKILL.md` + `AGENTS.md`
- **Memoria:** `getzep/graphiti`, `mem0ai/mem0`, `topoteretes/cognee`, `HKUDS/LightRAG`, `microsoft/graphrag`
- **Token optimization:** `pleasedodisturb/awesome-llm-token-optimization`, `microsoft/LLMLingua`, `zilliztech/GPTCache`, SuperCompress
- **Orquestación:** LangGraph, CrewAI, OpenAI Agents SDK, MetaGPT (`FoundationAgents/MetaGPT`), ChatDev 2.0
- **Inferencia local:** Ollama, vLLM, llama.cpp, gpt-oss:20b, Qwen3.8, Gemma 4
- **MCP:** `modelcontextprotocol/servers`, Bifrost (Maxim AI), Firecrawl MCP, cognee-mcp
- **Eval:** Langfuse, DeepEval, Ragas, Promptfoo, Braintrust, MLflow

---

## 11. Catálogo de herramientas externas

Todas las herramientas, frameworks, modelos y servicios mencionados en este plan están descritos (con descripción sencilla y enlace oficial verificado) en el documento complementario:

📄 **`docs/catalogo_herramientas.md`**

Consúltalo cada vez que necesites la URL o una explicación rápida de una herramienta durante la implementación de una fase.

---

*Fin del plan. Mantén este documento actualizado como registro vivo del ecosistema.*
