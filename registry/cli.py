"""CLI del Tool Registry (comandos de voz) - ADES-AI, Fase 5.

Mapea los comandos de voz del plan a subcomandos:

    python -m registry.cli list                  # "Lista herramientas integradas"
    python -m registry.cli search <texto>        # "Que herramientas hay para <tarea>?" (ordenado por rating)
    python -m registry.cli add <url> [--tipo T]  # "Agrega <url> a ADES-AI"
    python -m registry.cli integrate <id>        # "Integra <herramienta>" (pasa por cuarentena)
    python -m registry.cli activate <id>         # "Activa <herramienta>"
    python -m registry.cli deactivate <id>       # "Desactiva <herramienta>"

Extensiones (features #13, #14, #15, #16, #25):

    python -m registry.cli rate <id> <1-5> [--comentario C] [--autor A]   # puntuar
    python -m registry.cli tag <id> <tag...>                              # etiquetar
    python -m registry.cli top [-n N] [--tipo T]                          # mejor valoradas
    python -m registry.cli conflicts <id>                                 # detector de conflictos
    python -m registry.cli pin <id> <ref>                                 # fijar versión
    python -m registry.cli update <id> [--force]                          # actualizar
    python -m registry.cli rollback <id>                                  # volver a la versión anterior
    python -m registry.cli scan <id> [--no-bandit] [--refresh]            # escaneo en cuarentena
    python -m registry.cli approve <id> --autor A [--force]               # aprobar (salir de cuarentena)
    python -m registry.cli quarantine                                     # listar cuarentena
"""
import argparse
import sys

from registry import conflicts, integrator, quarantine, ratings, registry, versioning

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _fmt_prom(p) -> str:
    return "  -  " if p is None else f"{p:.2f}"


def _cmd_list() -> int:
    state = integrator.list_state()["herramientas"]
    print("=== Herramientas (catalogo y estado) ===")
    for t in registry.get_tools():
        st = state.get(t["id"], {})
        marca = "activa" if st.get("activa") else "inactiva"
        integrada = "integrada" if st.get("integrada") else "no integrada"
        estado = st.get("estado", quarantine.SIN_VERIFICAR)
        commit = (st.get("commit") or "")[:10]
        print(f"  {t['id']:14s} {t['tipo']:6s} {marca:8s} {integrada:13s} {estado:13s} "
              f"{commit:10s} {t['nombre']}")
    return 0


def _cmd_search(query: str) -> int:
    results = ratings.search(query)
    print(f"=== Resultados para '{query}' ({len(results)}) — ordenados por rating ===")
    for t in results:
        print(f"  {t['id']} ({t['tipo']}) [{_fmt_prom(t['promedio'])} / {t['votos']} votos]: {t['descripcion']}")
        print(f"    url: {t['url']}")
        if t["tags"]:
            print(f"    tags: {', '.join(t['tags'])}")
    return 0


def _cmd_add(url: str, tipo: str) -> int:
    try:
        tool = registry.add_tool(url, tipo=tipo)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    print(f"[OK] agregado al catalogo: {tool['id']} ({tool['tipo']}) — estado: sin verificar")
    return 0


def _print_conflicts(lista: list[dict]) -> None:
    for c in lista:
        print(f"  - [{c['tipo']}] con '{c['con']}'{' (ACTIVA)' if c['activa'] else ''}: {c['detalle']}")


def _cmd_integrate(tool_id: str, dry_run: bool, force: bool, use_bandit: bool) -> int:
    try:
        result = integrator.integrate(tool_id, dry_run=dry_run, force=force, use_bandit=use_bandit)
    except (ValueError, RuntimeError) as e:
        print(f"[!] {e}")
        return 1
    if result.get("conflictos"):
        print("[aviso] conflictos detectados:")
        _print_conflicts(result["conflictos"])
    if result.get("cuarentena"):
        print(f"[CUARENTENA] {tool_id}: veredicto '{result['veredicto']}' (estado {result['estado']})")
        print(f"  informe: {result['informe']}")
        print(f"  siguiente paso: python -m registry.cli approve {tool_id} --autor <tu-nombre>")
        return 2
    modo = "PLAN (dry-run)" if dry_run else "EJECUTADO"
    print(f"[OK] {tool_id} -> metodo '{result['metodo']}' ({modo}); estado {result['estado']}")
    print(f"  accion: {result['plan']}")
    return 0


def _cmd_activate(tool_id: str, on: bool, force: bool = False) -> int:
    try:
        ok = integrator.activate(tool_id, force=force) if on else integrator.deactivate(tool_id)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    if not ok:
        print(f"[!] no existe '{tool_id}' en el estado")
        return 1
    print(f"[OK] '{tool_id}' {'activada' if on else 'desactivada'}")
    return 0


def _cmd_rate(tool_id: str, score: int, comentario: str, autor: str) -> int:
    try:
        ratings.rate(tool_id, score, comentario, autor)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    s = ratings.summary(tool_id)
    print(f"[OK] '{tool_id}' puntuada con {score}; media {_fmt_prom(s['promedio'])} ({s['votos']} votos)")
    return 0


def _cmd_tag(tool_id: str, tags: list[str]) -> int:
    try:
        todas = ratings.tag(tool_id, *tags)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    print(f"[OK] tags de '{tool_id}': {', '.join(todas)}")
    return 0


def _cmd_top(n: int, tipo: str | None) -> int:
    lista = ratings.top(n, tipo=tipo)
    print(f"=== Top {n} herramientas por rating ===")
    if not lista:
        print("  (sin valoraciones todavia: usa 'rate')")
    for i, t in enumerate(lista, 1):
        print(f"  {i}. {t['id']:14s} {t['tipo']:6s} {_fmt_prom(t['promedio'])} ({t['votos']} votos)"
              f"{'  tags: ' + ', '.join(t['tags']) if t['tags'] else ''}")
    return 0


def _cmd_conflicts(tool_id: str) -> int:
    try:
        lista = conflicts.check_conflicts(tool_id)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    if not lista:
        print(f"[OK] '{tool_id}' no tiene conflictos")
        return 0
    print(f"=== Conflictos de '{tool_id}' ({len(lista)}) ===")
    _print_conflicts(lista)
    return 1 if conflicts.blocking(lista) else 0


def _cmd_version(action: str, tool_id: str, ref: str | None = None, force: bool = False,
                 use_bandit: bool = True) -> int:
    try:
        if action == "pin":
            r = versioning.pin(tool_id, ref, force=force, use_bandit=use_bandit)
        elif action == "update":
            r = versioning.update(tool_id, force=force, use_bandit=use_bandit)
        else:
            r = versioning.rollback(tool_id)
    except (ValueError, RuntimeError) as e:
        print(f"[!] {e}")
        return 1
    if not r["cambio"]:
        print(f"[OK] '{tool_id}' ya esta en {r['commit'][:10]} (sin cambios)")
    else:
        print(f"[OK] {action} '{tool_id}': {(r['anterior'] or '?')[:10]} -> {r['commit'][:10]}")
    return 0


def _cmd_scan(tool_id: str, use_bandit: bool, refresh: bool) -> int:
    try:
        inf = quarantine.scan(tool_id, use_bandit=use_bandit, refresh=refresh)
    except (ValueError, RuntimeError) as e:
        print(f"[!] {e}")
        return 1
    res = inf["resumen"]
    print(f"=== Escaneo de '{tool_id}' (commit {(inf.get('commit') or '-')[:10]}) ===")
    print(f"  CRITICA {res['CRITICA']}  ALTA {res['ALTA']}  MEDIA {res['MEDIA']}  BAJA {res['BAJA']}")
    b = inf["bandit"]
    print(f"  bandit (sandbox Docker): {'ejecutado' if b.get('ejecutado') else 'NO ejecutado'}"
          f"{' - ' + b['error'] if b.get('error') else ''}")
    for h in inf["hallazgos"][:15]:
        print(f"  - {h['severidad']:7s} {h['origen']:8s} {h['regla']}: {h['archivo']}:{h['linea']} {h['detalle']}")
    if len(inf["hallazgos"]) > 15:
        print(f"  ... y {len(inf['hallazgos']) - 15} mas (ver informe)")
    if inf.get("nota"):
        print(f"  nota: {inf['nota']}")
    print(f"  VEREDICTO: {inf['veredicto']}   estado: {quarantine.status(tool_id)}")
    print(f"  informe: {quarantine.report_path(tool_id)}")
    return 0 if inf["veredicto"] != "rechazado" else 1


def _cmd_approve(tool_id: str, autor: str, force: bool) -> int:
    try:
        a = quarantine.approve(tool_id, autor, force=force)
    except ValueError as e:
        print(f"[!] {e}")
        return 1
    print(f"[OK] '{tool_id}' aprobada por {a['autor']} (commit {(a['commit'] or '-')[:10]}, "
          f"veredicto {a['veredicto']}{', FORZADA' if a['forzada'] else ''})")
    return 0


def _cmd_quarantine() -> int:
    lista = quarantine.list_quarantine()
    print(f"=== Herramientas en cuarentena ({len(lista)}) ===")
    for q in lista:
        r = q["resumen"] or {}
        print(f"  {q['id']:14s} {q['estado']:10s} veredicto={q['veredicto']} "
              f"C{r.get('CRITICA', 0)}/A{r.get('ALTA', 0)}/M{r.get('MEDIA', 0)}/B{r.get('BAJA', 0)} "
              f"commit={(q['commit'] or '-')[:10]}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Tool Registry (Fase 5)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="lista herramientas (catalogo + estado)")

    p_s = sub.add_parser("search", help="busca en el catalogo (ordenado por rating)")
    p_s.add_argument("query")

    p_a = sub.add_parser("add", help="agrega un repo al catalogo (recursivo)")
    p_a.add_argument("url")
    p_a.add_argument("--tipo", default="tool")

    p_i = sub.add_parser("integrate", help="integra una herramienta (pasa por cuarentena)")
    p_i.add_argument("id")
    p_i.add_argument("--dry-run", action="store_true")
    p_i.add_argument("--force", action="store_true", help="ignora conflictos con herramientas activas")
    p_i.add_argument("--no-bandit", action="store_true", help="no ejecuta bandit en el sandbox")

    p_on = sub.add_parser("activate", help="activa una herramienta (requiere aprobacion)")
    p_on.add_argument("id")
    p_on.add_argument("--force", action="store_true", help="ignora conflictos con herramientas activas")

    p_off = sub.add_parser("deactivate", help="desactiva una herramienta")
    p_off.add_argument("id")

    p_r = sub.add_parser("rate", help="puntua una herramienta (1-5)")
    p_r.add_argument("id")
    p_r.add_argument("score", type=int)
    p_r.add_argument("--comentario", default="")
    p_r.add_argument("--autor", default="anonimo")

    p_tag = sub.add_parser("tag", help="etiqueta una herramienta")
    p_tag.add_argument("id")
    p_tag.add_argument("tags", nargs="+")

    p_t = sub.add_parser("top", help="herramientas mejor valoradas")
    p_t.add_argument("-n", type=int, default=5)
    p_t.add_argument("--tipo", default=None)

    p_c = sub.add_parser("conflicts", help="detecta herramientas que compiten")
    p_c.add_argument("id")

    p_p = sub.add_parser("pin", help="fija una herramienta a un commit/tag/rama")
    p_p.add_argument("id")
    p_p.add_argument("ref")
    p_p.add_argument("--force", action="store_true", help="acepta veredicto 'cuarentena' del re-escaneo")
    p_p.add_argument("--no-bandit", action="store_true")

    p_u = sub.add_parser("update", help="actualiza a la ultima version (guarda historial)")
    p_u.add_argument("id")
    p_u.add_argument("--force", action="store_true", help="ignora el pin y acepta veredicto 'cuarentena'")
    p_u.add_argument("--no-bandit", action="store_true")

    p_rb = sub.add_parser("rollback", help="vuelve al commit anterior")
    p_rb.add_argument("id")

    p_sc = sub.add_parser("scan", help="clona en cuarentena y escanea (reglas + bandit en Docker)")
    p_sc.add_argument("id")
    p_sc.add_argument("--no-bandit", action="store_true")
    p_sc.add_argument("--refresh", action="store_true", help="vuelve a clonar la copia de cuarentena")

    p_ap = sub.add_parser("approve", help="aprueba una herramienta escaneada (sale de cuarentena)")
    p_ap.add_argument("id")
    p_ap.add_argument("--autor", required=True)
    p_ap.add_argument("--force", action="store_true", help="aprueba aunque el veredicto sea 'rechazado'")

    sub.add_parser("quarantine", help="lista herramientas en cuarentena")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "search":
        return _cmd_search(args.query)
    if args.cmd == "add":
        return _cmd_add(args.url, args.tipo)
    if args.cmd == "integrate":
        return _cmd_integrate(args.id, args.dry_run, args.force, not args.no_bandit)
    if args.cmd == "activate":
        return _cmd_activate(args.id, True, args.force)
    if args.cmd == "deactivate":
        return _cmd_activate(args.id, False)
    if args.cmd == "rate":
        return _cmd_rate(args.id, args.score, args.comentario, args.autor)
    if args.cmd == "tag":
        return _cmd_tag(args.id, args.tags)
    if args.cmd == "top":
        return _cmd_top(args.n, args.tipo)
    if args.cmd == "conflicts":
        return _cmd_conflicts(args.id)
    if args.cmd == "pin":
        return _cmd_version("pin", args.id, args.ref, args.force, not args.no_bandit)
    if args.cmd == "update":
        return _cmd_version("update", args.id, force=args.force, use_bandit=not args.no_bandit)
    if args.cmd == "rollback":
        return _cmd_version("rollback", args.id)
    if args.cmd == "scan":
        return _cmd_scan(args.id, not args.no_bandit, args.refresh)
    if args.cmd == "approve":
        return _cmd_approve(args.id, args.autor, args.force)
    if args.cmd == "quarantine":
        return _cmd_quarantine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
