"""Regression detector (feature #19): ¿un cambio de prompt/modelo empeora la calidad?

Se corre una "baseline" y un "candidato" sobre el mismo conjunto de casos
(`evals/cases/casos.json` puntuado por el juez, y/o el benchmark #17 puntuado
por tests ocultos en el sandbox) y `compare()` decide si hay regresión:

  regresión = (caída de pass-rate > max_pass_drop  O  caída de score medio > max_score_drop)
              Y la caída es estadísticamente consistente:
              sign test unilateral (p < alpha)  O  IC bootstrap 95% de la diferencia < 0.

Las líneas base se guardan en `.ades/_global/regression/` (clave = agente + fuente +
hash del prompt + modelo) para no recalcularlas en cada cambio de prompt.

Formato de resultados (lista): [{"id": str, "passed": bool|None, "score": float|None}, ...]
"""
import hashlib
import json
import math
import random
import time
from pathlib import Path

from core.config import global_state_dir

CASES_PATH = Path(__file__).resolve().parent / "cases" / "casos.json"


def regression_dir() -> Path:
    d = global_state_dir() / "regression"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- estadística
def _value(r: dict) -> float | None:
    """Métrica por caso en [0, 1]: score/10 si existe, si no passed (1/0)."""
    if r.get("score") is not None:
        return float(r["score"]) / 10.0
    if r.get("passed") is not None:
        return 1.0 if r["passed"] else 0.0
    return None


def sign_test(diffs: list[float]) -> dict:
    """Sign test unilateral (H1: el candidato es peor). Ignora empates."""
    worse = sum(1 for d in diffs if d < 0)
    better = sum(1 for d in diffs if d > 0)
    n = worse + better
    p = sum(math.comb(n, k) for k in range(worse, n + 1)) / 2 ** n if n else 1.0
    return {"worse": worse, "better": better, "ties": len(diffs) - n, "p_value": round(p, 6)}


def bootstrap_ci(diffs: list[float], n_boot: int = 2000, seed: int = 0,
                 level: float = 0.95) -> dict:
    """IC bootstrap (percentil) de la media de las diferencias pareadas."""
    if not diffs:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int((1 - level) / 2 * n_boot)]
    hi = means[min(n_boot - 1, int((1 + level) / 2 * n_boot))]
    return {"mean": round(sum(diffs) / n, 6), "ci_low": round(lo, 6), "ci_high": round(hi, 6)}


def _rate(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return sum(float(v) for v in vals) / len(vals)


def compare(baseline_results: list[dict], candidate_results: list[dict], *,
            max_pass_drop: float = 0.05, max_score_drop: float = 0.5, alpha: float = 0.05,
            n_boot: int = 2000, seed: int = 0) -> dict:
    """Compara baseline vs candidato (función pura). Devuelve {"regression": bool, ...}.

    - `max_pass_drop`: caída tolerada del pass-rate (fracción, 0.05 = 5 puntos).
    - `max_score_drop`: caída tolerada del score medio (escala 1-10).
    Solo se comparan los casos presentes en ambos (pareados por `id`).
    """
    base = {r["id"]: r for r in baseline_results}
    cand = {r["id"]: r for r in candidate_results}
    ids = [i for i in base if i in cand]
    b_rows = [base[i] for i in ids]
    c_rows = [cand[i] for i in ids]

    pr_b = _rate([{"p": None if r.get("passed") is None else float(bool(r["passed"]))}
                  for r in b_rows], "p")
    pr_c = _rate([{"p": None if r.get("passed") is None else float(bool(r["passed"]))}
                  for r in c_rows], "p")
    sc_b, sc_c = _rate(b_rows, "score"), _rate(c_rows, "score")
    pass_drop = (pr_b - pr_c) if pr_b is not None and pr_c is not None else 0.0
    score_drop = (sc_b - sc_c) if sc_b is not None and sc_c is not None else 0.0

    diffs = []
    per_case = []
    for i in ids:
        vb, vc = _value(base[i]), _value(cand[i])
        if vb is None or vc is None:
            continue
        diffs.append(vc - vb)
        per_case.append({"id": i, "baseline": vb, "candidate": vc, "diff": round(vc - vb, 4)})

    st = sign_test(diffs)
    bs = bootstrap_ci(diffs, n_boot=n_boot, seed=seed)
    significant = st["p_value"] < alpha or bs["ci_high"] < 0
    reasons = []
    if pass_drop > max_pass_drop:
        reasons.append(f"pass-rate cae {pass_drop:.2%} (> {max_pass_drop:.2%})")
    if score_drop > max_score_drop:
        reasons.append(f"score medio cae {score_drop:.2f} (> {max_score_drop})")
    regression = bool(reasons) and significant
    if reasons and not significant:
        reasons.append("caída no significativa (sign test / bootstrap): no se marca regresión")
    return {
        "regression": regression, "n": len(ids), "n_compared": len(diffs),
        "pass_rate_baseline": None if pr_b is None else round(pr_b, 4),
        "pass_rate_candidate": None if pr_c is None else round(pr_c, 4),
        "pass_drop": round(pass_drop, 4),
        "score_baseline": None if sc_b is None else round(sc_b, 4),
        "score_candidate": None if sc_c is None else round(sc_c, 4),
        "score_drop": round(score_drop, 4),
        "sign_test": st, "bootstrap": bs, "significant": significant,
        "reasons": reasons, "per_case": per_case,
        "missing": sorted(set(base) ^ set(cand)),
    }


# --------------------------------------------------------------------------- ejecución
def load_cases(agent: str | None = None, path: Path = CASES_PATH) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    if agent:
        own = [c for c in cases if c.get("agente") == agent]
        return own or cases
    return cases


def run_cases(cases: list[dict], *, agent: str, prompt: str, provider: str | None = None,
              model: str | None = None, judge=None, project: str | None = None) -> list[dict]:
    """Genera la salida de cada caso con `prompt` y la puntúa con el juez.

    `judge(question, output, criteria, expected) -> {score, verdict}`; por defecto
    `evals.judge.evaluate` (que respeta ADES_JUDGE=council).
    """
    from core.llm_gateway import chat
    if judge is None:
        from evals.judge import evaluate

        def judge(q, out, criteria, expected):
            return evaluate(q, out, criteria=criteria, expected=expected, project=project)

    rows = []
    for c in cases:
        row = {"id": c["id"], "passed": False, "score": 0.0}
        try:
            res = chat(c.get("agente", agent), prompt, c["question"], project=project,
                       provider=provider, model=model, use_cache=False)
            j = judge(c["question"], res.text, c.get("criteria"), c.get("expected"))
            row.update(score=float(j["score"]), passed=j["verdict"] == "PASS",
                       cost=res.cost, model=f"{res.provider}:{res.model}")
        except Exception as e:  # noqa: BLE001 — un fallo cuenta como caso suspendido
            row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        rows.append(row)
    return rows


def run_benchmark_suite(*, agent: str, prompt: str, provider: str | None = None,
                        model: str | None = None, tasks=None,
                        project: str | None = None) -> list[dict]:
    """Corre el benchmark #17 con `prompt` como system del Developer."""
    from evals.benchmark import make_solver, run_benchmark
    rep = run_benchmark(make_solver(provider, model, system=prompt, agent=agent,
                                    project=project), tasks=tasks, save=False)
    return [{"id": t["id"], "passed": t["passed"], "score": None, "cost": t["cost"],
             "model": f"{t.get('provider', '')}:{t.get('model', '')}",
             **({"error": t["error"]} if t.get("error") else {})} for t in rep["tasks"]]


def run_suite(source: str, **kw) -> list[dict]:
    """source: "cases" | "benchmark" | "both"."""
    out = []
    if source in ("cases", "both"):
        cases = kw.pop("cases", None) or load_cases(kw["agent"])
        out += run_cases(cases, **{k: v for k, v in kw.items() if k != "tasks"})
    else:
        kw.pop("cases", None)
    if source in ("benchmark", "both"):
        out += run_benchmark_suite(**{k: v for k, v in kw.items() if k != "judge"})
    return out


def _key(agent: str, source: str, prompt: str, provider, model, tasks) -> str:
    h = hashlib.sha256(json.dumps([prompt, provider, model, tasks or "all"],
                                  sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"{agent}-{source}-{h}"


def save_baseline(name: str, results: list[dict], meta: dict | None = None) -> Path:
    p = regression_dir() / f"{name}.json"
    p.write_text(json.dumps({"name": name, "ts": time.time(), "meta": meta or {},
                             "results": results}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def load_baseline(name: str) -> list[dict] | None:
    p = regression_dir() / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))["results"] if p.exists() else None


def check_change(agent: str, *, new_prompt: str | None = None, provider: str | None = None,
                 model: str | None = None, new_provider: str | None = None,
                 new_model: str | None = None, source: str = "cases", tasks=None,
                 cases: list[dict] | None = None, judge=None, refresh_baseline: bool = False,
                 project: str | None = None, **thresholds) -> dict:
    """Compara la configuración actual (prompt activo + provider/model) con el candidato."""
    from agents.prompts import get_prompt
    current = get_prompt(agent)
    cand_prompt = new_prompt if new_prompt is not None else current
    cand_provider = new_provider or provider
    cand_model = new_model or model
    common = dict(agent=agent, tasks=tasks, cases=cases, judge=judge, project=project)

    name = _key(agent, source, current, provider, model,
                [tasks, [c.get("id") for c in cases] if cases else None])
    baseline = None if refresh_baseline else load_baseline(name)
    cached = baseline is not None
    if baseline is None:
        baseline = run_suite(source, prompt=current, provider=provider, model=model, **common)
        save_baseline(name, baseline, {"agent": agent, "source": source, "provider": provider,
                                       "model": model, "prompt": current})
    candidate = run_suite(source, prompt=cand_prompt, provider=cand_provider,
                          model=cand_model, **common)
    report = compare(baseline, candidate, **thresholds)
    report.update(agent=agent, source=source, baseline_name=name, baseline_cached=cached,
                  accept=not report["regression"], candidate_results=candidate,
                  baseline_results=baseline)
    rp = regression_dir() / f"report-{time.strftime('%Y%m%d-%H%M%S')}-{agent}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(rp)
    return report


def check_prompt_change(agent: str, new_prompt: str, **kw) -> dict:
    """¿El nuevo prompt de `agent` causa regresión frente al prompt activo?

    Devuelve el reporte de `compare` más `accept` (True si se puede adoptar).
    No activa el prompt: si `accept`, el llamador hace `agents.prompts.set_prompt`.
    """
    return check_change(agent, new_prompt=new_prompt, **kw)


def check_model_change(agent: str, provider: str, model: str, new_provider: str,
                       new_model: str, **kw) -> dict:
    """¿Cambiar (provider, model) -> (new_provider, new_model) causa regresión?"""
    return check_change(agent, provider=provider, model=model, new_provider=new_provider,
                        new_model=new_model, **kw)


def main(argv: list[str] | None = None) -> int:
    """CLI: `ades regression <agente> <archivo_con_prompt_nuevo> [--source cases|benchmark|both]`."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Regression detector de prompts")
    ap.add_argument("agente")
    ap.add_argument("prompt_file")
    ap.add_argument("--source", default="benchmark")
    a = ap.parse_args(argv)
    new_prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    r = check_prompt_change(a.agente, new_prompt, source=a.source)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str)[:4000])
    return 1 if r.get("regression") else 0


if __name__ == "__main__":
    raise SystemExit(main())
