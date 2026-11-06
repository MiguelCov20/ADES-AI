"""Fábrica de LLMs para los agentes (ADES-AI, Fase 3).

Crea el LLM de LangChain adecuado para cada "cerebro":
  - gemini   -> ChatGoogleGenerativeAI (nube, modelo configurable con GEMINI_MODEL)
  - opencode -> ChatOpenAI apuntando a OpenCode Go (DeepSeek V4, requiere header)
  - ollama   -> ChatOpenAI apuntando al endpoint OpenAI-compatible de Ollama (local)

Uso:
    from agents.llm import get_llm
    llm = get_llm("ollama", "gpt-oss:20b")
"""
import os
import uuid

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

# Cargar variables de entorno (.env) para que la fábrica sea autocontenida.
load_dotenv()

OPENCODE_BASE = "https://opencode.ai/inference/go/openai/v1"
OLLAMA_BASE = "http://localhost:11434/v1"


def get_llm(provider: str, model: str | None = None, temperature: float = 0.2):
    """Devuelve el LLM para un provider dado. `model="auto"` usa el default del provider."""
    provider = provider.lower()

    if provider == "gemini":
        m = os.getenv("GEMINI_MODEL", "gemini-flash-latest") if model in (None, "auto") else model
        return ChatGoogleGenerativeAI(
            model=m, temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )

    if provider == "opencode":
        m = "deepseek-v4-pro" if model in (None, "auto") else model
        return ChatOpenAI(
            model=m, temperature=temperature,
            api_key=os.getenv("OPENCODE_API_KEY"),
            base_url=OPENCODE_BASE,
            default_headers={
                "x-opencode-session": f"ades-{uuid.uuid4().hex}",
                "User-Agent": "ades-ai/1.0",
            },
        )

    if provider == "ollama":
        m = "gpt-oss:20b" if model in (None, "auto") else model
        # Acotar num_ctx para que el modelo + KV cache quepan en 16 GB de VRAM
        # (Fase 10: sin esto, Ollama carga la ventana completa de 128K y hace
        # offload parcial a CPU).
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        return ChatOpenAI(
            model=m, temperature=temperature,
            api_key="ollama",
            base_url=OLLAMA_BASE,
            extra_body={"num_ctx": num_ctx},
        )

    raise ValueError(f"Provider no soportado: {provider}")


def get_llm_for_agent(agent: dict):
    """Devuelve el LLM para un agente del roster (dict con 'llm')."""
    cfg = agent.get("llm", {})
    return get_llm(cfg.get("provider", "ollama"), cfg.get("model", "auto"))
