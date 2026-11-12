"""Dashboard de costo en tokens por agente (ADES-AI, Fase 8).

Lee datos REALES de `core.metrics_store.summary()` (SQLite en `.ades/_global/metrics.db`,
alimentado por cada llamada de `core.llm_gateway.chat`) y, si existe, el último
resultado del benchmark harness (#17).

Uso:
    python -m evals.dashboard [--project ades-ai] [--run RUN_ID]
"""
from core import metrics_store


def render(summary: dict, title: str = "todos los proyectos", benchmark: dict | None = None) -> str:
    s = summary
    lines = [
        f"=== Dashboard de costo por agente ({title}) ===",
        f"  llamadas totales : {s['calls']}  (errores {s['errors']})",
        f"  hits de cache    : {s['cache_hits']}  (hit-rate {s['hit_rate']:.1%})",
        f"  tokens in/out    : {s['tokens_in']} / {s['tokens_out']}",
        f"  tokens locales   : {s['local_tokens']}  ($0)",
        f"  costo total      : ${s['cost']:.6f}",
    ]
    if not s["calls"]:
        lines.append("  (sin llamadas registradas todavía)")
    else:
        lines += ["", "  Por agente / modelo:"]
        for r in s["by_agent"]:
            lines.append(f"    {str(r['agent']):12s} {str(r['model']):28s} {r['calls']:5d} llamadas | "
                         f"{r['hits'] or 0} hits | {r['tokens'] or 0} tokens | ${r['cost'] or 0:.6f}")
    if benchmark:
        lines += ["", f"  Último benchmark [{benchmark.get('label')}] {benchmark.get('timestamp')}: "
                      f"pass@1 {benchmark['pass@1']:.2f} ({benchmark['passed']}/{benchmark['total']}) "
                      f"| ${benchmark['cost']:.6f}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from evals.benchmark import latest_results

    ap = argparse.ArgumentParser(description="Dashboard de costo por agente")
    ap.add_argument("--project")
    ap.add_argument("--run")
    a = ap.parse_args(argv)
    s = metrics_store.summary(project=a.project, run_id=a.run)
    title = f"proyecto {a.project}" if a.project else "todos los proyectos"
    print(render(s, title, latest_results()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
