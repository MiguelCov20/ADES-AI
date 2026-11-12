"""Pasarela LLM unificada de ADES-AI.

Toda llamada a un modelo de la fábrica pasa por `chat()`, que aplica en orden:

  1. Token Budget Governor (#10): nivel permitido según el gasto del proyecto.
  2. Brain Selector (#20): si no se fija modelo, el router elige modelo + effort.
  3. Caché semántico (Fase 7): si hay una respuesta casi idéntica, no se paga.
  4. Prompt caching: mensajes con lo estático primero + sesión estable por run.
  5. GPU Memory Manager (#29): libera VRAM antes de usar un modelo local grande.
  6. Fallback en cascada (#21): si un modelo falla (503/429/timeout), escala al
     siguiente de la cadena en vez de colgarse.
  7. Tracing (Langfuse) + métricas persistentes (SQLite) con tokens reales.

Para tests: `set_mock(fn)` sustituye la llamada real por `fn(provider, model, messages)`.
"""
import concurrent.futures
import hashlib
import time
import uuid
from dataclasses import asdict, dataclass

from cache.prompt_cache import build_messages
from cache.token_metrics import COST_PER_1M
from core import budget, gpu_manager, metrics_store
from core.config import DEFAULT_PROJECT, LLM_TIMEOUT
from evals import tracing

_mock = None


def set_mock(fn) -> None:
    """Sustituye las llamadas reales por `fn(provider, model, messages) -> (texto, tin, tout)`."""
    global _mock
    _mock = fn


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cache_hit: bool = False
    fallback_from: str = ""
    latency: float = 0.0
    effort: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AllModelsFailed(RuntimeError):
    pass


def cost_of(model: str, tin: int, tout: int) -> float:
    c = COST_PER_1M.get(model)
    if c is None:
        c = {"input": 0.5, "output": 2.0} if not _is_local_name(model) else {"input": 0, "output": 0}
    return (tin * c["input"] + tout * c["output"]) / 1_000_000


def _is_local_name(model: str) -> bool:
    return ":" in model  # convención Ollama (gpt-oss:20b, llama3.2:3b, ...)


CIRCUIT_WINDOW_S = 300
CIRCUIT_FAILS = 2


def circuit_open(provider: str, model: str) -> bool:
    """Circuit breaker: ≥2 fallos (y ningún éxito) del modelo en los últimos 5 min -> saltarlo."""
    try:
        r = metrics_store.query(
            "SELECT SUM(1-ok) AS fails, SUM(ok) AS oks FROM calls WHERE provider=? AND model=? "
            "AND ts > ? AND cache_hit = 0", (provider, model, time.time() - CIRCUIT_WINDOW_S))[0]
        return (r["fails"] or 0) >= CIRCUIT_FAILS and not (r["oks"] or 0)
    except Exception:
        return False


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _invoke(provider: str, model: str, messages: list, session_id: str, effort: str,
            temperature: float, max_tokens: int | None = None, json_mode: bool = False):
    if _mock is not None:
        return _mock(provider, model, messages)
    from agents.llm import get_llm
    from langchain_openai import ChatOpenAI
    llm = get_llm(provider, model, temperature=temperature, session_id=session_id,
                  effort=effort)
    kw = {}
    if max_tokens:
        kw = {"max_tokens": max_tokens} if isinstance(llm, ChatOpenAI) else {
            "max_output_tokens": max_tokens}
    if json_mode and isinstance(llm, ChatOpenAI):
        # Salida JSON forzada por gramática (llama-server / Ollama / OpenAI-compatibles)
        kw["response_format"] = {"type": "json_object"}
    if provider == "ollama":
        resp = llm.invoke(messages, **kw)
    else:
        # Timeout DURO para la nube: el timeout del cliente de Gemini no siempre se
        # respeta (se observó una llamada colgada >6 min). Si vence, se pasa al
        # siguiente modelo de la cascada; el hilo huérfano se abandona.
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(lambda: llm.invoke(messages, **kw))
        try:
            resp = fut.result(timeout=LLM_TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"{provider}:{model} superó {LLM_TIMEOUT:.0f}s")
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    text = resp.content if isinstance(resp.content, str) else "".join(
        p.get("text", "") if isinstance(p, dict) else str(p) for p in resp.content)
    usage = getattr(resp, "usage_metadata", None) or {}
    tin = usage.get("input_tokens") or estimate_tokens("".join(str(m.content) for m in messages))
    tout = usage.get("output_tokens") or estimate_tokens(text)
    return text, int(tin), int(tout)


def chat(agent: str, system: str, user: str, *, context: str = "",
         project: str | None = None, run_id: str | None = None,
         provider: str | None = None, model: str | None = None,
         effort: str | None = None, use_cache: bool = True, temperature: float = 0.2,
         route: bool = False, max_tokens: int | None = None,
         json_mode: bool = False) -> LLMResult:
    """Llama al modelo adecuado para `agent` con todas las optimizaciones.

    Si `route=True` o no se da provider, el Brain Selector decide modelo/effort.
    """
    from agents.router import cascade_for, route_task

    project = project or DEFAULT_PROJECT
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    tier = budget.status(project)["tier"]

    if route or not provider:
        d = route_task(user[:1500], use_llm=_mock is None, tier=tier)
        provider, model, effort = d["provider"], d["model"], effort or d["effort"]
    model = model or {"gemini": None, "opencode": "deepseek-v4-pro",
                      "ollama": "gpt-oss:20b"}.get(provider)
    if provider == "gemini" and not model:
        from agents.llm import default_model
        model = default_model("gemini")
    chain = cascade_for(provider, model)

    messages = build_messages(system, context, user)
    # Caché semántico: el sistema y el CONTEXTO deben coincidir exactamente (van en el
    # namespace como hash) y la similitud se mide solo sobre la pregunta del usuario.
    # Antes se embebía contexto+pregunta: con un contexto largo (RepoMap) el embedding
    # lo dominaba el contexto (y nomic truncaba la pregunta), y dos tareas distintas
    # sobre el mismo paquete recibían la misma respuesta (bug detectado por el KPI 1).
    cache_prompt = user
    cache = None
    if use_cache and _mock is None:
        try:
            from cache.semantic_cache import SemanticCache
            ctx_hash = hashlib.sha256(f"{system}\n\x00{context}".encode()).hexdigest()[:16]
            ns = f"{project}:{agent}:{ctx_hash}"
            cache = SemanticCache(namespace=ns)
            hit, score, _ = cache.lookup_scored(cache_prompt)
            if hit is not None:
                res = LLMResult(text=hit, provider="cache", model=model, cache_hit=True,
                                effort=effort or "")
                metrics_store.record(project, run_id, user[:80], agent, "cache", model,
                                     0, 0, 0.0, cache_hit=True)
                tracing.trace_call(agent, f"cache({model})", cache_prompt, hit, 0, 0, 0.0,
                                   metadata={"cache_hit": True, "score": round(score, 4),
                                             "project": project}, session_id=run_id)
                return res
        except Exception:
            cache = None  # Redis/Ollama caídos: seguimos sin caché

    errors = []
    first = f"{provider}:{model}"
    for prov, mod in chain:
        if not budget.allowed(prov, mod, tier):
            errors.append(f"{prov}:{mod} bloqueado por presupuesto ({tier})")
            continue
        if _mock is None and prov != "ollama" and circuit_open(prov, mod) and (prov, mod) != chain[-1]:
            errors.append(f"{prov}:{mod} circuito abierto (fallos recientes)")
            continue
        if prov == "ollama" and _mock is None:
            from agents.llm import gateway_enabled, ollama_variant
            from core import local_serving
            if local_serving.enabled() and local_serving.config_for(mod):
                try:
                    local_serving.ensure(mod)  # llama-server con batching continuo (KPI 5)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"llama-server:{mod} -> {type(e).__name__}: {e}"[:200])
                    continue
            else:
                gpu_manager.ensure_fits(ollama_variant(mod) if gateway_enabled() else mod)
        t0 = time.time()
        try:
            text, tin, tout = _invoke(prov, mod, messages, run_id, effort or "", temperature,
                                      max_tokens, json_mode)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            errors.append(f"{prov}:{mod} -> {err}")
            metrics_store.record(project, run_id, user[:80], agent, prov, mod, 0, 0, 0.0,
                                 latency=time.time() - t0, ok=False, error=err,
                                 effort=effort or "")
            continue
        latency = time.time() - t0
        cost = 0.0 if prov == "ollama" else cost_of(mod, tin, tout)
        fb = "" if f"{prov}:{mod}" == first else first
        res = LLMResult(text=text, provider=prov, model=mod, tokens_in=tin, tokens_out=tout,
                        cost=cost, fallback_from=fb, latency=latency, effort=effort or "")
        metrics_store.record(project, run_id, user[:80], agent, prov, mod, tin, tout, cost,
                             latency=latency, effort=effort or "", fallback_from=fb)
        traced_input = (context + "\n\n" + user) if context else user
        tracing.trace_call(agent, mod, traced_input[-20000:], text, tin, tout, cost,
                           metadata={"provider": prov, "project": project, "effort": effort,
                                     "fallback_from": fb}, session_id=run_id)
        if cache is not None and text.strip():
            try:
                cache.add(cache_prompt, text)
            except Exception:
                pass
        return res
    raise AllModelsFailed(" | ".join(errors))
