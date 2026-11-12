# Comandos `ades` — referencia completa

`ades` es el **CLI unificado de ADES-AI** (feature #26): un solo comando para levantar
servicios, lanzar la fábrica multi-agente, gestionar proyectos, agentes, herramientas,
memoria, evaluaciones y automatizaciones.

**Cómo se invoca**

```powershell
ades <comando> [subcomando] [opciones]
```

- `ades` es `ades.bat` (raíz del repo), que hace `pushd` a la carpeta de ADES-AI y ejecuta
  `python -m ades_cli %*`. Por eso funciona desde cualquier carpeta, pero **las rutas
  relativas que pases se resuelven desde la raíz de ADES-AI**, no desde tu carpeta actual
  (usa rutas absolutas en `audit`, `council`, `regression`, `index`, `repomap`...).
- Equivalente sin el `.bat`: `python -m ades_cli <comando>` desde la raíz del repo.
- `ades`, `ades help`, `ades -h` o `ades --help` muestran la lista breve de comandos.
- Si añadiste la carpeta de ADES-AI al `PATH` con una PowerShell ya abierta, **cierra y
  reabre la terminal**: las sesiones abiertas antes no ven el `PATH` nuevo.

**Sobre `--help`.** Los comandos *delegados* (backlog, agent, tools, bench...) usan
`argparse` y aceptan `--help` (el `usage:` mostrará el nombre del módulo, p. ej.
`backlog.py`, en lugar de `ades backlog`). Los comandos *propios* de `ades_cli.py`
(start, status, tokens, project, budget, memory, dashboard, gpu) **no tienen `--help`**:
ignoran la opción y **ejecutan el comando** (ojo con `ades start --help`, que levanta
Docker, y `ades dashboard --help`, que arranca el servidor). Excepciones documentadas en
cada sección: `voice`, `audit` y `repomap` tampoco tienen `--help`.

---

## Tabla resumen

Leyenda de coste: **Nube $** = llama a modelos de pago (Gemini / OpenCode Go) salvo que el
presupuesto lo fuerce a local · **GPU** = modelos locales en Ollama (gratis, pero tarda y
ocupa VRAM) · **Docker** = necesita Docker Desktop (sandbox o servicios) · **—** = local,
rápido, sin LLM.

| Comando | Qué hace | LLM / GPU / Docker / nube |
|---|---|---|
| **Ecosistema** | | |
| `ades start` | Levanta los contenedores (Neo4j, Qdrant, Redis, Bifrost, Langfuse) y muestra el estado | Docker |
| `ades status` | Estado de servicios, GPU y gasto por proyecto | — (hace ping a servicios) |
| `ades tokens` | Llamadas, tokens, costo y hit-rate del caché | — |
| `ades budget` | Ver / cambiar el presupuesto de un proyecto | — |
| **Fábrica y proyectos** | | |
| `ades run` | Fábrica completa PM → Arquitecto → Dev ⇄ QA → Reviewer → DevOps | Nube $ + GPU + Docker |
| `ades project` | Lista o crea proyectos del workspace | — |
| `ades bootstrap` | Crea un proyecto entero (PRD, tickets, esqueleto, git, índice) | Nube $ (PM); + GPU/Docker con `--implementar`; Neo4j opcional |
| `ades backlog` | Kanban de tickets por proyecto; los Developers lo trabajan solos | `add`: Nube $ (salvo `--raw`); `work`: Nube $ + GPU + Docker; `board`: — |
| **Agentes** | | |
| `ades agent` | Reclutador: lista, crea, modifica y elimina agentes del roster | — (solo edita `roster.json`) |
| **Tool Registry** | | |
| `ades tools` | Catálogo de herramientas: buscar, añadir, escanear, aprobar, activar, versionar, puntuar | `scan`/`integrate`/`pin`/`update`: git + Docker (bandit); resto: — |
| `ades integrate` | Atajo de `ades tools integrate` | git + Docker |
| **Memoria** | | |
| `ades memory` | Atajo: recordar, buscar, "¿por qué?" y consolidar | GPU (embeddings); `why`/`consolidate`: LLM; `why` puede usar Graphiti (Nube $) |
| `ades knowledge` | Memoria cross-proyecto (preferencias, decisiones, lecciones) | GPU (embeddings `nomic-embed-text`, opcional) |
| `ades timeline` | Registro de decisiones de arquitectura | `add`: Graphiti (Nube $, desactivable); `why`: LLM |
| `ades vaccine` | "Vacunas": bugs ya resueltos y parecidos | GPU (embeddings, opcional) |
| `ades reflect` | Consolidación nocturna (lecciones, deduplicado, VACUUM) | LLM (salvo `--dry-run`) + GPU (embeddings) |
| `ades index` | Indexa un repo Python en el grafo Neo4j (Tree-sitter) | Docker (Neo4j) |
| `ades repomap` | Esqueleto del código desde Neo4j + ahorro de contexto | Docker (Neo4j) |
| **Evaluación** | | |
| `ades bench` | Benchmark local tipo SWE-bench mini (tests ocultos) | Nube $ o GPU + Docker |
| `ades council` | LLM Council: varios modelos juzgan una salida | Nube $ / GPU (varios modelos) |
| `ades ab` | A/B test entre dos modelos | Nube $ / GPU + Docker (o juez LLM) |
| `ades audit` | Auditoría anti-IA de código (secretos, eval, deps alucinadas...) | Docker (bandit); reglas propias offline |
| `ades regression` | ¿Un prompt nuevo empeora la calidad? | Nube $ / GPU + Docker |
| **Automatización** | | |
| `ades watchdog` | Vigila el repo y corre los tests al detectar cambios | Docker (tests); `--install-task --apply` crea tarea de Windows |
| `ades prefetch` | Precalienta el contexto que pedirá una tarea | Neo4j opcional + GPU (embeddings, opcional) |
| `ades voice` | Traduce órdenes habladas/escritas a comandos `ades` (no los ejecuta) | GPU (`llama3.2:3b` de respaldo); micrófono opcional |
| `ades skills` | Detecta tareas repetidas y genera skills (`SKILL.md`) | `generate`: GPU (`gpt-oss:20b`); resto: — |
| `ades improve` | Automejora del prompt de un agente con control de regresión | GPU + Nube $/Docker (regression) |
| `ades serving` | Router OpenAI-compatible multi-modelo / genera config vLLM | GPU (Ollama) en `serve`; `generate`: — |
| **Panel y GPU** | | |
| `ades dashboard` | Panel web en http://127.0.0.1:8765 | — |
| `ades gpu` | Modelos cargados en Ollama y uso de VRAM | — (consulta Ollama) |

Total: **31 comandos** (10 propios de `ades_cli.py` + 21 delegados a módulos).

---

## Ecosistema

### `ades start`

Levanta toda la infraestructura Docker y al terminar muestra `ades status`.

```powershell
ades start
```

- Ejecuta, desde la raíz de ADES-AI:
  `docker compose -f docker-compose.yml up -d` y
  `docker compose -f docker-compose.langfuse.yml up -d`.
- Sin opciones. **No tiene `--help`**: cualquier argumento se ignora y se levanta Docker.
- Requiere Docker Desktop arrancado. La primera vez puede tardar (descarga de imágenes).

### `ades status`

Muestra qué está vivo y cuánto se ha gastado.

```powershell
ades status
```

- **Servicios** (OK/OFF por ping HTTP, 3 s de timeout): Neo4j `:7474`, Qdrant `:6333`,
  Bifrost `:8080`, Langfuse `:3000`, Ollama `:11434`.
- **GPU**: VRAM usada/total, modelos cargados y si alguno hace *offload* a CPU.
- **Proyectos**: gasto `$` frente al presupuesto, % usado y nivel (`any`, `cheap`, `local`).
- Sin opciones; los argumentos se ignoran.

### `ades tokens`

Resumen de métricas del gateway LLM: llamadas, cache hits y hit-rate, tokens in/out,
tokens locales ($0), costo, errores y desglose por agente/modelo.

```powershell
ades tokens
ades tokens --project tienda
```

- `--project P`: filtra por proyecto. Sin él, global.
- Sin `--help` (se ignora y muestra el resumen).

### `ades budget`

Muestra (y opcionalmente cambia) el presupuesto de un proyecto. Imprime JSON con
`budget`, `spent`, `used_fraction` y `tier`.

```powershell
ades budget show --project tienda
ades budget set --project tienda --usd 5 --tokens 2000000
```

Sintaxis: `ades budget [show|set] [--project P] [--usd X] [--tokens N]`

- `--project P`: proyecto (por defecto `ades-ai`).
- `set`: guarda los límites indicados; `--usd` (float) es el tope en dólares y
  `--tokens` (entero) el tope de **tokens de pago**. Puedes pasar solo uno.
- Cualquier primer argumento distinto de `set` (incluido `show` o nada) solo muestra.
- Niveles: `any` (< 80 % usado, cualquier modelo), `cheap` (80–100 %, solo modelos
  baratos), `local` (≥ 100 %, solo Ollama).
- **Advertencia:** `budget set` cambia los límites reales que usa el gateway para decidir
  qué modelos puede llamar la fábrica. Bajarlos puede forzar modelos locales (más lentos
  o peores); subirlos permite gastar más dinero.

---

## Fábrica y proyectos

### `ades run`

Lanza la **fábrica multi-agente completa** (LangGraph) para un requerimiento:
contexto (RepoMap) → PM (Gemini, PRD + tickets) → Arquitecto (Gemini) → Developer ⇄ QA
(self-healing, anti-alucinación y tests en sandbox Docker) → escritura de archivos →
Reviewer (DeepSeek) + auditoría anti-IA → DevOps.

```powershell
ades run "API REST de productos con FastAPI" --project tienda
ades run "añade paginación al listado" --project tienda --max-iter 3 --no-write
```

Sintaxis (`agents/orquestador.py`, `--help` funcional):

```
ades run [--project PROJECT] [--max-iter MAX_ITER] [--no-write] requerimiento
```

- `requerimiento`: texto entre comillas.
- `--project`: proyecto destino (por defecto `ades-ai`).
- `--max-iter`: iteraciones máximas Dev ⇄ QA (por defecto `5`).
- `--no-write`: no escribe los archivos en el proyecto (solo genera y valida).
- Imprime estado, run_id, iteraciones, archivos generados/escritos, llamadas, tokens,
  costo, cache hits, duración y un extracto de la review. Código de salida 0 si `ok`.
- **Advertencias:** usa modelos de **nube de pago** y **locales (GPU)**, y ejecuta los
  tests en **Docker** (sandbox). Puede tardar minutos y cuesta dinero según el
  presupuesto. Sin `--no-write`, **escribe archivos** en el proyecto.

### `ades project`

Gestiona el workspace multi-proyecto.

```powershell
ades project list
ades project create tienda online
```

Sintaxis: `ades project [list | create NOMBRE...]`

- `list` (o sin argumentos): id y ruta de cada proyecto.
- `create NOMBRE`: crea la carpeta en el workspace y lo registra; todas las palabras se
  unen y se convierten en *slug* (`tienda online` → id tipo `tienda-online`). Si ya
  existe, devuelve el existente sin tocarlo.
- Sin `--help`: con un argumento desconocido (p. ej. `--help`) no hace nada.

### `ades bootstrap`

**Project Bootstrapper**: crea un proyecto entero en un comando: lo registra, el PM genera
PRD + tickets y los mete en el backlog, genera el esqueleto (README, requirements,
.gitignore, Dockerfile, CI de GitHub Actions, paquete y tests), hace `git init` + primer
commit local e indexa el código en Neo4j.

```powershell
ades bootstrap "tienda online" --descripcion "API de productos y carrito"
ades bootstrap "cli notas" --sin-plan
```

Sintaxis (`agents/bootstrap.py`, `--help` funcional):

```
ades bootstrap [--descripcion DESCRIPCION] [--implementar] [--sin-plan] nombre
```

- `--descripcion`: descripción para el PM y el README.
- `--implementar`: además, la fábrica implementa el **primer ticket** (Dev ⇄ QA con
  sandbox).
- `--sin-plan`: no llama al PM (sin PRD ni tickets); solo esqueleto + git.
- **Advertencias:** llama al PM (nube $) salvo `--sin-plan`; `--implementar` añade
  modelos + Docker. Hace un commit git local en el proyecto nuevo (no en ADES-AI). Si
  Neo4j no está levantado, el indexado se marca "no disponible" y sigue.

### `ades backlog`

Kanban persistente por proyecto (`.ades/<proyecto>/backlog.json`, columnas
todo → doing → done | failed). El PM trocea requerimientos en tickets y los Developers
los trabajan solos.

```powershell
ades backlog add "Tienda con carrito y pagos" --project tienda
ades backlog board --project tienda
ades backlog work --project tienda --max 3 --background
```

Sintaxis (`agents/backlog.py`, `--help` funcional):

```
ades backlog add   requerimiento [--project PROJECT] [--raw]
ades backlog board [--project PROJECT]
ades backlog work  [--project PROJECT] [--max MAX] [--background]
```

- `--project`: por defecto `ades-ai` en los tres subcomandos.
- `add --raw`: añade el texto tal cual como un ticket, sin pasar por el PM (sin LLM).
- `work --max N`: máximo de tickets a procesar (por defecto, hasta agotar).
- `work --background`: lanza un worker en segundo plano e imprime su PID.
- **Advertencias:** `add` (sin `--raw`) llama al PM (nube $). `work` ejecuta la fábrica
  completa por cada ticket (nube $ + GPU + Docker) y puede seguir trabajando en
  background tras cerrar el comando.

---

## Agentes

### `ades agent`

**Reclutador** (meta-agente): crea, modifica y elimina agentes del roster
(`roster.json`). Si no indicas modelo, elige el LLM según el rol (p. ej. roles de
PM/arquitectura/análisis → Gemini; por defecto `ollama/gpt-oss:20b`).

```powershell
ades agent list
ades agent create "Agente UX" "disenar interfaces y experiencia de usuario"
ades agent update agente_ux --provider ollama --model gpt-oss:20b --skills "figma,accesibilidad"
ades agent delete agente_ux
```

Sintaxis (`agents/reclutador.py`, `--help` funcional):

```
ades agent list
ades agent create nombre rol [--provider PROVIDER] [--model MODEL]
ades agent update id [--provider PROVIDER] [--model MODEL] [--rol ROL] [--skills SKILLS]
ades agent delete id
```

- `--skills`: lista separada por comas (reemplaza las skills del agente).
- `update` con solo `--provider` o solo `--model` conserva el otro valor actual.
- No llama a ningún LLM: solo edita el roster. `delete` no pide confirmación.

---

## Tool Registry

### `ades tools`

Catálogo de herramientas externas con cuarentena de seguridad, ratings, detección de
conflictos y versionado.

**Flujo seguro para usar una herramienta nueva:**

```powershell
ades tools add https://github.com/usuario/repo --tipo tool
ades tools scan repo
ades tools approve repo --autor Miguel
ades tools integrate repo
ades tools activate repo
```

Sintaxis (`registry/cli.py`, `--help` funcional; subcomandos y opciones exactas):

| Subcomando | Sintaxis | Qué hace |
|---|---|---|
| `list` | `ades tools list` | Catálogo con estado: activa/inactiva, integrada, estado de cuarentena, commit |
| `search` | `ades tools search query` | Busca en el catálogo, ordenado por rating |
| `add` | `ades tools add url [--tipo TIPO]` | Añade un repo al catálogo (por defecto `--tipo tool`); queda *sin verificar* |
| `integrate` | `ades tools integrate id [--dry-run] [--force] [--no-bandit]` | Integra (instala) la herramienta; si no está aprobada, la escanea y la deja en cuarentena |
| `activate` | `ades tools activate id [--force]` | Activa una herramienta **aprobada** |
| `deactivate` | `ades tools deactivate id` | Desactiva (no desinstala) |
| `rate` | `ades tools rate id score [--comentario C] [--autor A]` | Puntúa 1–5 (autor por defecto `anonimo`) |
| `tag` | `ades tools tag id tag [tag ...]` | Añade etiquetas |
| `top` | `ades tools top [-n N] [--tipo TIPO]` | Mejor valoradas (por defecto `-n 5`) |
| `conflicts` | `ades tools conflicts id` | Detecta herramientas que compiten con ella |
| `pin` | `ades tools pin id ref [--force] [--no-bandit]` | Fija a un commit/tag/rama (re-escanea) |
| `update` | `ades tools update id [--force] [--no-bandit]` | Actualiza a la última versión (guarda historial) |
| `rollback` | `ades tools rollback id` | Vuelve al commit anterior |
| `scan` | `ades tools scan id [--no-bandit] [--refresh]` | Clona en cuarentena y escanea (reglas + bandit en Docker) |
| `approve` | `ades tools approve id --autor AUTOR [--force]` | Aprueba una herramienta escaneada (sale de cuarentena) |
| `quarantine` | `ades tools quarantine` | Lista herramientas en cuarentena |

Notas de opciones:

- `--force` en `integrate`/`activate`: ignora conflictos con herramientas activas.
  En `pin`: acepta veredicto `cuarentena` del re-escaneo. En `update`: ignora el pin y
  acepta veredicto `cuarentena`. En `approve`: aprueba **aunque el veredicto sea
  `rechazado`**.
- `--no-bandit`: no ejecuta bandit en el sandbox Docker (escaneo solo con reglas propias).
- `scan --refresh`: vuelve a clonar la copia de cuarentena.
- `integrate --dry-run`: muestra el plan sin ejecutarlo.

**Advertencias:**

- `activate` **exige `scan` + `approve`** previos: si la herramienta no está en estado
  aprobada, falla con "no se puede activar sin escaneo y aprobacion (scan + approve)".
- `integrate` sobre una herramienta no aprobada **no instala nada**: la escanea, la deja
  en cuarentena (código de salida 2) y te indica que ejecutes `approve`.
- `integrate` sin `--dry-run` sobre una aprobada **instala/ejecuta** el método de
  integración real.
- `approve --force` y `--force` en general saltan protecciones de seguridad: úsalos solo
  tras revisar el informe.
- `scan`, `pin`, `update` clonan con git y usan Docker (bandit).

### `ades integrate`

Atajo de `ades tools integrate`: `ades integrate ID ...` = `ades tools integrate ID ...`
(mismas opciones `--dry-run`, `--force`, `--no-bandit`; `ades integrate --help` muestra la
ayuda de ese subcomando).

```powershell
ades integrate repo --dry-run
```

Mismas advertencias que `tools integrate`.

---

## Memoria

### `ades memory`

Atajo cómodo sobre los módulos de memoria. **Sin `--help`**: sin argumentos imprime
`uso: ades memory remember|recall|why|consolidate ...`; un subcomando desconocido no hace
nada.

```powershell
ades memory remember prefiero FastAPI
ades memory remember usamos Postgres --project tienda
ades memory recall qué framework web uso
ades memory why ¿por qué usamos Qdrant?
ades memory consolidate
```

| Subcomando | Equivale a | Detalle |
|---|---|---|
| `remember TEXTO [--project P]` | `knowledge.remember` | Sin `--project`: recuerdo **global** (todos los proyectos). Con `--project P`: alcance de proyecto. Tipo siempre `preference`; para elegir tipo usa `ades knowledge remember --kind`. |
| `recall TEXTO` | `knowledge.recall_context` | Une todas las palabras como consulta. **No admite `--project`** (se trataría como parte del texto); usa `ades knowledge recall --project`. |
| `why PREGUNTA` | `timeline.why` | Responde con la timeline de decisiones del proyecto por defecto. Para otro proyecto: `ades timeline why --project`. |
| `consolidate` | `reflection.consolidate()` | Consolida el proyecto por defecto (últimas 24 h) **llamando al LLM y escribiendo** (no es dry-run). Para simular: `ades reflect --dry-run`. |

### `ades knowledge`

Memoria cross-proyecto (SQLite global con embeddings `nomic-embed-text`; sin Ollama cae a
similitud léxica).

```powershell
ades knowledge remember "prefiero FastAPI" --kind preference --scope global
ades knowledge recall "qué framework web uso" --project tienda -k 3
```

Sintaxis (`memory/knowledge.py`, `--help` funcional):

```
ades knowledge remember text [--kind {preference,decision,lesson,fact}] [--scope {global,project}] [--project PROJECT]
ades knowledge recall query [--project PROJECT] [-k K]
```

- Defaults: `--kind preference`, `--scope global`, `-k 5`.
- `scope=global`: lo aprendido en un proyecto aparece en todos; `project`: solo en ese.
- Sincronización con Mem0 solo si `ADES_MEM0_SYNC=1` (desactivada por defecto porque
  Mem0 llama a un LLM de pago).

### `ades timeline`

Registro de decisiones de arquitectura (SQLite local + Graphiti/Neo4j como episodio
temporal).

```powershell
ades timeline add "Usar Qdrant" "Ya está en Docker y es rápido" --alt "pgvector" --alt "Chroma"
ades timeline list --project tienda --query qdrant
ades timeline why "¿por qué usamos Qdrant?"
```

Sintaxis (`memory/timeline.py`, `--help` funcional):

```
ades timeline add title rationale [--project PROJECT] [--alt ALT ...]
ades timeline list [--project PROJECT] [--query QUERY]
ades timeline why question [--project PROJECT]
```

- `--alt` se puede repetir (alternativas descartadas).
- Sin `--project` usa el proyecto por defecto (`ADES_PROJECT`, por defecto `ades-ai`).
- **Advertencia:** Graphiti usa un **LLM de pago** (OpenCode Go) por cada episodio en
  `add`. Desactívalo con `ADES_TIMELINE_GRAPHITI=0` (solo registro local).

### `ades vaccine`

"Vacunas" contra bugs: cada bug resuelto se guarda como patrón (firma normalizada +
corrección) y la fábrica lo consulta antes de generar código.

```powershell
ades vaccine match "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
ades vaccine list
```

Sintaxis (`memory/vaccine.py`, `--help` funcional):

```
ades vaccine match text
ades vaccine list
```

- No hay subcomando para añadir vacunas a mano: las registra la fábrica.

### `ades reflect`

Consolidación nocturna: lee la actividad del periodo, resume lecciones con el LLM y las
guarda en knowledge, deduplica memorias casi iguales (knowledge y vacunas) y compacta
SQLite (VACUUM).

```powershell
ades reflect --project tienda --hours 48 --dry-run
ades reflect --all
ades reflect --schedule --hour 3
ades reflect --schedule --hour 3 --create
```

Sintaxis (`memory/reflection.py`, `--help` funcional):

```
ades reflect [--project PROJECT] [--all] [--hours HOURS] [--dry-run] [--schedule] [--hour HOUR] [--create]
```

- `--all`: todos los proyectos registrados. `--hours`: ventana (por defecto `24`).
- `--dry-run`: no escribe, no borra y no llama al LLM; solo informa.
- `--schedule`: muestra el comando `schtasks` de la tarea diaria (a las `--hour`:00, por
  defecto 3). Con `--create` **crea la tarea programada de Windows**.
- **Advertencia:** sin `--dry-run` llama al LLM y **borra duplicados** de la memoria.

### `ades index`

Indexador determinista (sin LLM): analiza un repo Python con Tree-sitter y escribe
archivos, clases, funciones, imports, herencia y llamadas en Neo4j (RepoMap
anti-alucinación).

```powershell
ades index --repo "C:\Users\Miguel Dev\Desktop\Proyectos\ADES-AI" --summary
```

Sintaxis (`memory/indexer.py`, `--help` funcional):

```
ades index --repo REPO [--reset] [--summary]
```

- `--repo` es obligatorio (usa ruta absoluta: `ades.bat` cambia a la raíz de ADES-AI).
- `--reset`: **limpia el grafo** antes de indexar (borra lo indexado previamente).
- `--summary`: muestra conteos del grafo al final.
- Requiere Neo4j levantado (`ades start`).

### `ades repomap`

Genera el esqueleto del código (archivo → clases → funciones) desde el grafo Neo4j y mide
el ahorro frente a cargar el código completo.

```powershell
ades repomap
ades repomap --repo "C:\ruta\al\repo"
```

Sintaxis: `ades repomap [--repo RUTA]`

- **Sin argparse ni `--help`**: solo reconoce `--repo`; cualquier otro argumento se
  ignora y el comando se ejecuta igual.
- Requiere que el repo esté indexado (`ades index`) y Neo4j levantado.

---

## Evaluación

### `ades bench`

Benchmark local estilo SWE-bench mini: el Developer resuelve cada tarea de
`evals/benchmarks/tasks/*.json`, se añaden tests **ocultos** y se ejecutan en el sandbox
Docker (sin red). Reporta pass@1, tiempo, tokens y costo, y lo guarda en
`.ades/_global/benchmarks/`.

```powershell
ades bench --provider ollama --model gpt-oss:20b --tasks roman-numerals lru-cache
ades bench
```

Sintaxis (`evals/benchmark.py`, `--help` funcional):

```
ades bench [--provider PROVIDER] [--model MODEL] [--tasks [TASKS ...]]
```

- Sin `--provider/--model`: el gateway elige (`auto`), puede usar nube de pago.
- Sin `--tasks`: todas. Tareas incluidas hoy: `fastapi-todos`, `lru-cache`,
  `merge-intervals`, `parse-duration`, `roman-numerals`, `rpn-calculator`,
  `word-frequency`.
- **Advertencia:** usa LLM (nube $ o GPU) y Docker; con todas las tareas tarda.

### `ades council`

LLM Council como juez: varios modelos evalúan una salida de forma independiente, hacen
revisión cruzada anónima y un "chairman" agrega (mediana + mayoría). Necesita quórum (≥ 2
miembros).

```powershell
ades council "Implementa una cola LRU" "C:\tmp\salida.py" --criterio "correcto" --criterio "eficiente"
```

Sintaxis (`evals/council.py`, `--help` funcional):

```
ades council [--criterio CRITERIO] pregunta salida
```

- `salida`: **ruta a un archivo** con el texto a evaluar (no el texto en sí).
- `--criterio` se puede repetir.
- Imprime JSON (score, verdict, rationale, votes, failed). Salida 0 si `PASS`, 1 si no.
- **Advertencia:** varias llamadas LLM por evaluación (sin caché).

### `ades ab`

A/B testing de dos modelos sobre las mismas tareas. Tareas de benchmark se puntúan con
tests ocultos (Docker); casos abiertos con juez LLM. Gana el mayor win-rate; desempata
costo y luego latencia.

```powershell
ades ab ollama:gpt-oss:20b gemini:gemini-flash-latest --tasks roman-numerals merge-intervals
```

Sintaxis (`evals/ab_test.py`, `--help` funcional):

```
ades ab [--tasks [TASKS ...]] modelo_a modelo_b
```

- Formato de modelo: `provider:model` (se parte en el **primer** `:`, así que
  `ollama:gpt-oss:20b` → provider `ollama`, model `gpt-oss:20b`). El nombre exacto de
  provider/modelo deben existir en el gateway (`core/llm_gateway.py` reconoce los providers `gemini`, `opencode` y `ollama`); usa los que tengas configurados en
  el gateway.
- **Advertencia:** ejecuta ambos modelos sobre cada tarea (doble coste) + Docker.

### `ades audit`

Auditoría anti-IA de código: dependencias inexistentes/typosquatting, secretos
hardcodeados, `eval`/`exec`, SQL por concatenación, `shell=True`, deserialización
insegura, TLS desactivado, path traversal, prompts ocultos y caracteres invisibles
(Trojan Source). Reglas propias offline + `bandit` en el sandbox Docker.

```powershell
ades audit "C:\Users\Miguel Dev\Desktop\Proyectos\tienda\app"
ades audit "C:\ruta\main.py" "C:\ruta\utils.py"
```

Sintaxis: `ades audit RUTA [RUTA ...]` (archivos `.py` o carpetas, que se recorren en
`*.py`).

- **Sin argparse ni `--help`**: `ades audit --help` intentaría leer un archivo llamado
  `--help` y fallaría.
- Salida 0 si el veredicto es `PASS`, 1 si no.

### `ades regression`

Regression detector: compara la baseline del agente con un prompt candidato sobre el mismo
conjunto de casos y decide si hay regresión estadísticamente consistente (sign test o IC
bootstrap). Baselines cacheadas en `.ades/_global/regression/`.

```powershell
ades regression developer "C:\tmp\prompt_developer_v2.txt" --source both
```

Sintaxis (`evals/regression.py`, `--help` funcional):

```
ades regression [--source SOURCE] agente prompt_file
```

- `prompt_file`: archivo con el **prompt nuevo**.
- `--source`: `benchmark` (por defecto, tests ocultos en Docker), `cases`
  (`evals/cases/casos.json` puntuado por el juez LLM) o `both`. La ayuda no lista las
  opciones; vienen del docstring de `main()`.
- Salida 1 si hay regresión. Solo evalúa: **no** cambia el prompt.
- **Advertencia:** ejecuta baseline + candidato (LLM y Docker).

---

## Automatización

### `ades watchdog`

Vigila el repositorio de un proyecto (polling de cambios). Ante un cambio compila los
`.py` modificados (sin ejecutarlos) y corre los tests en el sandbox Docker; si algo se
rompe registra la alerta (`watchdog.log`, `alerts.jsonl`) y lanza un toast de Windows.

```powershell
ades watchdog --project tienda --once
ades watchdog --project tienda --interval 60
ades watchdog --project tienda --install-task
ades watchdog --project tienda --install-task --apply
```

Sintaxis (`automation/watchdog.py`, `--help` funcional):

```
ades watchdog [--project PROJECT] [--repo REPO] [--once] [--interval INTERVAL]
              [--no-toast] [--no-tests] [--install-task] [--apply]
```

- `--project`: por defecto el proyecto por defecto (`ADES_PROJECT`, `ades-ai`).
- `--repo`: ruta a vigilar si no quieres la registrada del proyecto.
- `--once`: una pasada y sale (código 1 si algo está roto). Sin `--once` corre
  **indefinidamente** cada `--interval` segundos (por defecto `30`); para con Ctrl+C.
- `--no-toast`: sin notificación de Windows (también `ADES_WATCHDOG_TOAST=0`).
- `--no-tests`: solo compila, no ejecuta tests (no necesita Docker).
- `--install-task`: muestra el comando `schtasks` (cada 5 min con `--once`); con
  `--apply` **crea la tarea programada de Windows**.

### `ades prefetch`

Predice qué archivos/símbolos va a necesitar una tarea (grafo Neo4j o búsqueda léxica) y
precalienta su RepoMap parcial y embeddings en caché con TTL.

```powershell
ades prefetch "añadir autenticación JWT al login" --project tienda
ades prefetch --stats
```

Sintaxis (`automation/prefetch.py`, `--help` funcional):

```
ades prefetch [--project PROJECT] [--no-graph] [--no-embed] [--stats] [task ...]
```

- `task`: palabras de la tarea (no hace falta comillas, se unen).
- Sin `task` o con `--stats`: muestra estadísticas del caché (hit-rate).
- `--no-graph`: no usa Neo4j (solo búsqueda léxica). `--no-embed`: sin embeddings de
  Ollama.

### `ades voice`

Control por voz: traduce una orden en español a la invocación `ades` equivalente (reglas +
respaldo con `llama3.2:3b`). **Solo muestra el comando; no lo ejecuta.**

```powershell
ades voice "lista las herramientas"
ades voice --texto
ades voice --mic-test
ades voice
```

Opciones (lectura manual de `argv`, **sin argparse ni `--help`**):

- `ades voice TEXTO...`: traduce esa orden e imprime JSON (`accion`, `args`, `fuente`,
  `invocacion`).
- `ades voice` (sin nada): bucle interactivo; usa micrófono si hay backend instalado
  (`sounddevice` + `faster_whisper`, o `speech_recognition`), si no lee texto de la
  consola. Sal con `salir`, `adios`, `exit`, `quit` o Ctrl+C.
- `--texto`: fuerza el bucle en modo texto (sin micrófono).
- `--mic-test`: graba una orden y muestra transcripción + traducción.
- `--no-llm`: solo reglas, sin el LLM de respaldo.
- Órdenes soportadas (acciones): integrar, activar, desactivar, agregar/buscar/listar
  herramientas, crear/listar proyectos, crear agente, tokens, estado, iniciar, vigilar.
- **Advertencia:** `ades voice --help` **no** muestra ayuda: trataría `--help` como texto
  de una orden.

### `ades skills`

Auto-skill Generator: detecta tareas que se repiten en el historial de la fábrica y genera
con un LLM una skill `SKILL.md`. Nada se publica sin `publish`.

```powershell
ades skills detect --min 3
ades skills generate --model gpt-oss:20b
ades skills staged
ades skills publish crear-endpoint-fastapi
```

Sintaxis (`automation/skill_generator.py`, `--help` funcional):

```
ades skills {detect,generate,staged,publish} [slug] [--min MIN] [--project PROJECT] [--model MODEL] [--force]
```

- `detect`: clusters de tareas repetidas (mínimo `--min`, por defecto `3` runs).
- `generate`: genera skills con el LLM (`--model`, por defecto `gpt-oss:20b` en Ollama) y
  las deja en **staging** (`state_dir()/skills_staging/auto-<slug>/`).
- `staged`: lista las skills en staging.
- `publish slug`: copia a `.opencode/skills/auto-<slug>/SKILL.md`; `--force` sobrescribe
  si ya existe.
- **Advertencia:** `publish` cambia las skills que usan los agentes.

### `ades improve`

Ecosistema automejorable: recoge fallos recientes de un agente, pide al LLM un prompt
mejorado, lo evalúa con el regression detector y **solo lo aplica si no hay regresión y
mejora**. Todo intento queda registrado en `self_improve.jsonl`.

```powershell
ades improve developer --dry-run
ades improve qa --project tienda
ades improve --history
```

Sintaxis (`automation/self_improve.py`, `--help` funcional):

```
ades improve [--project PROJECT] [--model MODEL] [--dry-run] [--history] [agent]
```

- `agent`: por defecto `developer`.
- `--model`: modelo que propone el prompt (por defecto `gpt-oss:20b`, Ollama).
- `--dry-run`: evalúa pero no aplica.
- `--history`: muestra los últimos 20 intentos.
- **Advertencia:** sin `--dry-run` puede **cambiar el prompt real** del agente. La
  evaluación usa `ades regression` (LLM + Docker).

### `ades serving`

Serving multi-modelo: router OpenAI-compatible con colas, límite de concurrencia, métricas
y failover sobre un pool de modelos; o genera la configuración vLLM.

```powershell
ades serving generate
ades serving serve --models llama3.2:3b gpt-oss:20b --port 8090
```

Sintaxis (`automation/model_serving.py`, `--help` funcional):

```
ades serving serve [--config CONFIG] [--host HOST] [--port PORT] [--models [MODELS ...]]
ades serving generate [--out OUT]
```

- `serve`: sin `--config` usa Ollama local con `--models` (por defecto `llama3.2:3b`).
  Defaults `--host 0.0.0.0`, `--port 8080`. Endpoints `/v1`, `/v1/models`, `/stats`,
  `/health`. Corre hasta Ctrl+C.
- `generate`: escribe `docker-compose.rocm.yml`, `docker-compose.cuda.yml` y
  `models.json` en `environment/vllm/` (o `--out`).
- **Advertencias:** el puerto por defecto `8080` es el mismo que **Bifrost**; si Bifrost
  está levantado usa otro `--port`. `--host 0.0.0.0` expone el router en la red local.
  vLLM requiere Linux: la configuración generada no está verificada en ejecución en esta
  máquina (Windows + AMD).

---

## Panel y GPU

### `ades dashboard`

Panel web local (FastAPI + uvicorn) con agentes, tokens/costo, hit-rate del caché en vivo,
presupuesto, proyectos y backlog, herramientas, GPU y últimas ejecuciones. Se refresca
cada 3 s.

```powershell
ades dashboard
```

- Abre http://127.0.0.1:8765 en el navegador (puerto configurable con
  `ADES_DASHBOARD_PORT`). Ocupa la terminal hasta Ctrl+C.
- Sin opciones ni `--help` (cualquier argumento se ignora y arranca el servidor).

### `ades gpu`

Imprime JSON con la VRAM total (`vram_gb`), la usada (`used_gb`), los modelos cargados en
Ollama (`loaded`) y los que hacen offload a CPU (`cpu_offload`).

```powershell
ades gpu
```

- Sin opciones; requiere Ollama en marcha para ver modelos.

---

## Puntos no confirmados o a tener en cuenta

- Los comandos propios (`start`, `status`, `tokens`, `project`, `budget`, `memory`,
  `dashboard`, `gpu`) y los delegados `voice`, `audit` y `repomap` **no tienen `--help`**;
  sus opciones se documentan leyendo el código de `ades_cli.py` y de cada módulo.
- `ades regression --source`: la ayuda de argparse no lista los valores válidos; los
  valores `cases|benchmark|both` salen del docstring de `main()`.
- `ades ab`: los nombres concretos de provider/modelo de nube dependen de la configuración
  del gateway; el formato `provider:model` sí está confirmado.
- Las opciones de los subcomandos (`backlog work`, `tools scan`, `serving serve`, etc.) se
  tomaron del código argparse; la ayuda de nivel superior de cada módulo se verificó con
  `python -m <modulo> --help`.
