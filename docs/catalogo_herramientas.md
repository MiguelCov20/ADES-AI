# Catálogo de Herramientas Externas — ADES-AI

> **Proyecto:** ADES-AI (Ecosistema de Desarrollo con Inteligencia Artificial)
> **Fecha:** 5 de Noviembre de 2026
> **Propósito:** Lista completa y verificada de todas las herramientas, frameworks, modelos y servicios externos que usará el ecosistema, con una descripción sencilla y su enlace oficial.

---

## 1. Agentes de Código (tu "copiloto" diario)

### OpenCode ⭐ (central del ecosistema)
El agente de IA open-source con el que ya trabajas. Corre en la terminal, escritorio o editor, es agnóstico de proveedor (funciona con 75+ modelos) y tiene Skills, Plugins, subagentes, MCP y análisis de código (LSP) nativos. Es el "cerebro conductor" del ecosistema.
- 🔗 **GitHub:** https://github.com/anomalyco/opencode
- 🔗 **Docs:** https://opencode.ai/docs

### Cline
Agente de código open-source dentro de VS Code. Ideal para quien quiere ver y aprobar cada cambio paso a paso. Habla MCP nativamente.
- 🔗 **GitHub:** https://github.com/cline/cline

### Aider
Programador de pares en la terminal, experto en Git. Crea "mapas" del repositorio para no cargar todo el código en contexto (clave para ahorrar tokens).
- 🔗 **GitHub:** https://github.com/Aider-AI/aider

### OpenHands
Ingeniero de software autónomo: le das un issue de GitHub y él clona, planifica, codifica, testea y crea el Pull Request solo.
- 🔗 **GitHub:** https://github.com/All-Hands-AI/OpenHands

### Roo Code *(alternativa)*
Variante de Cline enfocada en cambios grandes de forma fiable.
- 🔗 **GitHub:** https://github.com/RooCodeInc/Roo-Code

---

## 2. Skills y Contexto (enseñarle "oficios" al agente)

### Obra Superpowers ⭐
El framework de "skills" más completo (247k estrellas). Le da al agente una metodología de trabajo completa: lluvia de ideas → plan → desarrollo con pruebas → revisión. Convierte al agente en un ingeniero disciplinado.
- 🔗 **GitHub:** https://github.com/obra/superpowers

### oh-my-opencode / oh-my-openagent ⭐
Plugin que orquesta una flota de agentes especializados en paralelo (Sisyphus, Oracle, Librarian, Explore, Atlas, etc.) con modo "ultrawork" para tareas en segundo plano.
- 🔗 **GitHub:** https://github.com/code-yeongyu/oh-my-openagent

### Estándar AGENTS.md
Formato universal de instrucciones de proyecto que leen casi todos los agentes (OpenCode, Codex, Cursor, Gemini CLI, Claude Code). Es la "regla de oro" permanente del repositorio.
- 🔗 **Sitio:** https://agents.md

---

## 3. Frameworks de Orquestación (el "director de orquesta")

### LangGraph ⭐
Framework para construir la "fábrica" de agentes como un grafo: define quién hace qué, en qué orden, y permite ciclos (ej: Developer ⇄ QA hasta que pase). El motor autónomo del ecosistema.
- 🔗 **GitHub:** https://github.com/langchain-ai/langgraph

### LangChain
Biblioteca base para conectar modelos, prompts y herramientas. LangGraph se construye sobre ella.
- 🔗 **GitHub:** https://github.com/langchain-ai/langchain

### CrewAI *(alternativa)*
Framework multiagente por "roles" (cada agente tiene personalidad y tarea). Más fácil de armar, menos control fino.
- 🔗 **GitHub:** https://github.com/crewAIInc/crewAI

### OpenAI Agents SDK *(alternativa)*
SDK ligero para encadenar agentes con "handoffs" (traspaso de control). Bueno para flujos lineales simples.
- 🔗 **GitHub:** https://github.com/openai/openai-agents-python

### MetaGPT *(alternativa)*
"La primera empresa de software de IA": convierte una idea en un proyecto completo con agentes de PM, arquitecto e ingeniero.
- 🔗 **GitHub:** https://github.com/FoundationAgents/MetaGPT

### ChatDev *(alternativa)*
Empresa de software virtual con agentes (CEO, CTO, programador, tester). Ideal para estudiar inteligencia colectiva.
- 🔗 **GitHub:** https://github.com/OpenBMB/ChatDev

---

## 4. Memoria (evitar alucinaciones y no olvidar nada)

### Neo4j ⭐
Base de datos de grafos. Guarda el código como nodos y relaciones ("esta clase implementa esta interfaz"), para que el agente entienda la estructura sin tragarse todo el código.
- 🔗 **Sitio:** https://neo4j.com
- 🔗 **GitHub:** https://github.com/neo4j/neo4j

### Graphiti (de Zep) ⭐
Motor de "grafo temporal" sobre Neo4j. Actualiza el grafo de tu código de forma incremental y sabe cuándo cambió cada cosa. El pilar anti-alucinaciones.
- 🔗 **GitHub:** https://github.com/getzep/graphiti

### Qdrant ⭐
Base de datos vectorial (búsqueda por significado, no por palabras exactas). Complementa al grafo para encontrar "cosas parecidas".
- 🔗 **GitHub:** https://github.com/qdrant/qdrant

### Mem0 ⭐
Capa de "hechos personales": extrae y recuerda automáticamente preferencias y decisiones del usuario a lo largo del tiempo.
- 🔗 **GitHub:** https://github.com/mem0ai/mem0

### Cognee ⭐
Convierte documentos y repositorios en grafos de conocimiento, e incluye un servidor MCP. Integra con Neo4j, LangGraph y varios agentes.
- 🔗 **GitHub:** https://github.com/topoteretes/cognee

### LightRAG *(alternativa)*
GraphRAG ligero: capa de grafo + vectores para documentos estáticos.
- 🔗 **GitHub:** https://github.com/HKUDS/LightRAG

### Microsoft GraphRAG *(alternativa)*
El GraphRAG original de Microsoft, orientado a análisis de grandes corpus de texto.
- 🔗 **GitHub:** https://github.com/microsoft/graphrag

---

## 5. Inferencia Local (correr modelos en tu GPU de 16GB)

### Ollama ⭐
El "Docker de los LLMs": descarga y ejecuta modelos locales con un comando, exponiendo una API compatible. La forma más fácil de usar tu GPU.
- 🔗 **GitHub:** https://github.com/ollama/ollama

### vLLM ⭐ (escalado)
Motor de inferencia de alto rendimiento. Con PagedAttention sirve a muchos usuarios/agentes a la vez en una GPU (10-24x más throughput que Ollama). Para cuando la fábrica tenga muchos agentes concurrentes.
- 🔗 **GitHub:** https://github.com/vllm-project/vllm

### llama.cpp *(alternativa)*
El motor base (C++) que hay detrás de gran parte del ecosistema local. Más control, más flags, más complejo.
- 🔗 **GitHub:** https://github.com/ggml-org/llama.cpp

### LM Studio *(alternativa)*
Aplicación de escritorio con interfaz gráfica para descargar y probar modelos locales. Gratuita pero de código cerrado.
- 🔗 **Sitio:** https://lmstudio.ai

### Open WebUI *(alternativa)*
Interfaz web tipo ChatGPT para chatear con tus modelos locales de Ollama. Útil para probar rápido.
- 🔗 **GitHub:** https://github.com/open-webui/open-webui

---

## 6. Modelos Locales (open-weight)

### gpt-oss-20b ⭐
Modelo open-source de OpenAI, optimizado para caber en 16GB de VRAM (arquitectura MoE). El mejor para codificación local en 2026.
- 🔗 **GitHub:** https://github.com/openai/gpt-oss
- 🔗 **Modelo:** https://huggingface.co/openai/gpt-oss-20b

### Qwen 3.8 (27B)
Familia de modelos de Alibaba con razonamiento nativo, multimodal y gran rendimiento agéntico. Corre cuantizado en 16GB.
- 🔗 **GitHub:** https://github.com/QwenLM/Qwen3

### Gemma 4 (12B)
Modelo de Google compacto y multimodal, fuerte para una sola GPU.
- 🔗 **Sitio:** https://ai.google.dev/gemma

### Llama 3.2 (3B) ⭐ (router)
Modelo pequeño de Meta, ideal como "clasificador rápido" que decide qué tarea va a qué modelo (sin gastar tokens del grande).
- 🔗 **Sitio:** https://www.llama.com

### nomic-embed-text ⭐ (embeddings)
Modelo para convertir texto en vectores (embeddings), usado en la búsqueda semántica de Qdrant.
- 🔗 **Modelo:** https://huggingface.co/nomic-ai/nomic-embed-text-v1.5

### bge-m3 *(alternativa, embeddings)*
Alternativa multilingüe para embeddings.
- 🔗 **GitHub:** https://github.com/FlagOpen/FlagEmbedding

### Modelos Cloud (nube, vía API)

### Gemini (Google) ⭐
Familia de modelos de Google para razonamiento y arquitectura (serie Gemini 4 / Flash). Se usa para el PM y el Arquitecto de la fábrica. Configurable con `GEMINI_MODEL`.
- 🔗 **Sitio:** https://ai.google.dev

### DeepSeek V4 (OpenCode Go) ⭐
Modelos DeepSeek servidos a través del endpoint OpenAI-compatible de OpenCode Go (`deepseek-v4.1-flash`, `deepseek-v4-pro`). Se usan para código complejo, review y el Reclutador.
- 🔗 **OpenCode:** https://opencode.ai

### Claude Haiku 5.5 / GPT-6 Luna (routing barato)
Modelos de nube muy baratos (~$0.10/M) para clasificación, sumarios y extracción de hechos.

---

## 7. MCP (Model Context Protocol) — las "manos" del agente

### Model Context Protocol (MCP) ⭐
El estándar que permite a los agentes conectarse a herramientas y datos (archivos, git, bases de datos, web) de forma segura y uniforme.
- 🔗 **Sitio:** https://modelcontextprotocol.io
- 🔗 **GitHub:** https://github.com/modelcontextprotocol

### Bifrost ⭐ (gateway)
Gateway de IA open-source (Go) que centraliza LLMs, MCP y agentes en una sola API, con enrutamiento, caché semántico y control de acceso. Clave para escalar de forma segura.
- 🔗 **GitHub:** https://github.com/maximhq/bifrost
- 🔗 **Docs:** https://docs.getbifrost.ai

### Firecrawl MCP
Convierte cualquier página web en texto limpio (markdown) para que el agente la lea. Ideal para documentación e investigación.
- 🔗 **GitHub:** https://github.com/firecrawl/firecrawl

### GitHub MCP
Permite al agente operar con repositorios, issues y Pull Requests de GitHub directamente.
- 🔗 **GitHub:** https://github.com/github/github-mcp-server

### Supabase MCP *(alternativa)*
Da al agente acceso a bases de datos (inspeccionar esquemas, consultar).
- 🔗 **GitHub:** https://github.com/supabase-community/supabase-mcp

---

## 8. Optimización de Tokens (ahorrar hasta 90%)

### awesome-llm-token-optimization ⭐ (referencia)
Catálogo curado de estrategias, herramientas y papers para reducir costos de tokens. La "biblia" del ahorro.
- 🔗 **GitHub:** https://github.com/pleasedodisturb/awesome-llm-token-optimization

### GPTCache ⭐
Caché semántico: si ya respondiste una pregunta parecida, devuelve la respuesta guardada en vez de volver a pagar al modelo.
- 🔗 **GitHub:** https://github.com/zilliztech/GPTCache

### Redis ⭐
Almacén en memoria ultrarrápido donde vive el caché semántico y las colas del sistema.
- 🔗 **Sitio:** https://redis.io
- 🔗 **GitHub:** https://github.com/redis/redis

### LLMLingua ⭐
Compresor de prompts de Microsoft: elimina palabras irrelevantes antes de enviar el texto al modelo, reduciendo el tamaño hasta 20x con pérdida mínima.
- 🔗 **GitHub:** https://github.com/microsoft/LLMLingua

### SuperCompress *(alternativa)*
Compresor consciente de la pregunta (mantiene solo lo que responde a tu consulta), con MCP para agentes de código.
- 🔗 **Sitio:** https://www.supercompress.dev

---

## 9. Indexación de Código

### Tree-sitter ⭐
Analizador sintáctico que convierte tu código en un árbol estructurado (clases, métodos, relaciones). Es lo que alimenta el grafo de Neo4j/Graphiti.
- 🔗 **GitHub:** https://github.com/tree-sitter/tree-sitter

---

## 10. Evaluación y Observabilidad (medir calidad y costos)

### Langfuse ⭐
Plataforma open-source que registra cada llamada al modelo (tokens, costo, latencia) y permite evaluar respuestas con "jueces" de IA. Sin esto, optimizar es adivinar.
- 🔗 **GitHub:** https://github.com/langfuse/langfuse

### DeepEval
Framework para evaluar respuestas de LLM con métricas (alucinación, relevancia, etc.).
- 🔗 **GitHub:** https://github.com/confident-ai/deepeval

### Ragas
Framework especializado en evaluar la calidad de sistemas RAG.
- 🔗 **GitHub:** https://github.com/explodinggradients/ragas

### Promptfoo
Framework para "red-team" y pruebas de seguridad/regresión de prompts.
- 🔗 **GitHub:** https://github.com/promptfoo/promptfoo

### Braintrust *(alternativa)*
Plataforma comercial (con tier gratuito) centrada en evaluación iterativa con experimentos.
- 🔗 **GitHub:** https://github.com/braintrustdata/braintrust

### MLflow *(alternativa)*
Plataforma de machine learning que también sirve para trazabilidad y evaluación de LLMs.
- 🔗 **GitHub:** https://github.com/mlflow/mlflow

---

## 11. Fine-Tuning (personalizar modelos)

### Unsloth ⭐
Herramienta que acelera el "fine-tuning" (entrenar un modelo pequeño con tus propios datos) usando mucha menos memoria y tiempo.
- 🔗 **GitHub:** https://github.com/unslothai/unsloth

---

## 12. Infraestructura y Despliegue

### Docker / Docker Compose
Empaqueta cada servicio (bases de datos, memoria, agentes) en contenedores aislados y reproducibles. El "andamiaje" que levanta todo con un comando.
- 🔗 **Sitio:** https://www.docker.com

---

## 13. Registro de Herramientas Integrables — Repos Piloto

Repos que el **Tool Registry** integra bajo demanda (activables/desactivables por proyecto). Son los primeros del catálogo.

### ECC (Everything Claude Code) — skill ⭐
Framework de "operación" para agentes de código: skills, reglas, hooks, memoria y seguridad. Analiza tu repo y genera prácticas de trabajo reutilizables para que el agente trabaje de forma disciplinada.
- 🔗 **GitHub (organización):** https://github.com/ECC-Tools
- 🔗 **Repositorio:** https://github.com/affaan-m/ECC

### LLM Council — app
Consejo de varios LLMs: envía tu pregunta a múltiples modelos, se revisan entre sí de forma anónima, y un "presidente" produce la respuesta final. Ideal para decisiones difíciles y evaluación de respuestas.
- 🔗 **GitHub:** https://github.com/karpathy/llm-council

### llmfit — tool
Detecta tu hardware (CPU, RAM, GPU, VRAM) y recomienda qué modelos locales puedes correr y con qué cuantización. Perfecto para elegir el modelo correcto en tu GPU de 16GB.
- 🔗 **GitHub:** https://github.com/AlexsJones/llmfit
- 🔗 **Sitio:** https://www.llmfit.org

### WebLLM — sdk
Motor de inferencia que ejecuta LLMs directamente en el navegador usando WebGPU. Para construir aplicaciones web con IA 100% local (privada y sin servidor).
- 🔗 **GitHub:** https://github.com/mlc-ai/web-llm
- 🔗 **Docs:** https://webllm.mlc.ai/docs

---

*Fin del catálogo. Los elementos marcados con ⭐ son la opción recomendada (la "decisión final") en su categoría. Las marcadas como "alternativa" son opciones secundarias si la principal no se ajusta a una necesidad concreta.*
