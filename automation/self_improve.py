"""Ecosistema automejorable (feature #32).

Para un agente:
  1. Recoge fallos recientes: llamadas con `ok=0` en `core.metrics_store`, trazas
     del agente con error en metadata y feedback de QA en
     `state_dir(project)/runs/*.json` (si existen).
  2. Pide al LLM una versión mejorada de su prompt actual (`agents.prompts.get_prompt`).
  3. Evalúa la propuesta con el regression detector (#19,
     `evals.regression.check_prompt_change`, importado de forma perezosa; se puede
     inyectar otro con `evaluator=`).
  4. Solo la aplica (`agents.prompts.set_prompt`) si NO hay regresión y además
     mejora; si no, la descarta. Todo intento queda en
     `global_state_dir()/self_improve.jsonl`.
"""
import json
import re
import time
from pathlib import Path

from core.config import global_state_dir, state_dir

SYSTEM = (
    "Eres el optimizador de prompts de ADES-AI. Recibes el prompt de sistema actual de un "
    "agente y una lista de fallos recientes. Propón una versión MEJORADA del prompt que "
    "evite esos fallos sin perder ninguna instrucción existente (formato de salida, "
    "restricciones, idioma). Sé conciso. Devuelve SOLO el nuevo prompt entre las etiquetas "
    "<prompt> y </prompt>, y después una línea 'MOTIVO: ...' con el cambio principal."
)


def log_path() -> Path:
    return global_state_dir() / "self_improve.jsonl"


def _log(entry: dict) -> dict:
    entry = {"ts": time.time(), **entry}
    with open(log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history() -> list[dict]:
    p = log_path()
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _runs_feedback(agent: str, project: str | None, limit: int) -> list[dict]:
    d = state_dir(project) / "runs"
    if not d.exists():
        return []
    out = []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[: limit * 3]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for rec in (data if isinstance(data, list) else [data]):
            if not isinstance(rec, dict):
                continue
            fb = rec.get("qa_feedback") or rec.get("feedback") or ""
            verdict = str(rec.get("veredicto") or rec.get("verdict") or "")
            failed = (rec.get("passed") is False or "FAIL" in verdict.upper()
                      or "VEREDICTO: FAIL" in str(fb).upper())
            rec_agent = rec.get("agent") or rec.get("agente")
            if fb and failed and rec_agent in (None, agent, "qa"):
                out.append({"source": "runs", "file": f.name,
                            "task": str(rec.get("task") or rec.get("requerimiento") or "")[:200],
                            "error": str(fb)[:600]})
    return out[:limit]


def collect_failures(agent: str, project: str | None = None, limit: int = 10) -> list[dict]:
    """Fallos recientes del agente (métricas ok=0, trazas con error, feedback de QA)."""
    from core import metrics_store
    out = []
    sql = "SELECT task, model, error, ts FROM calls WHERE agent = ? AND ok = 0"
    params: list = [agent]
    if project:
        sql += " AND project = ?"
        params.append(project)
    for r in metrics_store.query(sql + " ORDER BY ts DESC LIMIT ?", (*params, limit)):
        out.append({"source": "metrics", "task": r["task"] or "", "model": r["model"],
                    "error": r["error"] or ""})
    try:
        from evals import tracing
        for t in reversed(tracing.load_traces()):
            md = t.get("metadata") or {}
            if t.get("agent") == agent and (md.get("error") or md.get("ok") is False):
                out.append({"source": "traces", "task": (t.get("input") or "")[-200:],
                            "error": str(md.get("error") or t.get("output", ""))[:400]})
                if len(out) >= limit * 2:
                    break
    except Exception:  # noqa: BLE001
        pass
    out += _runs_feedback(agent, project, limit)
    return out[: limit * 2]


def _extract_prompt(text: str) -> tuple[str, str]:
    m = re.search(r"<prompt>\s*(.*?)\s*</prompt>", text, re.S | re.I)
    prompt = m.group(1).strip() if m else ""
    r = re.search(r"MOTIVO:\s*(.+)", text)
    return prompt, (r.group(1).strip()[:300] if r else "")


def propose(agent: str, failures: list[dict], *, provider: str | None = "ollama",
            model: str | None = "gpt-oss:20b", project: str | None = None) -> dict:
    """Pide al LLM un prompt mejorado. Devuelve {prompt, motivo, raw}."""
    from agents.prompts import get_prompt
    from core.llm_gateway import chat
    current = get_prompt(agent)
    fallos = "\n".join(f"- [{f['source']}] tarea: {f.get('task', '')[:150]} | error: "
                       f"{f.get('error', '')[:300]}" for f in failures)
    user = (f"Agente: {agent}\n\nPROMPT ACTUAL:\n<prompt>\n{current}\n</prompt>\n\n"
            f"FALLOS RECIENTES:\n{fallos}\n\nDevuelve el prompt mejorado.")
    res = chat("self_improve", SYSTEM, user, provider=provider, model=model, project=project,
               use_cache=False)
    prompt, motivo = _extract_prompt(res.text)
    return {"prompt": prompt, "motivo": motivo, "raw": res.text, "current": current}


def _default_evaluator(agent: str, new_prompt: str) -> dict:
    from evals.regression import check_prompt_change  # perezoso: lo crea otro módulo (#19)
    return check_prompt_change(agent, new_prompt)


def _improves(ev: dict) -> tuple[bool, float | None]:
    """¿La evaluación indica mejora? Acepta varias formas de resultado del detector."""
    if ev.get("improved") is not None:
        delta = ev.get("delta")
        return bool(ev["improved"]), (float(delta) if delta is not None else None)
    if ev.get("delta") is not None:
        d = float(ev["delta"])
        return d > 0, d
    # Forma de `evals.regression.compare`: pass_rate_*/score_* de baseline y candidato.
    if ev.get("pass_rate_baseline") is not None or ev.get("score_baseline") is not None:
        pb, pc = ev.get("pass_rate_baseline"), ev.get("pass_rate_candidate")
        sb, sc = ev.get("score_baseline"), ev.get("score_candidate")
        dp = (pc - pb) if pb is not None and pc is not None else 0.0
        ds = (sc - sb) if sb is not None and sc is not None else 0.0
        return (dp > 0 or (dp >= 0 and ds > 0)), round(ds if ds else dp, 4)
    old = ev.get("old_score", ev.get("baseline_score", ev.get("score_old")))
    new = ev.get("new_score", ev.get("candidate_score", ev.get("score_new", ev.get("score"))))
    if old is not None and new is not None:
        return float(new) > float(old), float(new) - float(old)
    return False, None


def improve(agent: str, project: str | None = None, *, evaluator=None, apply: bool = True,
            min_failures: int = 1, provider: str | None = "ollama",
            model: str | None = "gpt-oss:20b", proposer=None) -> dict:
    """Ciclo completo de automejora para `agent`. Devuelve el registro del intento.

    `evaluator(agent, new_prompt) -> {"regression": bool, "improved"|"delta"|scores...}`.
    `proposer(agent, failures) -> {"prompt", "motivo"}` (por defecto, `propose` con el LLM).
    """
    from agents.prompts import DEFAULTS, get_prompt, set_prompt
    if agent not in DEFAULTS:
        from agents.prompts import history as phist
        if not phist(agent):
            raise KeyError(f"Agente sin prompt registrado: {agent}")
    base = {"agent": agent, "project": project}
    failures = collect_failures(agent, project)
    if len(failures) < min_failures:
        return _log({**base, "status": "omitido", "reason": "sin fallos recientes",
                     "failures": 0})
    current = get_prompt(agent)
    try:
        prop = (proposer or (lambda a, f: propose(a, f, provider=provider, model=model,
                                                  project=project)))(agent, failures)
    except Exception as e:  # noqa: BLE001
        return _log({**base, "status": "error", "reason": f"propuesta: {type(e).__name__}: {e}"[:300],
                     "failures": len(failures)})
    new = (prop.get("prompt") or "").strip()
    if not new or new == current.strip():
        return _log({**base, "status": "descartado", "reason": "propuesta vacía o idéntica",
                     "failures": len(failures)})
    if len(new) < 0.4 * len(current):
        return _log({**base, "status": "descartado", "failures": len(failures),
                     "reason": "propuesta demasiado corta (probable pérdida de instrucciones)",
                     "candidate": new[:2000]})
    try:
        ev = (evaluator or _default_evaluator)(agent, new)
    except ImportError as e:
        return _log({**base, "status": "error", "failures": len(failures), "candidate": new[:2000],
                     "reason": f"regression detector no disponible: {e}"[:300]})
    except Exception as e:  # noqa: BLE001
        return _log({**base, "status": "error", "failures": len(failures), "candidate": new[:2000],
                     "reason": f"evaluación: {type(e).__name__}: {e}"[:300]})
    regression = bool(ev.get("regression", True))
    better, delta = _improves(ev)
    entry = {**base, "failures": len(failures), "motivo": prop.get("motivo", ""),
             "candidate": new[:4000], "regression": regression, "improved": better,
             "delta": delta, "evaluation": {k: v for k, v in ev.items()
                                            if isinstance(v, (int, float, str, bool, type(None)))}}
    if regression or not better:
        entry.update(status="descartado",
                     reason="regresión detectada" if regression else "no mejora")
        return _log(entry)
    if not apply:
        entry.update(status="aprobado_sin_aplicar", reason="apply=False")
        return _log(entry)
    version = set_prompt(agent, new, reason=f"self_improve: {prop.get('motivo', '')}"[:300],
                         score=delta)
    entry.update(status="aplicado", version=version, reason="sin regresión y mejora")
    return _log(entry)


def main(argv: list[str] | None = None) -> int:
    """`ades improve <agente> [--project P] [--dry-run]` | `ades improve --history`."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Ecosistema automejorable (#32)")
    ap.add_argument("agent", nargs="?", default="developer")
    ap.add_argument("--project", default=None)
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--dry-run", action="store_true", help="evalúa pero no aplica")
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.history:
        r = history()[-20:]
    else:
        r = improve(a.agent, a.project, apply=not a.dry_run, model=a.model)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
