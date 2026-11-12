"""Benchmark harness local estilo SWE-bench mini (feature #17).

Cada tarea de `evals/benchmarks/tasks/*.json` contiene:
  - `prompt`: el enunciado que recibe el solver (el Developer).
  - `hidden_tests`: tests pytest OCULTOS que el modelo nunca ve. Los añade el
    harness tras extraer los archivos de la respuesta.
  - `reference`: solución de referencia (sirve para validar las propias tareas).

Flujo por tarea: solver(prompt) -> texto -> `core.sandbox.extract_files` ->
se descartan los tests/conftest que haya escrito el modelo -> se añaden los
tests ocultos -> `core.sandbox.run_tests` (Docker, sin red). Se reporta pass@1,
tiempo, tokens y costo, y se guarda en `.ades/_global/benchmarks/<timestamp>.json`.

Uso:
    from evals.benchmark import run_benchmark, make_solver
    r = run_benchmark(make_solver("ollama", "gpt-oss:20b"), tasks=["roman-numerals"])
"""
import json
import time
from pathlib import Path
from typing import Callable

from core import sandbox
from core.config import global_state_dir

TASKS_DIR = Path(__file__).resolve().parent / "benchmarks" / "tasks"

_INSTRUCCIONES = (
    "\n\nEntrega el código en bloques ```python cuya primera línea sea `# FILE: <ruta>`. "
    "Respeta exactamente los nombres de archivo, funciones y clases pedidos. "
    "Solo librería estándar salvo que se indique otra cosa."
)


def load_tasks(ids: list[str] | None = None) -> list[dict]:
    """Carga las tareas del benchmark (todas, o las de `ids` en ese orden)."""
    tasks = {}
    for p in sorted(TASKS_DIR.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        tasks[t["id"]] = t
    if ids is None:
        return list(tasks.values())
    missing = [i for i in ids if i not in tasks]
    if missing:
        raise KeyError(f"Tareas de benchmark inexistentes: {missing}")
    return [tasks[i] for i in ids]


def _resolve_tasks(tasks) -> list[dict]:
    if tasks is None:
        return load_tasks()
    out = []
    for t in tasks:
        out.extend(load_tasks([t]) if isinstance(t, str) else [t])
    return out


def task_prompt(task: dict) -> str:
    """Enunciado completo que recibe el solver."""
    return task["prompt"] + _INSTRUCCIONES


def make_solver(provider: str | None = None, model: str | None = None, *,
                system: str | None = None, agent: str = "developer",
                project: str | None = None, effort: str | None = None) -> Callable:
    """Solver por defecto: el Developer vía `core.llm_gateway.chat` (sin caché).

    Devuelve un callable `solver(prompt) -> LLMResult` (el harness usa `.text`,
    los tokens y el costo reales).
    """
    from agents.prompts import get_prompt
    from core.llm_gateway import chat

    def solver(prompt: str):
        return chat(agent, system if system is not None else get_prompt(agent), prompt,
                    project=project, provider=provider, model=model, effort=effort,
                    use_cache=False)

    solver.label = f"{provider or 'auto'}:{model or 'auto'}"
    return solver


def _is_test_file(name: str) -> bool:
    base = Path(name).name
    return base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"


def evaluate_solution(task: dict, text: str, timeout: int = 180) -> dict:
    """Extrae los archivos de `text`, añade los tests ocultos y los ejecuta en el sandbox."""
    files = sandbox.extract_files(text or "")
    model_tests = [n for n in files if _is_test_file(n)]
    code = {n: c for n, c in files.items() if not _is_test_file(n)}
    if not code:
        return {"passed": False, "tests_run": 0, "tests_failed": 0, "files": [],
                "model_tests": model_tests, "error": "la respuesta no contiene archivos de código",
                "output": ""}
    res = sandbox.run_tests({**code, **task["hidden_tests"]}, timeout=timeout)
    return {"passed": bool(res.passed), "tests_run": res.tests_run,
            "tests_failed": res.tests_failed, "files": sorted(code), "model_tests": model_tests,
            "error": "TIMEOUT" if res.timed_out else "", "output": res.output[-1500:]}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def run_benchmark(solver: Callable | None = None, tasks=None, *, label: str = "",
                  save: bool = True, timeout: int = 180) -> dict:
    """Ejecuta el benchmark.

    - `solver(task_prompt) -> str | LLMResult`. Por defecto `make_solver()` (Developer
      con el prompt activo de `agents.prompts`).
    - `tasks`: None (todas), lista de ids o lista de dicts de tarea.
    Devuelve {pass@1, passed, total, time, tokens_in, tokens_out, cost, tasks:[...], path}.
    """
    solver = solver or make_solver()
    task_list = _resolve_tasks(tasks)
    results = []
    t_start = time.time()
    for task in task_list:
        prompt = task_prompt(task)
        t0 = time.time()
        row = {"id": task["id"], "passed": False, "tokens_in": 0, "tokens_out": 0,
               "cost": 0.0, "provider": "", "model": ""}
        try:
            out = solver(prompt)
            text = getattr(out, "text", out) or ""
            row["gen_time"] = round(time.time() - t0, 3)
            if hasattr(out, "tokens_in"):
                row.update(tokens_in=out.tokens_in, tokens_out=out.tokens_out,
                           cost=round(out.cost, 6), provider=out.provider, model=out.model)
                if getattr(out, "fallback_from", ""):
                    row["fallback_from"] = out.fallback_from
            else:
                row.update(tokens_in=_estimate_tokens(prompt), tokens_out=_estimate_tokens(text))
            row.update(evaluate_solution(task, text, timeout=timeout))
        except Exception as e:  # noqa: BLE001 — un fallo de una tarea no aborta el benchmark
            row["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        row["time"] = round(time.time() - t0, 3)
        results.append(row)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    report = {
        "timestamp": time.strftime("%Y%m%d-%H%M%S"),
        "label": label or getattr(solver, "label", getattr(solver, "__name__", "solver")),
        "pass@1": round(passed / total, 4) if total else 0.0,
        "passed": passed, "total": total,
        "time": round(time.time() - t_start, 3),
        "tokens_in": sum(r["tokens_in"] for r in results),
        "tokens_out": sum(r["tokens_out"] for r in results),
        "cost": round(sum(r["cost"] for r in results), 6),
        "tasks": results,
    }
    if save:
        d = global_state_dir() / "benchmarks"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{report['timestamp']}-{int(time.time() * 1000) % 1000:03d}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["path"] = str(path)
    return report


def latest_results() -> dict | None:
    """Último resultado de benchmark guardado (o None)."""
    d = global_state_dir() / "benchmarks"
    files = sorted(d.glob("*.json")) if d.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def render(report: dict) -> str:
    lines = [f"=== Benchmark [{report['label']}] pass@1 = {report['pass@1']:.2f} "
             f"({report['passed']}/{report['total']}) | {report['time']:.1f}s | "
             f"tokens {report['tokens_in']}/{report['tokens_out']} | ${report['cost']:.6f} ==="]
    for r in report["tasks"]:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"  {mark} {r['id']:18s} {r['time']:6.1f}s  tests {r.get('tests_run', 0)}"
                     f" (fallan {r.get('tests_failed', 0)})  ${r['cost']:.6f}"
                     + (f"  [{r['error']}]" if r.get("error") else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: `ades bench [--provider P --model M] [--tasks id1 id2]`."""
    import argparse

    ap = argparse.ArgumentParser(description="Benchmark harness local de ADES-AI")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--tasks", nargs="*")
    a = ap.parse_args(argv)
    print(render(run_benchmark(make_solver(a.provider, a.model), tasks=a.tasks)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
