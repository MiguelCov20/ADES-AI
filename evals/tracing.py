"""Trazabilidad de llamadas LLM (Langfuse v5 SDK, con fallback a JSONL) - Fase 8.

Cada llamada LLM de la pasarela (`core.llm_gateway`) se registra como una
observación `generation` en Langfuse con uso de tokens y costo reales. Si
Langfuse no está configurado o no responde, la traza queda en
`.ades/_global/traces.jsonl` (fallback local).

Nota: la versión anterior usaba `Langfuse().trace(...)` (API v2), que no existe
en el SDK instalado (5.x); fallaba en silencio y nada llegaba a Langfuse.
"""
import json
import os
import threading
import time

from core.config import global_state_dir

_client = None
_client_lock = threading.Lock()
_disabled = False


def traces_file():
    return global_state_dir() / "traces.jsonl"


def _langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def get_client():
    """Cliente Langfuse singleton (None si no está configurado)."""
    global _client, _disabled
    if _disabled or not _langfuse_configured():
        return None
    with _client_lock:
        if _client is None:
            try:
                from langfuse import Langfuse
                _client = Langfuse(
                    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                    host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
                )
            except Exception:
                _disabled = True
                return None
    return _client


def trace_call(agent: str, model: str, input_text: str, output_text: str,
               tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0,
               metadata: dict | None = None, session_id: str | None = None) -> dict:
    """Registra una llamada LLM (Langfuse + JSONL). Devuelve el registro."""
    record = {
        "ts": round(time.time(), 3), "agent": agent, "model": model,
        "input": input_text[:500], "output": output_text[:500],
        "tokens_in": tokens_in, "tokens_out": tokens_out, "cost": round(cost, 6),
        "metadata": metadata or {}, "langfuse": False,
    }
    lf = get_client()
    if lf is not None:
        try:
            from langfuse import propagate_attributes
            with propagate_attributes(session_id=session_id, trace_name=f"ades:{agent}",
                                      tags=[agent, model]):
                gen = lf.start_observation(
                    name=agent, as_type="generation", model=model,
                    input=input_text[:20000], output=output_text[:20000],
                    usage_details={"input": int(tokens_in), "output": int(tokens_out)},
                    cost_details={"total": float(cost)}, metadata=metadata or {},
                )
                gen.end()
            record["langfuse"] = True
        except Exception as e:  # noqa: BLE001
            record["langfuse_error"] = f"{type(e).__name__}: {e}"[:200]
    with open(traces_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def flush() -> None:
    lf = get_client()
    if lf is not None:
        try:
            lf.flush()
        except Exception:
            pass


def load_traces() -> list[dict]:
    p = traces_file()
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    traces = load_traces()
    print(f"{len(traces)} trazas registradas en {traces_file()}")
    for t in traces[-5:]:
        print(f"  {t['agent']}/{t['model']}: {t['tokens_in']}+{t['tokens_out']} tok, "
              f"${t['cost']:.6f} langfuse={t.get('langfuse')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
