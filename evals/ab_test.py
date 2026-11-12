"""A/B testing de modelos (feature #22).

Corre el mismo conjunto de tareas con dos (provider, model), puntúa cada salida
y reporta el ganador con win-rate, costo y latencia.

Puntuación por tarea:
  - Tarea de benchmark (tiene `hidden_tests`): tests ocultos en el sandbox Docker
    (`evals.benchmark.evaluate_solution`). Gana quien pasa; si ambos o ninguno
    pasan, gana quien falla menos tests.
  - Caso abierto (`question` + `criteria`): juez LLM (por defecto
    `evals.judge.evaluate`, que respeta ADES_JUDGE=council). Gana el mayor score.

Ganador global: mayor win-rate (empates cuentan 0.5). Si el win-rate empata, se
desempata por costo y después por latencia (y se indica en `decided_by`).
"""
import json
import time

from core.config import global_state_dir


def _parse_model(m) -> tuple[str, str]:
    if isinstance(m, str):
        prov, _, mod = m.partition(":")
        if not mod:
            raise ValueError(f"Modelo '{m}' debe tener formato 'provider:model'")
        return prov, mod
    return tuple(m)


def _resolve(task_set) -> list[dict]:
    from evals.benchmark import load_tasks
    out = []
    for t in task_set:
        out.extend(load_tasks([t]) if isinstance(t, str) else [t])
    return out


def _run_one(task: dict, provider: str, model: str, *, agent: str, system: str | None,
             judge, project) -> dict:
    from agents.prompts import get_prompt
    from core.llm_gateway import chat
    from evals.benchmark import evaluate_solution, task_prompt

    bench = "hidden_tests" in task
    user = task_prompt(task) if bench else task["question"]
    ag = agent if bench else task.get("agente", agent)
    row = {"provider": provider, "model": model, "cost": 0.0, "latency": 0.0,
           "tokens": 0, "passed": False, "score": 0.0}
    t0 = time.time()
    try:
        res = chat(ag, system if system is not None else get_prompt(ag), user,
                   project=project, provider=provider, model=model, use_cache=False)
        row.update(latency=round(res.latency or time.time() - t0, 3), cost=res.cost,
                   tokens=res.tokens_in + res.tokens_out, used=f"{res.provider}:{res.model}")
        if bench:
            ev = evaluate_solution(task, res.text)
            row.update(passed=ev["passed"], tests_run=ev["tests_run"],
                       tests_failed=ev["tests_failed"],
                       score=10.0 * (ev["tests_run"] - ev["tests_failed"]) / ev["tests_run"]
                       if ev["tests_run"] else 0.0)
            if ev.get("error"):
                row["error"] = ev["error"]
        else:
            j = judge(task["question"], res.text, task.get("criteria"), task.get("expected"))
            row.update(score=float(j["score"]), passed=j["verdict"] == "PASS")
    except Exception as e:  # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        row["latency"] = round(time.time() - t0, 3)
    return row


def _winner(a: dict, b: dict, bench: bool) -> str:
    """'A', 'B' o 'tie' para una tarea."""
    if bench and a["passed"] != b["passed"]:
        return "A" if a["passed"] else "B"
    if a["score"] != b["score"]:
        return "A" if a["score"] > b["score"] else "B"
    return "tie"


def ab_test(task_set, model_a, model_b, judge=None, *, agent: str = "developer",
            system: str | None = None, project: str | None = None, save: bool = True) -> dict:
    """Compara dos modelos sobre `task_set` (ids de benchmark, tareas o casos).

    `model_a`/`model_b`: ("provider", "model") o "provider:model".
    `judge(question, output, criteria, expected) -> {score, verdict}` para casos abiertos.
    """
    if judge is None:
        from evals.judge import evaluate

        def judge(q, out, criteria, expected):
            return evaluate(q, out, criteria=criteria, expected=expected, project=project)

    pa, pb = _parse_model(model_a), _parse_model(model_b)
    tasks = _resolve(task_set)
    rows = []
    for t in tasks:
        a = _run_one(t, *pa, agent=agent, system=system, judge=judge, project=project)
        b = _run_one(t, *pb, agent=agent, system=system, judge=judge, project=project)
        bench = "hidden_tests" in t
        rows.append({"id": t.get("id", t.get("question", "")[:40]),
                     "scoring": "sandbox" if bench else "judge",
                     "A": a, "B": b, "winner": _winner(a, b, bench)})

    n = len(rows)
    wins_a = sum(r["winner"] == "A" for r in rows)
    wins_b = sum(r["winner"] == "B" for r in rows)
    ties = n - wins_a - wins_b

    def agg(side):
        rs = [r[side] for r in rows]
        return {"model": f"{(pa if side == 'A' else pb)[0]}:{(pa if side == 'A' else pb)[1]}",
                "wins": wins_a if side == "A" else wins_b,
                "win_rate": round(((wins_a if side == "A" else wins_b) + 0.5 * ties) / n, 4)
                if n else 0.0,
                "pass_rate": round(sum(x["passed"] for x in rs) / n, 4) if n else 0.0,
                "mean_score": round(sum(x["score"] for x in rs) / n, 3) if n else 0.0,
                "cost": round(sum(x["cost"] for x in rs), 6),
                "mean_latency": round(sum(x["latency"] for x in rs) / n, 3) if n else 0.0,
                "tokens": sum(x["tokens"] for x in rs),
                "errors": sum(1 for x in rs if x.get("error"))}

    A, B = agg("A"), agg("B")
    if A["win_rate"] != B["win_rate"]:
        winner, decided_by = ("A" if A["win_rate"] > B["win_rate"] else "B"), "win_rate"
    elif A["cost"] != B["cost"]:
        winner, decided_by = ("A" if A["cost"] < B["cost"] else "B"), "cost"
    elif A["mean_latency"] != B["mean_latency"]:
        winner, decided_by = ("A" if A["mean_latency"] < B["mean_latency"] else "B"), "latency"
    else:
        winner, decided_by = "tie", "empate total"
    report = {"timestamp": time.strftime("%Y%m%d-%H%M%S"), "n": n, "ties": ties,
              "A": A, "B": B, "winner": winner, "decided_by": decided_by,
              "winner_model": A["model"] if winner == "A" else B["model"] if winner == "B" else None,
              "tasks": rows}
    if save:
        d = global_state_dir() / "ab_tests"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{report['timestamp']}-{int(time.time() * 1000) % 1000:03d}.json"
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["path"] = str(p)
    return report


def render(report: dict) -> str:
    A, B = report["A"], report["B"]
    lines = [f"=== A/B: {A['model']} vs {B['model']} ({report['n']} tareas) ==="]
    for side, s in (("A", A), ("B", B)):
        lines.append(f"  {side} {s['model']:32s} win-rate {s['win_rate']:.2f} | pass "
                     f"{s['pass_rate']:.2f} | score {s['mean_score']:.1f} | ${s['cost']:.6f} | "
                     f"{s['mean_latency']:.1f}s")
    lines.append(f"  Ganador: {report['winner_model'] or 'empate'} (por {report['decided_by']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: `ades ab <prov:modelo_a> <prov:modelo_b> [--tasks id1 id2]`."""
    import argparse

    from evals.benchmark import load_tasks

    ap = argparse.ArgumentParser(description="A/B testing de modelos")
    ap.add_argument("modelo_a")
    ap.add_argument("modelo_b")
    ap.add_argument("--tasks", nargs="*")
    a = ap.parse_args(argv)
    print(render(ab_test(load_tasks(a.tasks), a.modelo_a, a.modelo_b)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
