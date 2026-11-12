"""Tests del benchmark harness local (#17)."""
import json
from pathlib import Path

import pytest

from core.config import global_state_dir
from core.sandbox import SandboxResult
from evals import benchmark

F = "`" * 3


def _as_answer(files: dict[str, str]) -> str:
    return "".join(f"{F}python\n# FILE: {n}\n{c}{F}\n" for n, c in files.items())


def _reference_solver(prompt: str) -> str:
    for t in benchmark.load_tasks():
        if prompt.startswith(t["prompt"]):
            return _as_answer(t["reference"])
    raise AssertionError("tarea desconocida")


def test_tareas_bien_formadas():
    tasks = benchmark.load_tasks()
    assert len(tasks) >= 6
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids))
    for t in tasks:
        assert t["prompt"] and t["reference"]
        assert t["hidden_tests"] and all(Path(n).name.startswith("test_hidden_")
                                         for n in t["hidden_tests"])
        # el enunciado no filtra los tests ocultos
        for body in t["hidden_tests"].values():
            assert body not in benchmark.task_prompt(t)


def test_load_tasks_ids_inexistentes():
    with pytest.raises(KeyError):
        benchmark.load_tasks(["no-existe"])


def test_run_benchmark_anade_tests_ocultos_y_descarta_los_del_modelo(monkeypatch):
    seen = []

    def fake_run_tests(files, timeout=180):
        seen.append(dict(files))
        return SandboxResult(passed=True, exit_code=0, output="3 passed", tests_run=3)

    monkeypatch.setattr(benchmark.sandbox, "run_tests", fake_run_tests)

    def solver(prompt):
        ans = _reference_solver(prompt)
        # el modelo añade sus propios tests/conftest: el harness debe ignorarlos
        return ans + f"{F}python\n# FILE: test_mio.py\ndef test_x():\n    assert True\n{F}\n" \
                     f"{F}python\n# FILE: conftest.py\nimport sys\n{F}\n"

    r = benchmark.run_benchmark(solver, tasks=["roman-numerals", "lru-cache"], label="ref")
    assert r["pass@1"] == 1.0 and r["passed"] == 2 and r["total"] == 2
    assert "test_hidden_roman.py" in seen[0] and "roman.py" in seen[0]
    assert "test_mio.py" not in seen[0] and "conftest.py" not in seen[0]
    assert r["tasks"][0]["model_tests"] == ["test_mio.py", "conftest.py"]
    saved = Path(r["path"])
    assert saved.parent == global_state_dir() / "benchmarks"
    assert json.loads(saved.read_text(encoding="utf-8"))["pass@1"] == 1.0
    assert benchmark.latest_results()["label"] == "ref"


def test_solver_por_defecto_usa_gateway_y_reporta_tokens(monkeypatch, mock_llm):
    calls = []

    def fake_llm(provider, model, messages):
        calls.append((provider, model, messages[0].content))
        t = benchmark.load_tasks(["merge-intervals"])[0]
        return _as_answer(t["reference"]), 1000, 500

    mock_llm(fake_llm)
    monkeypatch.setattr(benchmark.sandbox, "run_tests",
                        lambda files, timeout=180: SandboxResult(False, 1, "1 failed", 1, 1))
    r = benchmark.run_benchmark(benchmark.make_solver("opencode", "deepseek-v4.1-flash"),
                                tasks=["merge-intervals"], save=False)
    assert calls[0][:2] == ("opencode", "deepseek-v4.1-flash")
    assert "Developer" in calls[0][2]  # system = agents.prompts.get_prompt("developer")
    row = r["tasks"][0]
    assert row["tokens_in"] == 1000 and row["tokens_out"] == 500
    assert row["cost"] == pytest.approx((1000 * 0.10 + 500 * 0.40) / 1e6)
    assert r["pass@1"] == 0.0 and row["tests_failed"] == 1
    assert "path" not in r


def test_fallo_del_solver_no_aborta(monkeypatch):
    monkeypatch.setattr(benchmark.sandbox, "run_tests",
                        lambda files, timeout=180: SandboxResult(True, 0, "ok", 1, 0))

    def solver(prompt):
        if "roman.py" in prompt:
            raise RuntimeError("503 servicio caído")
        return _reference_solver(prompt)

    r = benchmark.run_benchmark(solver, tasks=["roman-numerals", "merge-intervals"], save=False)
    assert r["passed"] == 1 and r["total"] == 2
    assert "503" in r["tasks"][0]["error"]


def test_respuesta_sin_codigo():
    t = benchmark.load_tasks(["roman-numerals"])[0]
    ev = benchmark.evaluate_solution(t, "No sé hacerlo.")
    assert ev["passed"] is False and "no contiene" in ev["error"]


# ----------------------------------------------------------------------------- live
@pytest.mark.live
def test_live_referencias_pasan_en_sandbox():
    """Valida las propias tareas: las soluciones de referencia pasan los tests ocultos."""
    r = benchmark.run_benchmark(_reference_solver, save=False, label="reference")
    assert r["pass@1"] == 1.0, benchmark.render(r)


@pytest.mark.live
@pytest.mark.parametrize("provider,model", [("ollama", "gpt-oss:20b"),
                                            ("opencode", "deepseek-v4.1-flash"),
                                            ("gemini", "gemini-flash-lite-latest")])
def test_live_benchmark_modelos(provider, model):
    r = benchmark.run_benchmark(benchmark.make_solver(provider, model),
                                tasks=["roman-numerals", "merge-intervals"])
    print("\n" + benchmark.render(r))
    for t in r["tasks"]:
        if t.get("fallback_from"):
            print(f"  AVISO: {t['id']} resuelto por {t['provider']}:{t['model']} "
                  f"(fallback desde {t['fallback_from']})")
    assert r["total"] == 2 and Path(r["path"]).exists()
    assert all(t["tokens_out"] > 0 for t in r["tasks"]), r["tasks"]
