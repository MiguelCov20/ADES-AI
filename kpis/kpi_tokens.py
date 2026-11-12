"""KPI 1 — Ahorro de tokens medido en Langfuse.

Objetivo del plan (sección 8):
  - ≥ 70% de ahorro de tokens medible en Langfuse tras la Fase 7.
  - ≥ 90% en flujos repetitivos cacheados.

Método (reproducible):
  Para un conjunto fijo de tareas reales sobre el código de ADES-AI se ejecutan,
  con llamadas reales a modelos, tres modos; cada modo es una sesión de Langfuse:

  * baseline  — agente "ingenuo": mete el código fuente COMPLETO de los paquetes
                que toca la tarea en el prompt, modelo de nube fijo
                (deepseek-v4-pro), sin caché, sin router.
  * ades      — pipeline ADES: RepoMap de esos paquetes (esqueleto desde Neo4j) +
                el cuerpo de las 2-3 funciones/clases relevantes recuperadas del
                grafo (GraphRAG), Brain Selector y caché semántico.
  * repetido  — la misma carga `ades` repetida (flujo repetitivo): debe salir
                del caché semántico.

  El ahorro se calcula con los tokens que Langfuse registró por sesión
  (`usageDetails`), no con estimaciones. La calidad se controla con un juez
  LLM: el modo ades no debe perder más de 1.5 puntos (sobre 10) de media.

Uso:
    python -m kpis.kpi_tokens            # ejecuta y guarda .ades/_global/kpis/kpi1_<ts>.json
"""
import ast
import json
import re
import time
from pathlib import Path

from core.config import ROOT, global_state_dir
from core.llm_gateway import chat
from evals import tracing
from kpis.langfuse_query import session_usage

SYSTEM = ("Eres un ingeniero senior del proyecto ADES-AI. Responde a la tarea usando SOLO las "
          "APIs que existen en el contexto dado. Si escribes codigo, que sea correcto y breve.")

TASKS = [
    {"id": "t1", "pkgs": ["core"], "symbols": ["summary", "spent"],
     "task": "Escribe una funcion `resumen_costos(project)` que use core.metrics_store para "
             "devolver el costo total y el hit-rate de cache de un proyecto."},
    {"id": "t2", "pkgs": ["core", "agents"], "symbols": ["chat", "cascade_for", "circuit_open"],
     "task": "Explica paso a paso como funciona el fallback en cascada de core.llm_gateway.chat "
             "y que modelos se prueban, en orden, si falla gemini-flash-latest."},
    {"id": "t3", "pkgs": ["cache"], "symbols": ["SemanticCache"],
     "task": "Anade a cache.semantic_cache.SemanticCache un metodo `delete(prompt)` que borre "
             "una entrada concreta. Devuelve solo el metodo."},
    {"id": "t4", "pkgs": ["core"], "symbols": ["status", "set_budget", "allowed"],
     "task": "Escribe un test pytest para core.budget.status que compruebe el paso de nivel "
             "'any' a 'cheap' a 'local'."},
    {"id": "t5", "pkgs": ["memory"], "symbols": ["validate_code", "GraphIndex"],
     "task": "Que hace memory.validator.validate_code con una linea `from paquete.modulo import "
             "Nombre` cuando Nombre no existe? Explicalo y da un ejemplo."},
    {"id": "t6", "pkgs": ["agents"], "symbols": ["claim_next", "work"],
     "task": "Explica como agents.backlog.work procesa los tickets y que pasa cuando un ticket "
             "falla dos veces."},
]

SKIP = {"__pycache__", ".opencode", "workspace", ".ades", "tests"}


def _py_files(pkgs: list[str]) -> list[Path]:
    out = []
    for p in pkgs:
        for f in sorted((ROOT / p).rglob("*.py")):
            if not any(part in SKIP for part in f.relative_to(ROOT).parts):
                out.append(f)
    return out


def baseline_context(t: dict) -> str:
    """Código fuente completo de los paquetes (lo que haría un agente sin optimizar)."""
    return "\n\n".join(f"# FILE: {f.relative_to(ROOT).as_posix()}\n"
                       + f.read_text(encoding="utf-8") for f in _py_files(t["pkgs"]))


def _symbol_source(symbols: list[str], files: list[Path]) -> list[str]:
    out = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in symbols:
                seg = ast.get_source_segment(src, node) or ""
                out.append(f"# {f.relative_to(ROOT).as_posix()}\n{seg}")
    return out


def ades_context(t: dict) -> str:
    """RepoMap (Neo4j) de los paquetes + fuente de los símbolos relevantes (GraphRAG)."""
    from memory.repomap import generate_repomap
    full = generate_repomap(repo=str(ROOT))
    keep, include = [], False
    for line in full.splitlines():
        if not line.startswith(" "):
            include = any(line.replace("\\", "/").startswith(p + "/") for p in t["pkgs"])
        if include:
            keep.append(line)
    snippets = _symbol_source(t["symbols"], _py_files(t["pkgs"]))
    return ("Mapa del repositorio (esqueleto):\n" + "\n".join(keep)
            + "\n\nCodigo relevante:\n" + "\n\n".join(snippets))


def _judge(task: str, answer: str, context: str) -> int:
    from evals.judge import evaluate
    r = evaluate(task, answer,
                 criteria=["Responde correctamente a la tarea",
                           "Usa solo APIs que existen en el codigo de referencia",
                           "Es correcto tecnicamente"],
                 expected="Codigo de referencia (extracto):\n" + context[:12000],
                 provider="opencode", model="deepseek-v4.1-flash", council=False)
    return int(r.get("score", 0))


def run(tasks=None, judge: bool = True) -> dict:
    import os
    b_prov, b_model = os.getenv("KPI1_BASELINE", "opencode:deepseek-v4-pro").split(":", 1)
    tasks = tasks or TASKS
    ts = time.strftime("%Y%m%d-%H%M%S")
    sessions = {m: f"kpi1-{m}-{ts}" for m in ("baseline", "ades", "repetido")}
    project = f"kpi1-{ts}"
    rows = []
    for t in tasks:
        bctx, actx = baseline_context(t), ades_context(t)
        b = chat("kpi-baseline", SYSTEM, t["task"], context=bctx, project=project,
                 run_id=sessions["baseline"], provider=b_prov, model=b_model,
                 use_cache=False)
        a = chat("kpi-ades", SYSTEM, t["task"], context=actx, project=project,
                 run_id=sessions["ades"], route=True, use_cache=True)
        r = chat("kpi-ades", SYSTEM, t["task"], context=actx, project=project,
                 run_id=sessions["repetido"], route=True, use_cache=True)
        row = {"id": t["id"], "baseline_ctx_chars": len(bctx), "ades_ctx_chars": len(actx),
               "baseline_model": b.model, "ades_model": f"{a.provider}/{a.model}",
               "repetido_cache_hit": r.cache_hit,
               # Validez: la línea base debe ser de nube y con el contexto COMPLETO (si cae a
               # un modelo local, Ollama trunca el contexto y la línea base sale artificialmente baja)
               "baseline_valido": b.provider != "ollama" and b.tokens_in >= len(bctx) // 6}
        if judge:
            # referencia = fuente real de los símbolos que pide la tarea (igual para ambos modos)
            ref = "\n\n".join(_symbol_source(t["symbols"], _py_files(t["pkgs"])))
            row["score_baseline"] = _judge(t["task"], b.text, ref)
            row["score_ades"] = _judge(t["task"], a.text, ref)
        rows.append(row)
        print(f"  {t['id']}: ctx {len(bctx)} -> {len(actx)} chars · ades={row['ades_model']} "
              f"· repetido cache={r.cache_hit} · scores {row.get('score_baseline')}/{row.get('score_ades')}")
    tracing.flush()
    n = len(tasks)
    usage = {m: session_usage(s, expected=n) for m, s in sessions.items()}
    base_tot = usage["baseline"]["total"] or 1
    res = {
        "fecha": ts, "sesiones_langfuse": sessions, "uso_langfuse": usage, "tareas": rows,
        "ahorro_tokens_ades": round(1 - usage["ades"]["total"] / base_tot, 4),
        "ahorro_tokens_repetido": round(1 - usage["repetido"]["total"] / base_tot, 4),
        "ahorro_tokens_pagados_ades": round(
            1 - usage["ades"]["pagados"] / (usage["baseline"]["pagados"] or 1), 4),
        "ahorro_costo_ades": round(1 - usage["ades"]["cost"] / (usage["baseline"]["cost"] or 1e-9), 4),
    }
    if judge:
        sb = sum(r["score_baseline"] for r in rows) / n
        sa = sum(r["score_ades"] for r in rows) / n
        res.update(score_medio_baseline=round(sb, 2), score_medio_ades=round(sa, 2))
        res["calidad_ok"] = sa >= sb - 1.5
    res["medicion_valida"] = all(r["baseline_valido"] for r in rows)
    res["kpi_70"] = (res["ahorro_tokens_ades"] >= 0.70 and res.get("calidad_ok", True)
                     and res["medicion_valida"])
    res["kpi_90_repetido"] = res["ahorro_tokens_repetido"] >= 0.90
    d = global_state_dir() / "kpis"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"kpi1_{ts}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main(argv=None) -> int:
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k not in ("tareas",)}, indent=2,
                     ensure_ascii=False))
    return 0 if (r["kpi_70"] and r["kpi_90_repetido"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
