"""Trazabilidad de llamadas LLM (Langfuse, con fallback a JSONL) - ADES-AI, Fase 8.

Registra cada llamada LLM (agente, modelo, tokens, costo) para observabilidad.
Si Langfuse está configurado (LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY +
LANGFUSE_HOST), envía las trazas allí; si no, las guarda en `evals/traces.jsonl`
(fallback local, siempre disponible).
"""
import json
import os
import time
from pathlib import Path

TRACES_FILE = Path(__file__).resolve().parent / "traces.jsonl"


def _langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def trace_call(agent: str, model: str, input_text: str, output_text: str,
               tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0) -> dict:
    """Registra una traza de una llamada LLM y la devuelve."""
    record = {
        "ts": round(time.time(), 3),
        "agent": agent,
        "model": model,
        "input": input_text[:500],
        "output": output_text[:500],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": round(cost, 6),
    }
    with open(TRACES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if _langfuse_configured():
        try:
            from langfuse import Langfuse
            lf = Langfuse()
            trace = lf.trace(name=f"{agent}:{model}")
            trace.generation(name=agent, model=model, input=input_text,
                             output=output_text,
                             usage={"input": tokens_in, "output": tokens_out})
            lf.flush()
        except Exception:
            pass  # Langfuse no disponible; la traza queda en JSONL
    return record


def load_traces() -> list[dict]:
    if not TRACES_FILE.exists():
        return []
    return [json.loads(l) for l in TRACES_FILE.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def main() -> int:
    traces = load_traces()
    print(f"{len(traces)} trazas registradas en {TRACES_FILE.name}")
    for t in traces[-5:]:
        print(f"  {t['agent']}/{t['model']}: {t['tokens_in']}+{t['tokens_out']} tok, "
              f"${t['cost']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
