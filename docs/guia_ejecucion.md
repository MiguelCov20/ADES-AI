# Guía de ejecución — ADES-AI v1.2

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

Observabilidad (necesaria para medir el KPI 1):
`docker compose -f docker-compose.langfuse.yml up -d` → Langfuse v4 en `http://localhost:3000`
(Postgres + ClickHouse + Redis + MinIO; el proyecto y las API keys se crean solos con las
variables `LANGFUSE_INIT_*` de `.env`).

Todo de una vez: `ades start` (o `ades.bat start`).

### 2.3.1 Gateway Bifrost (auth/scope)
Con `ADES_GATEWAY=bifrost` en `.env`, todas las llamadas LLM pasan por Bifrost
(`mcp_servers/gateway/bifrost.config.json`). Dos virtual keys: `BIFROST_VK_FACTORY`
(todos los proveedores) y `BIFROST_VK_LOCAL` (solo modelos Ollama).

### 2.3.2 Sandbox de QA
`docker build -t ades-sandbox:py311 environment/sandbox` (se construye solo la primera vez
que QA lo necesita). Los tests corren con `--network none`, sin privilegios.

### 2.4 Modelos locales (Ollama)

```powershell
powershell -ExecutionPolicy Bypass -File environment/setup_ollama.ps1
```

Descarga: `gpt-oss:20b`, `qwen3.8:27b-iq3` (importa GGUF local), `llama3.2:3b`,
`nomic-embed-text`.

Después crea las variantes con contexto fijo (obligatorio si usas Bifrost: el servidor
Ollama usa 65536 de contexto por defecto y por el gateway no se puede enviar `num_ctx`):

```powershell
powershell -ExecutionPolicy Bypass -File environment/setup_ollama_ctx.ps1
```

### 2.4.1 Serving concurrente local: llama.cpp (Windows + AMD) / vLLM (Linux)

- **Linux (ROCm o CUDA): usa vLLM.** Es la mejor opción (PagedAttention, máximo throughput):
  `python -m automation.model_serving generate` → `environment/vllm/docker-compose.{rocm,cuda}.yml`.
- **Windows 11 + AMD RX 9070 XT: usa llama.cpp `llama-server`.** vLLM no corre de forma nativa
  en Windows; `llama-server` ofrece batching continuo y slots paralelos con caché KV unificada
  sobre ROCm/HIP o Vulkan.

```powershell
powershell -ExecutionPolicy Bypass -File environment/setup_llamacpp.ps1   # release oficial ggml-org
```

En `.env`: `ADES_LOCAL_BACKEND=llamacpp` (y `ADES_LLAMACPP_BACKEND=rocm|vulkan`), `ADES_LLAMACPP_DIR=F:/IA/llamacpp/b12292` y `ADES_GGUF_DIR=F:/IA/gguf`.

**Dónde están los modelos (desde el 12/11/2026):** todo en `F:\IA`:
- `ollama\models`: modelos de Ollama (variable de usuario `OLLAMA_MODELS`).
- `gguf\`: GGUF con nombre legible para llama.cpp. Son enlaces duros a los blobs de Ollama (no ocupan espacio extra), más Qwen3.6-35B-A3B.
- `llamacpp\`: binarios ROCm/Vulkan.
- `huggingface\`: modelo de voz de whisper (variable `HF_HOME`).

Si borras un modelo de Ollama, borra también su enlace en `gguf\`; si no, el espacio no se libera. La pasarela
arranca bajo demanda un `llama-server` por modelo (8081 gpt-oss, 8082 llama3.2, 8083 qwen3.8, 8084 Qwen3.6-35B-A3B),
reutilizando los GGUF de Ollama, y libera la VRAM de Ollama antes. En Bifrost queda registrado
como proveedor `vllm`: en Linux basta con apuntar esa entrada a vLLM.

### 2.4.2 Voz (micrófono)

`pip install faster-whisper sounddevice`. Se usa el micrófono de la webcam automáticamente
(o `ADES_MIC_DEVICE`). Transcripción local con whisper `small` en CPU ($0, sin red tras la
primera descarga).

```powershell
ades voice --mic-test     # graba una orden y muestra texto + comando
ades voice                # bucle por micrófono ("salir" para terminar); --texto para teclado
```

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

### 3.7 CLI unificado y panel

```powershell
ades status                      # servicios, GPU, presupuesto por proyecto
ades run "requerimiento" --project demo-api
ades bootstrap "tienda" --descripcion "API de productos"   # crea proyecto + backlog
ades backlog work --project tienda --background            # agota tickets en background
ades budget set --project tienda --usd 2
ades tokens                      # tokens, costo y hit-rate
ades dashboard                   # http://127.0.0.1:8765 (se refresca solo)
ades tools scan <id> / approve <id> / integrate <id>       # registry con cuarentena
ades memory remember "prefiero FastAPI"  /  ades memory why "por qué Qdrant"
ades watchdog --project tienda   ·  ades bench  ·  ades council  ·  ades audit
```

### 3.8 Tests y KPIs

```powershell
python -m pytest -m "not live" -q      # unitarios (rápidos, sin servicios)
python -m pytest -q                    # todo, incluidos los live (Docker, Ollama, nube)
python -m kpis.kpi_tokens              # KPI 1: ahorro de tokens leído de Langfuse
python -m kpis.kpi_loop                # KPI 2 y 3: costo $0 y bucle Dev⇄QA
python -m kpis.kpi_halluc              # KPI 4: anti-alucinación
python -m kpis.kpi_scale               # KPI 5: concurrencia (sin vLLM en Windows+AMD)
```

Los resultados se guardan en `.ades/_global/kpis/`.

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
| La fábrica va muy lenta con llama.cpp | otro proceso ocupa la GPU (llama-server huérfano, Ollama con otro modelo) y desborda a la RAM | `Get-Process llama-server`, `ollama ps`; detén lo que sobre. Solo cabe un servidor a la vez |
| gpt-oss mezcla el razonamiento con la respuesta | falta la plantilla harmony (el GGUF de Ollama no la trae) | ya se pasa `environment/llamacpp/templates/gpt-oss.jinja` |
| El build ROCm no ve la GPU | faltan hipBLAS/rocBLAS | `setup_llamacpp.ps1` las copia de Ollama, o instala el AMD HIP SDK; alternativa: `ADES_LLAMACPP_BACKEND=vulkan` |
| Error de codificación al imprimir | consola Windows cp1252 | los módulos ya reconfiguren stdout a UTF-8 |
| La fábrica se queda esperando a Gemini | el cliente de Google no siempre respeta su timeout | ya hay timeout duro (`ADES_LLM_TIMEOUT`, 120 s) + fallback en cascada + circuit breaker |
| `429 OpenCode Go usage limit reached` | cuota del plan OpenCode Go agotada | la cascada cae a Gemini/local; espera al reinicio de la cuota |
| VRAM llena con llama3.2:3b (10 GB) | contexto 65536 por defecto del servidor Ollama | usa las variantes `-ctx16k` (`setup_ollama_ctx.ps1`) |
| `activate` del registry se niega | la herramienta no está aprobada o compite con otra | `ades tools scan <id>` → `ades tools approve <id>`; ver `ades tools conflicts <id>` |
