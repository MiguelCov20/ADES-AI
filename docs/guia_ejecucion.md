# Guía de ejecución — ADES-AI v1.0

Guía paso a paso para levantar y usar el ecosistema completo. Complementa a
`docs/plan_ecosistema_ia.md` (el plan/fuente de verdad) y a `AGENTS.md` (reglas).

---

## 1. Requisitos previos

| Herramienta | Para qué | Verificación |
|---|---|---|
| **Python 3.11** | backend LangGraph, memoria, registry | `python --version` |
| **Docker Desktop** | Neo4j, Qdrant, Redis, Bifrost, cognee-mcp | `docker info` |
| **Node.js + npx** | servidores MCP (filesystem, github, etc.) | `node --version` |
| **Ollama** | modelos locales (GPU) | `ollama --version` |
| **Git** | clonar skills externas | `git --version` |

> La GPU real es una **AMD Radeon RX 9070 XT (16 GB)**; Ollama la usa vía ROCm.

---

## 2. Instalación

### 2.1 Dependencias de Python

```powershell
pip install -r requirements.txt
```

### 2.2 Variables de entorno (`.env`)

Copia `.env.example` a `.env` y completa:

```ini
GOOGLE_API_KEY=...          # clave de Gemini
OPENCODE_API_KEY=...        # clave de OpenCode Go
GEMINI_MODEL=gemini-flash-latest   # opcional (ver troubleshooting)
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
QDRANT_URL=http://localhost:6333
```

> `.env` está en `.gitignore`; nunca lo versiones.

### 2.3 Infraestructura (Docker)

```powershell
docker compose up -d
```

Levanta:
- **Neo4j** (grafo + APOC) → `http://localhost:7474`
- **Qdrant** (vectorial) → `http://localhost:6333`
- **Redis** (caché) → `:6379`
- **Bifrost** (gateway) → `http://localhost:8080`

(Opcional, observabilidad) `docker compose -f docker-compose.langfuse.yml up -d`.

### 2.4 Modelos locales (Ollama)

```powershell
powershell -ExecutionPolicy Bypass -File environment/setup_ollama.ps1
```

Descarga: `gpt-oss:20b`, `qwen3.8:27b-iq3` (importa GGUF local), `llama3.2:3b`,
`nomic-embed-text`.

### 2.5 Skills externas (opcional)

```powershell
powershell -ExecutionPolicy Bypass -File environment/setup_fase4.ps1
```

Clona Obra Superpowers + oh-my-opencode a `.opencode/vendor/` (gitignored).

---

## 3. Cómo usar cada componente

### 3.1 Fábrica multiagente (LangGraph)

```powershell
python -m agents.orquestador "Un endpoint /ping en FastAPI" --max-iter 3
```

Flujo: PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps.
El Reclutador gestiona agentes: `python -m agents.reclutador list|create|delete`.

### 3.2 Indexador de código y RepoMap

```powershell
python -m memory.indexer --repo . --summary   # indexa el repo en Neo4j
python -m memory.repomap --repo .             # esqueleto condensado (RepoMap)
```

### 3.3 Memoria (Graphiti / Mem0 / Cognee)

```powershell
python -m memory.graphiti_client add "texto"      # grafo temporal
python -m memory.graphiti_client search "consulta"
python -m memory.mem0_client add "texto" --user miguel
python -m memory.mem0_client search "consulta" --user miguel
python -m memory.cognee_client add "texto o archivo"  # requiere APOC en Neo4j
python -m memory.cognee_client cognify
python -m memory.cognee_client search "consulta"
```

### 3.4 Tool Registry

```powershell
python -m registry.cli list
python -m registry.cli search "llm"
python -m registry.cli add "https://github.com/..." --tipo tool
python -m registry.cli integrate <id> --dry-run
python -m registry.cli activate <id>
```

### 3.5 MCP

```powershell
python -m mcp_servers.client            # lista servidores configurados
# servidores stdio (filesystem, git, github, ...) se conectan bajo demanda.

# cognee-mcp (SSE) — arranca el contenedor una vez:
docker run -d --name cognee-mcp -p 8001:8000 -e TRANSPORT_MODE=sse cognee/cognee-mcp:main
```

### 3.6 Evaluación y observabilidad

```powershell
python -m evals.judge                   # ejemplo LLM-as-a-Judge
python -m evals.dashboard               # dashboard de costo (ejemplo)
npx promptfoo eval -c evals/promptfooconfig.yaml   # red-team
```

---

## 4. Referencia rápida

| Qué | Comando |
|---|---|
| Levantar infraestructura | `docker compose up -d` |
| Fábrica | `python -m agents.orquestador "..."` |
| Indexar repo | `python -m memory.indexer --repo . --summary` |
| RepoMap | `python -m memory.repomap --repo .` |
| Tool Registry | `python -m registry.cli list` |
| Servidores MCP | `python -m mcp_servers.client` |
| Benchmark local | `python environment/benchmark_local.py` |
| Escanear secretos | `python environment/scan_secrets.py` |
| Skills externas | `environment/setup_fase4.ps1` |

---

## 5. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| Gemini 503/429 | sobrecarga/cuota de Google (transitorio) | `GEMINI_MODEL=gemini-flash-lite-latest` en `.env` |
| Modelo local lento (offload CPU) | ventana de contexto completa (128K) | `OLLAMA_NUM_CTX=8192` (ya por defecto en `agents/llm.py`) |
| Cognee falla al cognify | falta el plugin APOC | `docker compose up -d --force-recreate graph_memory` (APOC ya configurado) |
| cognee-mcp no conecta | `cognee-cli serve` conecta a Cloud, no al MCP local | usa Docker: `docker run -d ... cognee/cognee-mcp:main` |
| Skills de oh-my-opencode desaparecen | `.opencode/vendor/` está gitignored | re-ejecuta `environment/setup_fase4.ps1` |
| Error de codificación al imprimir | consola Windows cp1252 | los módulos ya reconfiguren stdout a UTF-8 |
