"""CLI unificado `ades` (feature #26).

Un solo comando para todo el ecosistema:

    ades start                     levanta Docker (memoria, caché, gateway, Langfuse)
    ades status                    estado de servicios, modelos, GPU y presupuesto
    ades tokens [--project P]      tokens, costo y hit-rate del caché
    ades run "requerimiento" [--project P]       fábrica Dev⇄QA completa
    ades bootstrap "nombre" [--descripcion D]    Project Bootstrapper
    ades project list|create NOMBRE
    ades backlog add|board|work ... --project P
    ades budget show|set --project P [--usd X] [--tokens N]
    ades agent list|create|delete ...            (Reclutador)
    ades integrate ID | tools ... (list/search/add/activate/deactivate/rate/scan/...)
    ades memory remember|recall|why|consolidate ...
    ades watchdog|prefetch|voice|bench|council|ab|audit|improve|skills ...
    ades dashboard                 panel web en http://127.0.0.1:8765
    ades gpu                       modelos cargados / VRAM

En Windows: `ades.bat <comando>` (o `python -m ades_cli <comando>`).
"""
import importlib
import json
import subprocess
import sys
import urllib.request

from core.config import ROOT

SERVICES = {
    "Neo4j": "http://localhost:7474",
    "Qdrant": "http://localhost:6333",
    "Bifrost": "http://localhost:8080",
    "Langfuse": "http://localhost:3000/api/public/health",
    "Ollama": "http://localhost:11434/api/tags",
}

# subcomando -> (módulo, función main(argv)) — se delega el resto de argumentos
PASSTHROUGH = {
    "backlog": ("agents.backlog", "main"),
    "agent": ("agents.reclutador", "main"),
    "tools": ("registry.cli", "main"),
    "bootstrap": ("agents.bootstrap", "main"),
    "watchdog": ("automation.watchdog", "main"),
    "prefetch": ("automation.prefetch", "main"),
    "voice": ("automation.voice", "main"),
    "skills": ("automation.skill_generator", "main"),
    "improve": ("automation.self_improve", "main"),
    "serving": ("automation.model_serving", "main"),
    "bench": ("evals.benchmark", "main"),
    "council": ("evals.council", "main"),
    "ab": ("evals.ab_test", "main"),
    "audit": ("evals.ai_audit", "main"),
    "regression": ("evals.regression", "main"),
    "reflect": ("memory.reflection", "main"),
    "timeline": ("memory.timeline", "main"),
    "vaccine": ("memory.vaccine", "main"),
    "knowledge": ("memory.knowledge", "main"),
    "index": ("memory.indexer", "main"),
    "repomap": ("memory.repomap", "main"),
}


def _ping(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status < 500
    except Exception:
        return False


def cmd_start(_args) -> int:
    for f in ("docker-compose.yml", "docker-compose.langfuse.yml"):
        print(f"docker compose -f {f} up -d")
        subprocess.run(["docker", "compose", "-f", f, "up", "-d"], cwd=ROOT)
    return cmd_status([])


def cmd_status(_args) -> int:
    print("Servicios:")
    for name, url in SERVICES.items():
        print(f"  {'OK ' if _ping(url) else 'OFF'} {name:9s} {url}")
    try:
        from core import gpu_manager
        g = gpu_manager.status()
        print(f"GPU: {g['used_gb']}/{g['vram_gb']} GB · cargados: "
              f"{', '.join(m['name'] for m in g['loaded']) or 'ninguno'}"
              + (f" · OFFLOAD CPU: {g['cpu_offload']}" if g["cpu_offload"] else ""))
    except Exception as e:  # noqa: BLE001
        print(f"GPU: no disponible ({type(e).__name__})")
    from core import budget, projects
    print("Proyectos:")
    for p in projects.list_projects():
        b = budget.status(p["id"])
        print(f"  {p['id']:16s} gasto ${b['spent']['cost']:.4f}/{b['budget']['usd']} "
              f"({b['used_fraction'] * 100:.1f}%, nivel {b['tier']})")
    return 0


def cmd_tokens(args) -> int:
    from core import metrics_store
    project = args[args.index("--project") + 1] if "--project" in args else None
    s = metrics_store.summary(project=project)
    print(f"llamadas {s['calls']} · cache hits {s['cache_hits']} (hit-rate {s['hit_rate']:.1%})")
    print(f"tokens in/out {s['tokens_in']}/{s['tokens_out']} · locales ($0) {s['local_tokens']}")
    print(f"costo ${s['cost']:.5f} · errores {s['errors']}")
    for a in s["by_agent"]:
        print(f"  {a['agent']:12s} {a['model']:28s} {a['calls']:4d} llamadas "
              f"{a['tokens'] or 0:8d} tok ${a['cost'] or 0:.5f}")
    return 0


def cmd_run(args) -> int:
    from agents.orquestador import main
    return main(args)


def cmd_project(args) -> int:
    from core import projects
    if not args or args[0] == "list":
        for p in projects.list_projects():
            print(f"  {p['id']:16s} {p['path']}")
    elif args[0] == "create":
        print(projects.create(" ".join(args[1:])))
    return 0


def cmd_budget(args) -> int:
    from core import budget
    project = args[args.index("--project") + 1] if "--project" in args else "ades-ai"
    if args and args[0] == "set":
        usd = float(args[args.index("--usd") + 1]) if "--usd" in args else None
        tok = int(args[args.index("--tokens") + 1]) if "--tokens" in args else None
        budget.set_budget(project, usd, tok)
    print(json.dumps(budget.status(project), indent=2))
    return 0


def cmd_integrate(args) -> int:
    from registry.cli import main
    return main(["integrate", *args])


def cmd_memory(args) -> int:
    if not args:
        print("uso: ades memory remember|recall|why|consolidate ...")
        return 1
    sub, rest = args[0], args[1:]
    if sub == "remember":
        from memory import knowledge
        scope = "project" if "--project" in rest else "global"
        project = rest[rest.index("--project") + 1] if "--project" in rest else None
        text = " ".join(a for a in rest if a not in ("--project", project))
        print(knowledge.remember(text, project=project, scope=scope))
    elif sub == "recall":
        from memory import knowledge
        print(knowledge.recall_context(" ".join(rest)) or "(nada)")
    elif sub == "why":
        from memory import timeline
        print(timeline.why(" ".join(rest)))
    elif sub == "consolidate":
        from memory import reflection
        print(json.dumps(reflection.consolidate(), indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_dashboard(_args) -> int:
    from dashboard.app import main
    return main()


def cmd_gpu(_args) -> int:
    from core import gpu_manager
    print(json.dumps(gpu_manager.status(), indent=2))
    return 0


COMMANDS = {
    "start": cmd_start, "status": cmd_status, "tokens": cmd_tokens, "run": cmd_run,
    "project": cmd_project, "budget": cmd_budget, "integrate": cmd_integrate,
    "memory": cmd_memory, "dashboard": cmd_dashboard, "gpu": cmd_gpu,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in COMMANDS:
        return COMMANDS[cmd](rest) or 0
    if cmd in PASSTHROUGH:
        mod, fn = PASSTHROUGH[cmd]
        try:
            m = importlib.import_module(mod)
        except ImportError as e:
            print(f"[!] '{cmd}' no disponible: {e}")
            return 2
        f = getattr(m, fn, None)
        if f is None:
            print(f"[!] {mod} no expone {fn}()")
            return 2
        try:
            return f(rest) or 0
        except TypeError:
            sys.argv = [mod, *rest]
            return f() or 0
    print(f"[!] comando desconocido: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
