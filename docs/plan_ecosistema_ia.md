# PLAN DE TRABAJO: Ecosistema Completo de IA para Programación (ADE-AI v2.0)

> **Estado:** Plan actualizado tras investigación exhaustiva · **Fecha:** 4 de Noviembre de 2026
> **Proyecto:** ADE-AI (Autonomous Development Ecosystem with Artificial Intelligence)
> **Este documento es la fuente de verdad del proyecto.** Léelo al inicio de cualquier sesión para retomar el contexto sin repetirlo.

---

## 0. Contexto y recursos disponibles

**Recursos del desarrollador:**
- 🟢 **Gemini Plus** (Google) → razonamiento y arquitectura en nube (modelos 2026: serie Gemini 4 / Flash)
- 🟢 **OpenCode Go** → endpoint OpenAI-compatible con modelos DeepSeek V4 (`deepseek-v4.1-flash`, `deepseek-v4-pro`)
- 🟢 **GPU 16GB VRAM** → LLMs locales (sweet spot 2026: modelos ~20-27B cuantizados, o MoE con offload)

**Estado actual del proyecto (diagnóstico):**

| Componente | Estado | Detalle |
|---|---|---|
| `docker-compose.yml` | ✅ Listo | Neo4j (GraphRAG) + Qdrant (vectorial) |
| `agents/orquestador.py` | ⚠️ Parcial | LangGraph con 1 solo nodo (PM). Modelos desactualizados (`gemini-1.5-flash`) |
| `.env` / `.env.example` | ⚠️ Keys expuestas | Hay que rotarlas (están en el repo) |
| `requirements.txt` | ✅ Listo | LangChain + LangGraph + clientes |
| `mcp_servers/`, `memory/`, `environment/`, `skills/` | ❌ Vacías | Pendientes |
| Ollama/vLLM local, agentes reales, skills, evals | ❌ No existe | Falta todo |

**Punto clave:** existe el esqueleto (memoria + 1 agente PM), pero el ecosistema real —cerebro local, fábrica multiagente, capa de skills, MCP, memoria de largo plazo, evaluación y la estrategia de ahorro del 90%— está por construir.

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

> Ya implementaste el `x-opencode-session` para cacheo ✅. Falta: reordenar prompts (estático primero) y actualizar nombres de modelo (`gemini-1.5-flash` → serie Gemini 2026).

### 3.3 Capa de Memoria (anti-alucinaciones) — MEJORADA

La investigación revela que el RAG vectorial puro quedó atrás; 2026 combina **grafo temporal + hechos + documentos**:

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Grafo de código (temporal)** | **Graphiti (Zep)** sobre Neo4j | LightRAG | ❌ Falta — imprescindible |
| **Grafo/vectorial base** | **Neo4j 5.23** | Memgraph | ✅ Ya en Docker |
| **Vectorial (semántica)** | **Qdrant** | Pinecone / Chroma | ✅ Ya en Docker |
| **Hechos personales (largo plazo)** | **Mem0** | Zep / Letta | ❌ Falta |
| **KG de documentos + MCP** | **Cognee** (Apache 2.0) | Microsoft GraphRAG | ❌ Falta |
| **Indexador código → grafo** | **Tree-sitter** → Graphiti/Neo4j | Aider RepoMap | ❌ Falta |

**Por qué esta combinación:**
- **Graphiti** (Apache 2.0, sobre Neo4j): construye el grafo de tu código de forma **incremental y temporal** — sabe qué clases existen, sus relaciones, y cuándo cambiaron. Anti-alucinación estructural real.
- **Mem0**: extrae "hechos" del usuario (preferencias, decisiones) con la mejor precisión en LongMemEval (93.4%).
- **Cognee**: convierte docs/repos en grafo de conocimiento, y trae **servidor MCP** (`cognee-mcp`) + integraciones con Claude Code/Cursor/LangGraph/Neo4j.
- **Qdrant**: búsqueda vectorial rápida como complemento.

### 3.4 Capa de Orquestación

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Motor de grafos (fábrica)** | **LangGraph** | CrewAI / OpenAI Agents SDK / MetaGPT | ⚠️ Solo 1 nodo |
| **Orquestación multiagente OpenCode** | **oh-my-opencode** | Obra Superpowers | ❌ Falta |

LangGraph gana por **ciclos** (Dev ⇄ QA hasta pasar), checkpoints, recuperación y human-in-the-loop. `oh-my-opencode` orquesta flotas de agentes (Sisyphus, Oracle, Librarian, Explore, Atlas, Prometheus, Metis, Momus) con modo "ultrawork" y enrutamiento por categoría.

### 3.5 Capa de Agentes (la "Software Factory" + enjambre)

**Fábrica principal (LangGraph):**
1. **PM** → Gemini. Requerimiento → PRD + tickets. *(✅ parcial, existe)*
2. **Arquitecto** → Gemini. PRD → estructura, stack, RepoMap inicial.
3. **Developer** (varias instancias) → gpt-oss:20b/Qwen3.8 local. Escribe código por ticket.
4. **QA/Tester** → sandbox Docker + LAM. Lee errores, devuelve feedback. *Bucle cerrado con Developer.*
5. **Code Reviewer** → deepseek-v4-pro. Revisa diffs (seguridad, calidad).
6. **DevOps** → empaqueta, Dockerfile/CI, despliega.

**Enjambre de subagentes (OpenCode + oh-my-opencode):** cada tarea de la fábrica se delega a subagentes con contexto acotado (Explore para investigar código, Librarian para memoria, Oracle para planificar), evitando contaminar el contexto principal.

### 3.6 Capa de Skills (NUEVA — la gran novedad 2026)

Las **Skills** (archivos `SKILL.md`) son capacidades reutilizables que se cargan **solo bajo demanda**, con *progressive disclosure*: el agente lee por etapas en vez de tragarse todo. Esto es ahorro de tokens estructural, no cosmético.

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Instrucciones permanentes** | **AGENTS.md** (estándar cross-tool) | CLAUDE.md | ❌ Crear |
| **Framework de skills** | **Obra Superpowers** (247k ⭐) | Superpowers | ❌ Instalar |
| **Skills propias** | `.opencode/skills/` | `.claude/skills/` | ❌ Crear |

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

---

## 5. Roadmap por fases (reestructurado)

### FASE 0 — Cimientos y seguridad (estado: 40%)
- [x] Docker (Neo4j + Qdrant)
- [x] LangGraph con nodo PM
- [ ] **Rotar keys expuestas** en `.env` (GEMINI + OPENCODE) — urgente
- [ ] Corregir `docker-compose.yml` (eliminar `version:` deprecada; añadir Redis)
- [ ] Crear `AGENTS.md` raíz (corto, permanente)

### FASE 1 — Cerebro local (GPU)
- [ ] Instalar **Ollama** + bajar gpt-oss:20b, Qwen3.8 27B (IQ3_S), Llama-3.2-3B, nomic-embed-text
- [ ] Script `environment/setup_ollama.ps1`
- [ ] Probar coding a <30 tok/s; benchmark gpt-oss:20b vs Qwen3.8
- [ ] (Opcional, Fase 6+) instalar **vLLM** para servir el modelo a muchos agentes

### FASE 2 — Memoria completa (el pilar anti-alucinación)
- [ ] Levantar **Graphiti** (sobre Neo4j existente)
- [ ] Integrar **Mem0** (hechos personales/preferencias)
- [ ] Levantar **Cognee** + `cognee-mcp` (KG de documentos)
- [ ] Implementar **indexador Tree-sitter → Graphiti/Neo4j** (`memory/indexer.py`)
- [ ] Script para (re)indexar un repo bajo demanda

### FASE 3 — Fábrica multiagente (LangGraph)
- [ ] Refactorizar `orquestador.py` → grafo completo (PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps)
- [ ] **Router** (Llama-3.2-3B) para elegir modelo por tarea
- [ ] Bucle cerrado Dev⇄QA con checkpoint
- [ ] Actualizar nombres de modelo en código (Gemini 2026, deepseek-v4)

### FASE 4 — Skills y subagentes (OpenCode)
- [ ] Instalar **Obra Superpowers** + **oh-my-opencode**
- [ ] Crear skills propias en `.opencode/skills/`
- [ ] Configurar subagentes (Explore, Librarian, Oracle) con contexto acotado
- [ ] Definir `AGENTS.md` anidados por carpeta (convenciones locales)

### FASE 5 — MCP + gateway
- [ ] Crear `mcp_servers/mcp_config.json`
- [ ] Levantar MCP: filesystem, git, GitHub, memory, sequential-thinking, Firecrawl, cognee-mcp
- [ ] Instalar **Bifrost** como gateway (auth + scope)
- [ ] Conectar orquestador a MCP (Developer lee/escribe archivos reales)

### FASE 6 — Optimización de tokens (objetivo 90%)
- [ ] **Prompt caching**: reordenar contexto (estático primero) en Gemini y OpenCode
- [ ] **Semantic caching**: Redis + GPTCache para respuestas repetidas
- [ ] **RepoMaps** en uso real (medir ahorro en Langfuse)
- [ ] **LLMLingua-2 / SuperCompress** para compresión de RAG y prompts
- [ ] **Model routing** fino: medir hit-rate del caché y costo/tarea

### FASE 7 — Evaluación y observabilidad
- [ ] Levantar **Langfuse** (+ Redis/ClickHouse en docker-compose)
- [ ] Suite **LLM-as-a-Judge** para cada agente
- [ ] **Ragas/DeepEval** para calidad de RAG
- [ ] **Promptfoo** para red-team/seguridad
- [ ] Dashboard de costo en tokens por agente

### FASE 8 — Escalado, autonomía y fine-tuning
- [ ] Migrar local a **vLLM** si la fábrica exige concurrencia
- [ ] Workflow **OpenHands**: issue de GitHub → PR automático
- [ ] Fine-tuning de un SLM (Qwen 3B/8B) con tus patrones vía **Unsloth**
- [ ] (Opcional) Agentes en entorno simulado (Godot/Phaser) del reporte §6

---

## 6. Estructura de directorios objetivo

```
ADE-AI/
├── agents/                    # Fábrica LangGraph
│   ├── orquestador.py         # Grafo completo (PM → ... → DevOps)
│   ├── pm.py                  # Project Manager (Gemini)
│   ├── arquitecto.py          # Architect (Gemini)
│   ├── developer.py           # Developer (gpt-oss:20b / Qwen3.8 local)
│   ├── qa.py                  # QA sandbox (local + LAM)
│   ├── reviewer.py            # Code Reviewer (DeepSeek V4)
│   └── router.py              # Llama-3.2-3B selector
├── memory/
│   ├── indexer.py             # Tree-sitter → Graphiti/Neo4j
│   ├── graphiti_client.py     # Grafo temporal
│   ├── mem0_client.py         # Hechos personales
│   └── schemas.py
├── mcp_servers/
│   ├── mcp_config.json        # Config MCP (OpenCode + Cline + LangGraph)
│   └── gateway/               # Bifrost (auth + scope)
├── skills/
│   ├── AGENTS.md              # Instrucciones permanentes (raíz)
│   └── .opencode/skills/      # Skills propias (SKILL.md)
├── environment/
│   ├── setup_ollama.ps1
│   └── setup_vllm.sh
├── evals/
│   ├── judge.py               # LLM-as-a-Judge
│   └── cases/
├── cache/
│   └── semantic_cache.py      # Redis + GPTCache
├── docs/
│   └── plan_ecosistema_ia.md  # ESTE documento
├── docker-compose.yml         # + Redis, + Graphiti, + Mem0, + Langfuse
└── .env
```

---

## 7. Criterios de éxito (KPIs)

- **Ahorro de tokens:** ≥ 70% medible en Langfuse tras Fase 6; ≥ 90% en flujos repetitivos cacheados
- **Costo local:** $0 por tareas de codificación iterativa
- **Ciclo Dev⇄QA:** corrección de errores en bucle cerrado sin intervención humana
- **Anti-alucinación:** agente no referencia clases inexistentes (validado contra Graphiti/Neo4j)
- **Escalabilidad:** fábrica sirve N agentes concurrentes vía vLLM + Bifrost sin saturar GPU

---

## 8. Cómo usar este archivo en futuras conversaciones

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

## 9. Fuentes clave de la investigación (para verificación futura)

- **Agentes de código:** OpenCode (`sst/opencode`), Cline, Aider, RooCode, Qwen Code, Kilo Code; Claude Code/Codex (propietarios)
- **Skills:** Obra `obra/superpowers` (247k ⭐), `oh-my-opencode`, estándar `SKILL.md` + `AGENTS.md`
- **Memoria:** `getzep/graphiti`, `mem0ai/mem0`, `topoteretes/cognee`, `HKUDS/LightRAG`, `microsoft/graphrag`
- **Token optimization:** `pleasedodisturb/awesome-llm-token-optimization`, `microsoft/LLMLingua`, `zilliztech/GPTCache`, SuperCompress
- **Orquestación:** LangGraph, CrewAI, OpenAI Agents SDK, MetaGPT (`FoundationAgents/MetaGPT`), ChatDev 2.0
- **Inferencia local:** Ollama, vLLM, llama.cpp, gpt-oss:20b, Qwen3.8, Gemma 4
- **MCP:** `modelcontextprotocol/servers`, Bifrost (Maxim AI), Firecrawl MCP, cognee-mcp
- **Eval:** Langfuse, DeepEval, Ragas, Promptfoo, Braintrust, MLflow

*Fin del plan. Mantén este documento actualizado como registro vivo del ecosistema.*
