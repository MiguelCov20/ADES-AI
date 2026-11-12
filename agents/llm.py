"""Fábrica de LLMs para los agentes (ADES-AI, Fase 3 / 10).

Crea el LLM de LangChain adecuado para cada "cerebro":
  - gemini   -> ChatGoogleGenerativeAI (nube, modelo configurable con GEMINI_MODEL)
  - opencode -> ChatOpenAI apuntando a OpenCode Go (DeepSeek V4, requiere header)
  - ollama   -> ChatOpenAI apuntando al endpoint OpenAI-compatible de Ollama (local)

Correcciones:
  - `session_id` estable por ejecución: el header `x-opencode-session` ya no se
    regenera en cada llamada (antes el prompt caching de OpenCode nunca acertaba).
  - Timeout y reintentos acotados: un 503 de Gemini ya no cuelga la fábrica; la
    pasarela (`core.llm_gateway`) hace fallback en cascada al siguiente modelo.
  - `effort` (low/medium/high) -> reasoning effort / thinking budget (#20).

Uso normal: NO llames a esto directamente, usa `core.llm_gateway.chat(...)`.
"""
import os
import uuid

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from core.config import LLM_TIMEOUT, OLLAMA_URL

OPENCODE_BASE = "https://opencode.ai/inference/go/openai/v1"
OLLAMA_BASE = OLLAMA_URL + "/v1"

GEMINI_THINKING = {"low": 0, "medium": 1024, "high": 8192}
# Modelos locales que aceptan `reasoning_effort` (gpt-oss)
EFFORT_MODELS = ("gpt-oss",)


def default_model(provider: str) -> str:
    return {
        "gemini": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        "opencode": "deepseek-v4-pro",
        "ollama": "gpt-oss:20b",
    }[provider]


BIFROST_URL = os.getenv("BIFROST_URL", "http://localhost:8080/v1")
BIFROST_PROVIDER = {"gemini": "gemini", "opencode": "opencode-go", "ollama": "ollama"}
CTX_VARIANT_SUFFIX = os.getenv("ADES_OLLAMA_CTX_SUFFIX", "-ctx16k")


def gateway_enabled() -> bool:
    """¿Enrutar por el gateway Bifrost? (ADES_GATEWAY=bifrost en .env)."""
    return os.getenv("ADES_GATEWAY", "direct").lower() == "bifrost"


def ollama_variant(model: str) -> str:
    """Variante con num_ctx fijo (environment/setup_ollama_ctx.ps1): por el gateway no se
    puede enviar `num_ctx` y el servidor usa 65536 por defecto (dispara la VRAM)."""
    return model if model.endswith(CTX_VARIANT_SUFFIX) else model + CTX_VARIANT_SUFFIX


def _via_bifrost(provider: str, m: str, temperature: float, session_id: str | None,
                 effort: str | None, timeout: float, max_retries: int):
    vk = os.getenv("BIFROST_VK_LOCAL" if provider == "ollama" else "BIFROST_VK_FACTORY", "")
    model = ollama_variant(m) if provider == "ollama" else m
    headers = {"x-bf-vk": vk, "User-Agent": "ades-ai/1.0"}
    if provider == "opencode":
        headers["x-opencode-session"] = session_id or f"ades-{uuid.uuid4().hex}"
    kwargs = {}
    if effort and provider == "ollama" and any(m.startswith(p) for p in EFFORT_MODELS):
        kwargs["reasoning_effort"] = effort
    return ChatOpenAI(model=f"{BIFROST_PROVIDER[provider]}/{model}", temperature=temperature,
                      api_key=vk or "bifrost", base_url=BIFROST_URL,
                      timeout=max(timeout, 600) if provider == "ollama" else timeout,
                      max_retries=max_retries, default_headers=headers, **kwargs)


def get_llm(provider: str, model: str | None = None, temperature: float = 0.2,
            session_id: str | None = None, effort: str | None = None,
            timeout: float | None = None, max_retries: int = 1):
    """Devuelve el LLM para un provider dado. `model="auto"` usa el default del provider.

    Con ADES_GATEWAY=bifrost todas las llamadas pasan por el gateway Bifrost (auth por
    virtual key, scope por proveedor/modelo, concurrencia acotada hacia Ollama).
    """
    provider = provider.lower()
    m = default_model(provider) if model in (None, "auto") else model
    timeout = timeout or LLM_TIMEOUT
    if gateway_enabled():
        return _via_bifrost(provider, m, temperature, session_id, effort, timeout, max_retries)

    if provider == "gemini":
        kwargs = {}
        if effort in GEMINI_THINKING and "lite" not in m:
            kwargs["thinking_budget"] = GEMINI_THINKING[effort]
        return ChatGoogleGenerativeAI(
            model=m, temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            timeout=timeout, max_retries=max_retries, **kwargs,
        )

    if provider == "opencode":
        return ChatOpenAI(
            model=m, temperature=temperature,
            api_key=os.getenv("OPENCODE_API_KEY"),
            base_url=OPENCODE_BASE,
            timeout=timeout, max_retries=max_retries,
            default_headers={
                "x-opencode-session": session_id or f"ades-{uuid.uuid4().hex}",
                "User-Agent": "ades-ai/1.0",
            },
        )

    if provider == "ollama":
        # Acotar num_ctx para que el modelo + KV cache quepan en 16 GB de VRAM.
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        kwargs = {}
        if effort and any(m.startswith(p) for p in EFFORT_MODELS):
            kwargs["reasoning_effort"] = effort
        return ChatOpenAI(
            model=m, temperature=temperature,
            api_key="ollama",
            base_url=OLLAMA_BASE,
            timeout=max(timeout, 600), max_retries=max_retries,
            extra_body={"num_ctx": num_ctx},
            **kwargs,
        )

    raise ValueError(f"Provider no soportado: {provider}")


def get_llm_for_agent(agent: dict, **kw):
    """Devuelve el LLM para un agente del roster (dict con 'llm')."""
    cfg = agent.get("llm", {})
    return get_llm(cfg.get("provider", "ollama"), cfg.get("model", "auto"), **kw)
