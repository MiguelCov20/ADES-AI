"""Operaciones del catálogo y estado del Tool Registry - ADES-AI, Fase 5.

- catalog.json: catálogo versionado de herramientas (metadatos).
- state.json: qué herramientas están activas/integradas en el proyecto.
"""
import json
import re
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
STATE_PATH = Path(__file__).resolve().parent / "state.json"


def load_catalog() -> dict:
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(catalog: dict) -> None:
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_state() -> dict:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_tools() -> list[dict]:
    return load_catalog().get("herramientas", [])


def get_tool(tool_id: str) -> dict | None:
    for t in get_tools():
        if t["id"] == tool_id:
            return t
    return None


def _id_from_url(url: str) -> str:
    """Deriva un id a partir de una URL de GitHub (repo path en kebab-case)."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s#]+)", url)
    if not m:
        return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")
    owner, repo = m.group(1), m.group(2).rstrip(".git")
    return re.sub(r"[^a-z0-9]+", "-", f"{owner}-{repo}".lower()).strip("-")


def add_tool(url: str, tipo: str = "tool", nombre: str | None = None,
             descripcion: str = "", instalacion: str = "git clone") -> dict:
    """Añade un repo al catálogo (flujo recursivo: 'agrega <repo> a ADES-AI')."""
    catalog = load_catalog()
    tool_id = _id_from_url(url)
    if get_tool(tool_id):
        raise ValueError(f"Ya existe la herramienta '{tool_id}' en el catalogo.")

    tool = {
        "id": tool_id,
        "nombre": nombre or tool_id,
        "tipo": tipo,
        "url": url,
        "descripcion": descripcion,
        "instalacion": instalacion,
        "licencia": "consultar",
    }
    catalog["herramientas"].append(tool)
    save_catalog(catalog)

    # registrar también en el estado (inactiva y sin verificar: cuarentena #25)
    state = load_state()
    state["herramientas"][tool_id] = {"activa": False, "integrada": False, "estado": "sin_verificar"}
    save_state(state)
    return tool


def search(query: str) -> list[dict]:
    """Busca en el catálogo por texto (id, nombre, tipo, descripción)."""
    q = query.lower()
    results = []
    for t in get_tools():
        hay = " ".join([t["id"], t["nombre"], t["tipo"], t["descripcion"]]).lower()
        if q in hay:
            results.append(t)
    return results
