# PLAN DE TRABAJO: Ecosistema Completo de IA para Programación (ADE-AI v2.0)

> **Estado:** Pendiente de ejecución · **Fecha:** 4 de Noviembre de 2026
> **Proyecto:** ADE-AI (Autonomous Development Ecosystem with Artificial Intelligence)
> **Este documento es la fuente de verdad del proyecto.** Léelo al inicio de cualquier sesión de trabajo para retomar el contexto sin repetirlo.

---

## 0. Contexto y recursos disponibles

**Recursos del desarrollador:**
- 🟢 **Gemini Plus** (Google) → razonamiento y arquitectura en nube
- 🟢 **OpenCode Go** → endpoint OpenAI-compatible con modelos DeepSeek (`deepseek-v4.1-flash` y `deepseek-v4-pro`)
- 🟢 **GPU 16GB VRAM** → LLMs locales (sweet spot: modelos ~14B cuantizados, o 32B con offload parcial)

**Estado actual del proyecto (diagnóstico):**

| Componente | Estado | Detalle |
|---|---|---|
| `docker-compose.yml` | ✅ Listo | Neo4j (GraphRAG) + Qdrant (vectorial) |
| `agents/orquestador.py` | ⚠️ Parcial | LangGraph con 1 solo nodo (PM). Elige Gemini o OpenCode Go |
| `.env` / `.env.example` | ✅ Listo | Keys + conexiones de memoria |
| `requirements.txt` | ✅ Listo | LangChain + LangGraph + clientes |
| `mcp_servers/`, `memory/`, `environment/` | ❌ Vacías | Pendientes |
| Ollama local, Developer/QA agents, evals, UI | ❌ No existe | Falta todo |

**Punto clave:** existe el esqueleto (bases de memoria + un PM), pero faltan el **cerebro local (Ollama)**, los **agentes reales**, la **capa MCP**, la **memoria a largo plazo** y la **evaluación**.

---

## 1. Visión y arquitectura objetivo

Un ecosistema **híbrido de 3 cerebros** que asigna cada tarea al modelo óptimo según costo/latencia/capacidad:

```
🧠 CEREBRO 1 — NUBE (razonamiento pesado)
   Gemini 2.5 Pro → Arquitectura, planificación, System 2
   OpenCode Go (DeepSeek) → Código complejo, refactors grandes
        ↓  (baja latencia, alto costo)
🧠 CEREBRO 2 — LOCAL (GPU 16GB, costo $0)
   Qwen2.5-Coder-14B → codificación iterativa, autocompletado
   DeepSeek-R1-Distill-14B → razonamiento local
   Llama-3.2-3B → router/clasificador rápido
        ↓
🧠 CEREBRO 3 — MEMORIA (contexto infinito sin quemar tokens)
   Neo4j (grafo) + Qdrant (vectorial) + Mem0 (hechos personales)
```

Todo orquestado por **LangGraph**, expuesto vía **MCP**, y gobernado por **evaluación automatizada**.

---

## 2. Capas del ecosistema (recomendado + alternativas)

### 2.1 Capa de Inferencia Local (GPU 16GB)

| Rol | ⭐ Recomendado | Alternativa | Notas |
|---|---|---|---|
| **Runtime** | **Ollama** | LM Studio / llama.cpp / vLLM | Ollama = mejor soporte GPU en Windows, API compatible, fácil |
| **Código (local)** | **Qwen2.5-Coder-14B-Instruct** (Q5_K_M ≈ 10GB) | Qwen3-14B / DeepSeek-Coder-V2-Lite | El mejor coding model que cabe en 16GB |
| **General/chat** | **Qwen3-14B** | Llama-3.1-8B / Mistral | Conversación y tareas mixtas |
| **Razonamiento local** | **DeepSeek-R1-Distill-Qwen-14B** (Q4_K_M) | QwQ-32B (con offload parcial) | Para System 2 sin costo |
| **Router/compresor** | **Llama-3.2-3B** | Qwen2.5-3B | Clasifica tareas, comprime contexto |
| **Embeddings** | **nomic-embed-text** (local) | bge-m3 / Gemini text-embedding-004 | Para Qdrant y GraphRAG |

> **Regla de oro 16GB:** NUNCA cargues dos modelos 14B a la vez. Carga uno pesado (14B) + uno ligero (3B) residentes. Con `ollama` mantienes los demás en disco y se cargan bajo demanda (~10s de swap).

### 2.2 Capa Cloud

| Rol | ⭐ Recomendado | Alternativa | Cuándo usarlo |
|---|---|---|---|
| **Arquitectura/PM** | **Gemini 2.5 Pro** | Gemini 2.5 Flash (más barato) | PRDs, diseño de sistemas, decisiones difíciles |
| **Código nube** | **OpenCode Go (DeepSeek)** | Gemini Flash | Refactors grandes, debugging profundo |
| **Prompt caching** | **Gemini nativo + OpenCode session header** | — | Contexto estático al inicio = -90% costo |

> Ya está implementado el `x-opencode-session` para cacheo en `orquestador.py` ✅. Falta explotarlo en Gemini agrupando contexto estático primero.

### 2.3 Capa de Memoria (anti-alucinaciones)

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Grafo (estructura)** | **Neo4j 5.23** | Memgraph | ✅ Ya en Docker |
| **Vectorial (semántica)** | **Qdrant** | Pinecone / Chroma | ✅ Ya en Docker |
| **Memoria largo plazo (hechos)** | **Mem0** | Zep | ❌ Falta — imprescindible |
| **Indexador de código → grafo** | **Tree-sitter** (parser) | Aider RepoMap | ❌ Falta |

**Qué construye el indexador:** escanea tu repo → extrae clases/métodos/relaciones con Tree-sitter → los escribe como nodos en Neo4j (`PaymentProcessor IMPLEMENTS IPayable`). Así el LLM consulta el grafo en vez de tragarse 100k tokens.

### 2.4 Capa de Orquestación

| Rol | ⭐ Recomendado | Alternativa | Estado |
|---|---|---|---|
| **Motor de grafos** | **LangGraph** | CrewAI / OpenAI Agents SDK / AutoGen | ⚠️ Solo 1 nodo |

LangGraph gana porque soporta **ciclos** (Dev ⇄ QA hasta pasar), checkpoints y recuperación. CrewAI es más fácil para roles empresariales; AutoGen para conversaciones multiagente.

### 2.5 Capa de Agentes (la "Software Factory")

Agentes a construir (todos sobre LangGraph, cada uno con su modelo):

1. **Agente PM** → Gemini 2.5 Pro. Requerimiento → PRD + tickets. *(✅ parcial, ya existe)*
2. **Agente Arquitecto** → Gemini 2.5 Pro. PRD → estructura de carpetas, stack, RepoMap inicial.
3. **Agente Developer** (varias instancias) → Qwen2.5-Coder-14B local. Escribe código por ticket.
4. **Agente QA/Tester** → ejecuta en sandbox Docker, lee errores, devuelve feedback. *Bucle cerrado con Developer.*
5. **Agente Code Reviewer** → OpenCode Go/DeepSeek. Revisa diffs por seguridad y calidad.
6. **Agente DevOps** → empaqueta, escribe Dockerfile/CI, despliega.

### 2.6 Capa MCP (herramientas del agente)

El estándar 2026. Servidores a integrar (⭐ = prioritarios):

- ⭐ `filesystem` (leer/escribir archivos)
- ⭐ `git` (commits, branches, diffs)
- ⭐ `GitHub` (issues, PRs)
- ⭐ `memory` (Qdrant/Neo4j como MCP server)
- ⭐ `sequential-thinking` (razonamiento paso a paso)
- `fetch` (documentación web)
- `playwright`/`browser` (para el agente QA tipo LAM)
- `postgres`/`database` (si el proyecto lo requiere)
- `docker` (gestión de sandbox)

> Configurables en un `mcp_servers/mcp_config.json` consumible tanto por tu código como por Cline.

### 2.7 Capa de IDE/Interfaz

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Editor agentico** | **Cline (VS Code)** | Cursor / Windsurf (pago) |
| **Terminal** | **Aider** | — |
| **Autónomo** | **OpenHands** | — |

Cline es el estándar open-source y habla MCP nativamente. Conecta tu stack local (Ollama) y tu nube (Gemini/OpenCode) al mismo editor.

### 2.8 Capa de Evaluación y Observabilidad

| Rol | ⭐ Recomendado | Alternativa |
|---|---|---|
| **Trazabilidad** | **Langfuse** (open source, self-host) | LangSmith (pago) |
| **Eval-Driven Dev** | **LLM-as-a-Judge** (tests de prompts) | RAGAS / DeepEval |

Registra cada llamada, costo en tokens, latencia y calidad de respuesta. Sin esto, optimizar tokens es adivinar.

### 2.9 Capa de Optimización de Tokens (el ahorro 70-80%)

| Técnica | ⭐ Recomendado | Implementación |
|---|---|---|
| **Prompt caching** | Gemini + OpenCode session | Contexto estático primero, dinámico al final |
| **RepoMaps** | Tree-sitter → Neo4j | El LLM ve esqueleto (3k tokens), no código (100k) |
| **Compresión** | **LLMLingua-2** (local, corre en tu GPU) | Comprime prompts/RAG -50% preservando 95% |
| **Router** | Llama-3.2-3B | Tareas triviales → local, complejas → nube |

### 2.10 Capa de Seguridad y Despliegue

| Rol | ⭐ Recomendado | Notas |
|---|---|---|
| **Sandbox** | Docker (contenedor efímero por agente) | El QA NUNCA ejecuta código fuera de contenedor |
| **Secretos** | `.env` + `python-dotenv` (ya ✅) | Nunca hardcodear keys |
| **Config global** | `.cursorrules` / `CLAUDE.md` / AGENTS.md | Define reglas del proyecto, se cachea |

---

## 3. Stack recomendado — resumen ejecutivo

| Capa | ⭐ Decisión final |
|---|---|
| Runtime local | **Ollama** |
| Coding local | **Qwen2.5-Coder-14B** (Q5) |
| Razonamiento local | **DeepSeek-R1-Distill-14B** |
| Router/compresor | **Llama-3.2-3B** + **LLMLingua-2** |
| Embeddings | **nomic-embed-text** |
| Nube arquitectura | **Gemini 2.5 Pro** |
| Nube código | **OpenCode Go (DeepSeek)** |
| Grafo | **Neo4j** ✅ |
| Vectorial | **Qdrant** ✅ |
| Largo plazo | **Mem0** |
| Orquestación | **LangGraph** |
| Indexador | **Tree-sitter → Neo4j** |
| MCP | filesystem, git, GitHub, memory, sequential-thinking |
| Editor | **Cline (VS Code)** + Aider |
| Observabilidad | **Langfuse** |
| Evaluación | LLM-as-a-Judge |

---

## 4. Roadmap por fases (con tareas concretas)

### FASE 0 — Cimientos (estado: 60% ✅)
- [x] Docker (Neo4j + Qdrant)
- [x] LangGraph con nodo PM
- [ ] Corregir `docker-compose.yml` (versión `3.8` está deprecada → eliminar `version:`)
- [ ] Migrar `.env` hardcodeado a secretos seguros (rotar keys expuestas en el repo)

### FASE 1 — Cerebro local (GPU)
- [ ] Instalar **Ollama** y bajar los 5 modelos de la tabla 2.1
- [ ] Script `environment/setup_ollama.ps1` que descargue todos con un comando
- [ ] Probar: Qwen2.5-Coder-14B responde código en <2s/token

### FASE 2 — Memoria completa
- [ ] Implementar **indexador Tree-sitter → Neo4j** (`memory/indexer.py`)
- [ ] Integrar **Mem0** para hechos personales/preferencias
- [ ] Script para (re)indexar un repo bajo demanda

### FASE 3 — Orquestación multiagente
- [ ] Refactorizar `orquestador.py` → grafo completo (PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps)
- [ ] Añadir **router** (Llama-3.2-3B) para elegir modelo por tarea
- [ ] Bucle cerrado Dev⇄QA con checkpoint (LangGraph)

### FASE 4 — MCP
- [ ] Crear `mcp_servers/mcp_config.json`
- [ ] Levantar servidores MCP: filesystem, git, GitHub, memory, sequential-thinking
- [ ] Conectar el orquestador a MCP (que Developer lea/escriba archivos reales)

### FASE 5 — Interfaz
- [ ] Instalar **Cline** en VS Code, apuntarlo a Ollama + Gemini + OpenCode
- [ ] Configurar **Aider** para terminal
- [ ] Crear `.cursorrules`/`AGENTS.md` global

### FASE 6 — Evaluación y observabilidad
- [ ] Levantar **Langfuse** (añadir al docker-compose)
- [ ] Suite de tests LLM-as-a-Judge para cada agente
- [ ] Dashboard de costo en tokens por agente

### FASE 7 — Optimización de tokens
- [ ] Prompt caching en Gemini (reordenar contexto)
- [ ] RepoMaps en uso real (medir ahorro)
- [ ] LLMLingua-2 para compresión de RAG

### FASE 8 — Autonomía total y fine-tuning
- [ ] Workflow OpenHands para issues de GitHub → PR automático
- [ ] Fine-tuning de un SLM (Qwen-3B/8B) con tus patrones de código vía **Unsloth**
- [ ] (Opcional) Agentes en entorno simulado (Godot/Phaser) del reporte §6

---

## 5. Estructura de directorios objetivo

```
ADE-AI/
├── agents/
│   ├── orquestador.py        # Grafo LangGraph (PM → ... → DevOps)
│   ├── pm.py                 # Project Manager (Gemini)
│   ├── arquitecto.py         # Architect (Gemini)
│   ├── developer.py          # Developer (Qwen local)
│   ├── qa.py                 # QA sandbox (local + LAM)
│   └── router.py             # Llama-3.2-3B selector
├── memory/
│   ├── indexer.py            # Tree-sitter → Neo4j
│   ├── mem0_client.py        # Memoria largo plazo
│   └── schemas.py
├── mcp_servers/
│   └── mcp_config.json
├── environment/
│   ├── setup_ollama.ps1
│   └── setup_ollama.sh
├── evals/
│   ├── judge.py              # LLM-as-a-Judge
│   └── cases/
├── docs/
│   └── plan_ecosistema_ia.md  # ESTE documento
├── docker-compose.yml        # + Langfuse, + Mem0
├── .cursorrules
├── AGENTS.md
└── .env
```

---

## 6. Criterios de éxito (KPIs)

- **Ahorro de tokens:** ≥ 60% medible en Langfuse tras Fase 7
- **Costo local:** $0 por tareas de codificación iterativa
- **Ciclo Dev⇄QA:** corrección de errores en bucle cerrado sin intervención humana
- **Anti-alucinación:** agente no referencia clases inexistentes (validado contra Neo4j)

---

## 7. Cómo usar este archivo en futuras conversaciones

Este documento está diseñado para ser **tu "norte" persistente**. Úsalo así:

1. **Al iniciar una sesión nueva**, di algo como:
   > "Lee `docs/plan_ecosistema_ia.md` y continuemos con la Fase X"

   El agente leerá el plan completo y sabrá exactamente dónde estás, sin que repitas contexto.

2. **Para retomar una fase a medias**, indica la fase y qué tarea:
   > "Estoy en la Fase 2, quiero implementar el indexador Tree-sitter de `memory/indexer.py`"

3. **Para actualizar el progreso**, pide al agente marcar tareas hechas:
   > "Marca como completadas las tareas que terminamos y actualiza la sección de diagnóstico"

4. **Para cambiar decisiones**, edita directamente la tabla correspondiente (sección 2 o 3). Este archivo ES la fuente de verdad: si cambias una herramienta recomendada, cámbiala aquí primero.

5. **Para compartir contexto con herramientas** (Cline, Aider, otro agente), pásales este archivo. Al estar en el repo, se beneficia del prompt caching mencionado en el reporte.

### Frases de arranque recomendadas (copiar y pegar)

- **Arrancar fase nueva:** `Lee docs/plan_ecosistema_ia.md y ejecuta la Fase 1 completa.`
- **Continuar donde quedé:** `Lee docs/plan_ecosistema_ia.md, dime en qué fase estoy según el repo y continúa con la siguiente tarea pendiente.`
- **Revisar estado:** `Lee docs/plan_ecosistema_ia.md y haz un diagnóstico del avance real del proyecto comparado con el roadmap.`

---

*Fin del plan. Mantén este documento actualizado como registro vivo del ecosistema.*
