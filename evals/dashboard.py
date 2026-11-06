"""Dashboard de costo en tokens por agente (ADES-AI, Fase 8).

Agrega las métricas de `cache/token_metrics.py` (Fase 7) y produce un reporte
legible por agente/tarea.
"""
from cache.token_metrics import TokenMetrics


def render(metrics: TokenMetrics) -> str:
    r = metrics.report()
    lines = [
        "=== Dashboard de costo por agente ===",
        f"  llamadas totales : {r['calls']}",
        f"  hits de cache    : {r['cache_hits']}  (hit-rate {r['hit_rate']})",
        f"  tokens in/out    : {r['input_tokens']} / {r['output_tokens']}",
        f"  costo total      : ${r['total_cost']:.6f}",
        "",
        "  Por tarea:",
    ]
    for task, t in sorted(r["by_task"].items()):
        lines.append(f"    {task:20s} {t['calls']} llamadas | "
                     f"{t['tokens']} tokens | ${t['cost']:.6f}")
    return "\n".join(lines)


def main() -> int:
    m = TokenMetrics()
    # Ejemplo de uso (sin llamadas reales): se documenta cómo se alimenta.
    print("El dashboard se alimenta con TokenMetrics.record(...).")
    print("Ejemplo:")
    m.record("developer", "gpt-oss:20b", 500, 200)
    m.record("reviewer", "deepseek-v4-pro", 300, 150, cache_hit=True)
    print(render(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
