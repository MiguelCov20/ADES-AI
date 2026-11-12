"""Tests del A/B testing de modelos (#22)."""
import pytest

from core.sandbox import SandboxResult
from evals import ab_test, benchmark


def test_parse_model():
    assert ab_test._parse_model("ollama:gpt-oss:20b") == ("ollama", "gpt-oss:20b")
    assert ab_test._parse_model(("gemini", "x")) == ("gemini", "x")
    with pytest.raises(ValueError):
        ab_test._parse_model("sin-provider")


def test_ab_benchmark_con_sandbox(monkeypatch, mock_llm):
    def fn(provider, model, messages):
        if model == "deepseek-v4.1-flash":
            return "```python\n# FILE: roman.py\nBUENO = 1\n```", 100, 50
        return "```python\n# FILE: roman.py\nMALO = 1\n```", 100, 50

    mock_llm(fn)

    def fake_run(files, timeout=180):
        ok = any("BUENO" in c for c in files.values())
        return SandboxResult(ok, 0 if ok else 1, "", 4, 0 if ok else 3)

    monkeypatch.setattr(benchmark.sandbox, "run_tests", fake_run)
    r = ab_test.ab_test(["roman-numerals", "merge-intervals"], "opencode:deepseek-v4.1-flash",
                        ("ollama", "gpt-oss:20b"))
    assert r["winner"] == "A" and r["decided_by"] == "win_rate"
    assert r["A"]["win_rate"] == 1.0 and r["B"]["win_rate"] == 0.0
    assert r["A"]["pass_rate"] == 1.0 and r["B"]["mean_score"] == pytest.approx(2.5)
    assert r["A"]["cost"] > 0 and r["B"]["cost"] == 0.0  # local = $0
    assert r["tasks"][0]["scoring"] == "sandbox"
    assert r["winner_model"] == "opencode:deepseek-v4.1-flash" and "path" in r


def test_ab_casos_con_juez_y_desempate_por_costo(mock_llm):
    mock_llm(lambda p, m, msgs: ("respuesta", 1000, 1000))
    casos = [{"id": "q1", "question": "¿Qué es REST?", "criteria": ["claro"]},
             {"id": "q2", "question": "¿Qué es JWT?"}]
    judge = lambda q, out, c, e: {"score": 7, "verdict": "PASS"}  # noqa: E731
    r = ab_test.ab_test(casos, ("gemini", "gemini-flash-lite-latest"),
                        ("opencode", "deepseek-v4-pro"), judge=judge, save=False)
    assert r["ties"] == 2 and r["A"]["win_rate"] == r["B"]["win_rate"] == 0.5
    assert r["winner"] == "A" and r["decided_by"] == "cost"  # flash-lite es más barato
    assert r["tasks"][0]["scoring"] == "judge"


def test_ab_error_de_un_modelo_pierde(monkeypatch, mock_llm):
    def fn(provider, model, messages):
        if model in ("llama3.2:3b", "gpt-oss:20b"):
            raise RuntimeError("Ollama caído")
        return "ok", 10, 10

    mock_llm(fn)
    judge = lambda q, out, c, e: {"score": 8, "verdict": "PASS"}  # noqa: E731
    r = ab_test.ab_test([{"id": "q", "question": "hola"}], "ollama:llama3.2:3b",
                        "gemini:gemini-flash-lite-latest", judge=judge, save=False)
    assert r["winner"] == "B" and r["A"]["errors"] == 1


# ----------------------------------------------------------------------------- live
@pytest.mark.live
def test_live_ab_deepseek_flash_vs_gemini_lite():
    r = ab_test.ab_test(["merge-intervals"], "opencode:deepseek-v4.1-flash",
                        "gemini:gemini-flash-lite-latest")
    print("\n" + ab_test.render(r))
    for side in ("A", "B"):
        row = r["tasks"][0][side]
        print(f"  {side}: usado={row.get('used')} passed={row['passed']} error={row.get('error')}")
    assert r["n"] == 1 and r["winner"] in ("A", "B", "tie")
    assert r["A"]["tokens"] > 0 or r["B"]["tokens"] > 0
