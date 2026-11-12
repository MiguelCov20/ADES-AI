"""Tests del regression detector (#19)."""
import pytest

from core.sandbox import SandboxResult
from evals import benchmark, regression


def _rows(passes, scores=None):
    return [{"id": f"c{i}", "passed": p, "score": None if scores is None else scores[i]}
            for i, p in enumerate(passes)]


def test_sin_cambios_no_hay_regresion():
    base = _rows([True] * 10, [8] * 10)
    r = regression.compare(base, base)
    assert r["regression"] is False and r["pass_drop"] == 0 and r["score_drop"] == 0


def test_caida_clara_es_regresion():
    base = _rows([True] * 10, [8] * 10)
    cand = _rows([True] * 4 + [False] * 6, [8] * 4 + [3] * 6)
    r = regression.compare(base, cand)
    assert r["regression"] is True
    assert r["pass_drop"] == pytest.approx(0.6) and r["score_drop"] == pytest.approx(3.0)
    assert r["sign_test"]["worse"] == 6 and r["sign_test"]["p_value"] < 0.05
    assert r["bootstrap"]["ci_high"] < 0


def test_caida_ruidosa_no_significativa():
    # 1 peor, 1 mejor sobre 10: la media cae pero no es consistente
    base = _rows([True] * 10, [8] * 9 + [2])
    cand = _rows([True] * 10, [1] + [8] * 8 + [3])
    r = regression.compare(base, cand, max_score_drop=0.5)
    assert r["score_drop"] > 0.5
    assert r["significant"] is False and r["regression"] is False
    assert any("no significativa" in x for x in r["reasons"])


def test_mejora_no_es_regresion():
    r = regression.compare(_rows([False] * 5), _rows([True] * 5))
    assert r["regression"] is False and r["pass_drop"] == -1.0


def test_solo_pass_fail_y_ids_desemparejados():
    base = _rows([True, True, True, True])
    cand = _rows([False, False, False]) + [{"id": "nuevo", "passed": True}]
    r = regression.compare(base, cand)
    assert r["n"] == 3 and r["missing"] == ["c3", "nuevo"]
    assert r["regression"] is True  # 3/3 peor: bootstrap IC < 0


def test_sign_test_exacto():
    st = regression.sign_test([-1, -1, -1, 0, 1])
    assert (st["worse"], st["better"], st["ties"]) == (3, 1, 1)
    assert st["p_value"] == pytest.approx(5 / 16)


def test_check_prompt_change_casos_con_baseline_cacheada(mock_llm):
    gen_calls = []

    def fn(provider, model, messages):
        system = messages[0].content
        if "evaluador" in system:  # juez
            bueno = "def " in messages[-1].content and "MALO" not in messages[-1].content
            return (f"SCORE: {9 if bueno else 2}\nVERDICT: {'PASS' if bueno else 'FAIL'}\n"
                    "RATIONALE: x"), 10, 5
        gen_calls.append(system)
        return ("def f():\n    return 1" if "MALO" not in system else "MALO: sin código"), 10, 5

    mock_llm(fn)
    kw = dict(provider="opencode", model="deepseek-v4.1-flash", source="cases",
              judge=lambda q, o, c, e: __import__("evals.judge", fromlist=["x"]).evaluate(
                  q, o, criteria=c, expected=e, council=False))
    ok = regression.check_prompt_change("developer", "Prompt nuevo equivalente.", **kw)
    assert ok["accept"] is True and ok["baseline_cached"] is False
    assert (regression.regression_dir() / f"{ok['baseline_name']}.json").exists()
    n_cases = len(regression.load_cases("developer"))
    assert len(gen_calls) == 2 * n_cases

    bad = regression.check_prompt_change("developer", "MALO: responde sin código.", **kw)
    assert bad["baseline_cached"] is True  # no se recalcula la baseline
    assert len(gen_calls) == 3 * n_cases
    assert bad["pass_rate_candidate"] == 0.0 and bad["pass_drop"] == 1.0
    assert bad["regression"] is True and bad["accept"] is False


def test_check_model_change_benchmark(monkeypatch, mock_llm):
    t = benchmark.load_tasks(["roman-numerals"])[0]
    good = "".join(f"```python\n# FILE: {n}\n{c}```\n" for n, c in t["reference"].items())

    def fn(provider, model, messages):
        return (good if model == "deepseek-v4.1-flash" else "no sé"), 10, 5

    mock_llm(fn)
    monkeypatch.setattr(benchmark.sandbox, "run_tests",
                        lambda files, timeout=180: SandboxResult(True, 0, "ok", 5, 0))
    r = regression.check_model_change("developer", "opencode", "deepseek-v4.1-flash",
                                      "ollama", "llama3.2:3b", source="benchmark",
                                      tasks=["roman-numerals", "merge-intervals"])
    assert r["pass_rate_baseline"] == 1.0 and r["pass_rate_candidate"] == 0.0
    assert r["regression"] is True


# ----------------------------------------------------------------------------- live
@pytest.mark.live
def test_live_regresion_prompt_saboteado():
    """Prompt saboteado vs prompt activo en 2 tareas del benchmark (deepseek-v4.1-flash)."""
    r = regression.check_prompt_change(
        "developer", "Responde solo con una frase en español explicando la idea. "
                     "NUNCA escribas código ni bloques de código.",
        provider="opencode", model="deepseek-v4.1-flash", source="benchmark",
        tasks=["roman-numerals", "merge-intervals"], refresh_baseline=True)
    print(f"\nRegresión: baseline {r['pass_rate_baseline']} -> candidato "
          f"{r['pass_rate_candidate']} | regression={r['regression']} | {r['reasons']}")
    assert r["pass_rate_candidate"] == 0.0
    if r["pass_rate_baseline"] == 1.0:
        assert r["regression"] is True
