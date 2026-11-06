"""CLI del Tool Registry (comandos de voz) - ADES-AI, Fase 5.

Mapea los comandos de voz del plan a subcomandos:

    python -m registry.cli list                  # "Lista herramientas integradas"
    python -m registry.cli search <texto>        # "Que herramientas hay para <tarea>?"
    python -m registry.cli add <url> [--tipo T]  # "Agrega <url> a ADES-AI"
    python -m registry.cli integrate <id>        # "Integra <herramienta>"
    python -m registry.cli activate <id>         # "Activa <herramienta>"
    python -m registry.cli deactivate <id>       # "Desactiva <herramienta>"
"""
import argparse
import sys

from registry import integrator, registry

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _cmd_list() -> int:
    state = integrator.list_state()["herramientas"]
    print("=== Herramientas (catalogo y estado) ===")
    for t in registry.get_tools():
        st = state.get(t["id"], {})
        marca = "activa" if st.get("activa") else "inactiva"
        integrada = "integrada" if st.get("integrada") else "no integrada"
        print(f"  {t['id']:14s} {t['tipo']:6s} {marca:8s} {integrada:13s} {t['nombre']}")
    return 0


def _cmd_search(query: str) -> int:
    results = registry.search(query)
    print(f"=== Resultados para '{query}' ({len(results)}) ===")
    for t in results:
        print(f"  {t['id']} ({t['tipo']}): {t['descripcion']}")
        print(f"    url: {t['url']}")
    return 0


def _cmd_add(url: str, tipo: str) -> int:
    try:
        tool = registry.add_tool(url, tipo=tipo)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    print(f"[OK] agregado al catalogo: {tool['id']} ({tool['tipo']})")
    return 0


def _cmd_integrate(tool_id: str, dry_run: bool) -> int:
    try:
        result = integrator.integrate(tool_id, dry_run=dry_run)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    modo = "PLAN (dry-run)" if dry_run else "EJECUTADO"
    print(f"[OK] {tool_id} -> metodo '{result['metodo']}' ({modo})")
    print(f"  accion: {result['plan']}")
    return 0


def _cmd_activate(tool_id: str, on: bool) -> int:
    ok = integrator.activate(tool_id) if on else integrator.deactivate(tool_id)
    if not ok:
        print(f"[!] no existe '{tool_id}' en el estado")
        return 1
    print(f"[OK] '{tool_id}' {'activada' if on else 'desactivada'}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Tool Registry (Fase 5)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="lista herramientas (catalogo + estado)")

    p_s = sub.add_parser("search", help="busca en el catalogo")
    p_s.add_argument("query")

    p_a = sub.add_parser("add", help="agrega un repo al catalogo (recursivo)")
    p_a.add_argument("url")
    p_a.add_argument("--tipo", default="tool")

    p_i = sub.add_parser("integrate", help="integra una herramienta")
    p_i.add_argument("id")
    p_i.add_argument("--dry-run", action="store_true")

    p_on = sub.add_parser("activate", help="activa una herramienta")
    p_on.add_argument("id")

    p_off = sub.add_parser("deactivate", help="desactiva una herramienta")
    p_off.add_argument("id")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "search":
        return _cmd_search(args.query)
    if args.cmd == "add":
        return _cmd_add(args.url, args.tipo)
    if args.cmd == "integrate":
        return _cmd_integrate(args.id, args.dry_run)
    if args.cmd == "activate":
        return _cmd_activate(args.id, True)
    if args.cmd == "deactivate":
        return _cmd_activate(args.id, False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
