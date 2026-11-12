"""Modo cuarentena (feature #25) - ADES-AI, Fase 5.

Ninguna herramienta no verificada se integra ni se activa fuera de la
cuarentena. Flujo:

1. `scan(id)`: clona el repo en `registry/quarantine/<id>` (nunca en su destino
   final), lo escanea (#16) y guarda el informe en
   `registry/quarantine/<id>.informe.json`. Estado -> `cuarentena`
   (o `rechazada` si el veredicto es `rechazado`).
2. `approve(id, autor)`: aprobación humana explícita del commit escaneado.
   Estado -> `aprobada`. Un veredicto `rechazado` solo se aprueba con `force=True`.
3. `integrator.integrate(id, dry_run=False)` instala desde la copia verificada de
   cuarentena (mismo commit aprobado) y `integrator.activate(id)` exige `aprobada`.

Estados (`state.json` -> herramientas.<id>.estado):
`sin_verificar` (por defecto) | `cuarentena` | `aprobada` | `rechazada`.
"""
import json
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from registry import registry, scanner, versioning

QUARANTINE_DIR = Path(__file__).resolve().parent / "quarantine"

SIN_VERIFICAR, CUARENTENA, APROBADA, RECHAZADA = "sin_verificar", "cuarentena", "aprobada", "rechazada"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quarantine_path(tool_id: str) -> Path:
    return QUARANTINE_DIR / tool_id


def report_path(tool_id: str) -> Path:
    return QUARANTINE_DIR / f"{tool_id}.informe.json"


def status(tool_id: str) -> str:
    return registry.load_state()["herramientas"].get(tool_id, {}).get("estado", SIN_VERIFICAR)


def is_approved(tool_id: str) -> bool:
    return status(tool_id) == APROBADA


def load_report(tool_id: str) -> dict | None:
    p = report_path(tool_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _rmtree(path: Path) -> None:
    def _onerror(func, p, _exc):  # en Windows los objetos de .git son de solo lectura
        Path(p).chmod(stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_onerror)


def _fetch_into_quarantine(tool: dict, refresh: bool) -> Path | None:
    """Clona el repo en cuarentena. None si la herramienta no viene de git."""
    if not versioning.is_git_source(tool.get("url", "")):
        return None
    dest = quarantine_path(tool["id"])
    if dest.exists() and refresh:
        _rmtree(dest)
    if not (dest / ".git").exists():
        if dest.exists():
            _rmtree(dest)
        versioning.clone(tool["url"], dest)
    return dest


def scan(tool_id: str, use_bandit: bool = True, refresh: bool = False) -> dict:
    """Clona en cuarentena, escanea y actualiza el estado. Devuelve el informe."""
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")
    dest = _fetch_into_quarantine(tool, refresh)
    if dest is None:
        informe = {
            "ruta": None, "commit": None, "fecha": _now(), "hallazgos": [],
            "resumen": {s: 0 for s in scanner.SEVERIDADES},
            "bandit": {"ejecutado": False, "error": "sin codigo que escanear"},
            "veredicto": "cuarentena",
            "nota": f"'{tool.get('url')}' no es un repositorio git: no hay codigo que escanear; "
                    "requiere revision manual y approve().",
        }
    else:
        informe = scanner.scan_path(dest, use_bandit=use_bandit)
    informe = {"id": tool_id, "url": tool.get("url"), **informe}

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    report_path(tool_id).write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    state = registry.load_state()
    e = state["herramientas"].setdefault(tool_id, {"activa": False, "integrada": False})
    aprob = e.get("aprobacion") or {}
    if informe["veredicto"] == "rechazado":
        e["estado"] = RECHAZADA
        e["activa"] = False
    elif e.get("estado") == APROBADA and aprob.get("commit") == informe["commit"]:
        pass  # mismo commit ya aprobado: se mantiene la aprobación
    else:
        e["estado"] = CUARENTENA  # código nuevo o sin aprobar: requiere approve()
        e["activa"] = False
    e["escaneo"] = {"veredicto": informe["veredicto"], "fecha": informe["fecha"],
                    "commit": informe["commit"], "resumen": informe["resumen"],
                    "informe": str(report_path(tool_id))}
    registry.save_state(state)
    return informe


def approve(tool_id: str, autor: str, force: bool = False) -> dict:
    """Aprobación humana explícita: saca la herramienta de cuarentena."""
    if not autor or not autor.strip():
        raise ValueError("La aprobacion requiere un autor.")
    state = registry.load_state()
    e = state["herramientas"].get(tool_id)
    if e is None or not e.get("escaneo"):
        raise ValueError(f"'{tool_id}' no ha sido escaneada: ejecuta scan antes de aprobar.")
    v = e["escaneo"]["veredicto"]
    if v == "rechazado" and not force:
        raise ValueError(f"'{tool_id}' fue RECHAZADA por el escaneo; solo se aprueba con force=True "
                         f"tras revisar {e['escaneo'].get('informe')}.")
    e["estado"] = APROBADA
    e["aprobacion"] = {"autor": autor.strip(), "fecha": _now(), "commit": e["escaneo"].get("commit"),
                       "veredicto": v, "forzada": bool(force and v != "aprobado")}
    registry.save_state(state)
    return e["aprobacion"]


def list_quarantine() -> list[dict]:
    """Herramientas en `cuarentena` o `rechazada` con su último veredicto."""
    out = []
    for tid, e in registry.load_state()["herramientas"].items():
        if e.get("estado") in (CUARENTENA, RECHAZADA):
            esc = e.get("escaneo") or {}
            out.append({"id": tid, "estado": e["estado"], "veredicto": esc.get("veredicto"),
                        "commit": esc.get("commit"), "resumen": esc.get("resumen", {}),
                        "informe": esc.get("informe")})
    return out
