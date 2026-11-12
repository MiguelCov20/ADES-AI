"""Marketplace interno con ratings (feature #13) - ADES-AI, Fase 5.

Permite puntuar (1-5) y etiquetar las herramientas ya probadas del catálogo, y
ordenar búsquedas por valoración media.

- `ratings.json` guarda las valoraciones (una por autor y herramienta: si el
  mismo autor vuelve a puntuar, se reemplaza su valoración) y las etiquetas que
  añaden los usuarios.
- Las etiquetas opcionales del catálogo (`tags` en catalog.json) se combinan con
  las del marketplace.

    rate("llmfit", 5, "funciona en mi GPU", "miguel")
    top(3)                      # mejores herramientas por media
    search("modelo")            # búsqueda ordenada por rating
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from registry import registry

RATINGS_PATH = Path(__file__).resolve().parent / "ratings.json"

MIN_SCORE, MAX_SCORE = 1, 5


def _empty() -> dict:
    return {"version": "1.0", "valoraciones": {}, "tags": {}}


def load() -> dict:
    """Carga ratings.json (estructura vacía si no existe)."""
    if not RATINGS_PATH.exists():
        return _empty()
    with open(RATINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("valoraciones", {})
    data.setdefault("tags", {})
    return data


def save(data: dict) -> None:
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _require_tool(tool_id: str) -> dict:
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")
    return tool


def rate(tool_id: str, score: int, comentario: str = "", autor: str = "anonimo") -> dict:
    """Puntúa una herramienta (1-5). Una valoración por autor (se reemplaza)."""
    _require_tool(tool_id)
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValueError("La puntuacion debe ser un entero entre 1 y 5.")
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"La puntuacion debe estar entre {MIN_SCORE} y {MAX_SCORE} (recibido {score}).")
    autor = (autor or "anonimo").strip() or "anonimo"

    data = load()
    lista = [v for v in data["valoraciones"].get(tool_id, []) if v.get("autor") != autor]
    entrada = {
        "puntuacion": score,
        "comentario": comentario,
        "autor": autor,
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    lista.append(entrada)
    data["valoraciones"][tool_id] = lista
    save(data)
    return entrada


def ratings(tool_id: str) -> list[dict]:
    """Valoraciones de una herramienta."""
    return list(load()["valoraciones"].get(tool_id, []))


def average(tool_id: str) -> float | None:
    """Media de puntuaciones (None si no hay valoraciones)."""
    lista = ratings(tool_id)
    if not lista:
        return None
    return round(sum(v["puntuacion"] for v in lista) / len(lista), 2)


def tag(tool_id: str, *tags: str) -> list[str]:
    """Añade etiquetas del marketplace a una herramienta. Devuelve todas sus etiquetas."""
    _require_tool(tool_id)
    data = load()
    actuales = data["tags"].setdefault(tool_id, [])
    for t in tags:
        t = t.strip().lower()
        if t and t not in actuales:
            actuales.append(t)
    save(data)
    return get_tags(tool_id)


def untag(tool_id: str, *tags: str) -> list[str]:
    """Quita etiquetas del marketplace (las del catálogo no se pueden quitar aquí)."""
    data = load()
    quitar = {t.strip().lower() for t in tags}
    data["tags"][tool_id] = [t for t in data["tags"].get(tool_id, []) if t not in quitar]
    save(data)
    return get_tags(tool_id)


def get_tags(tool_id: str) -> list[str]:
    """Etiquetas del catálogo (`tags`) + etiquetas del marketplace, sin duplicados."""
    tool = registry.get_tool(tool_id) or {}
    out: list[str] = []
    for t in list(tool.get("tags", [])) + load()["tags"].get(tool_id, []):
        t = str(t).strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def summary(tool_id: str) -> dict:
    """{id, promedio, votos, tags}."""
    return {
        "id": tool_id,
        "promedio": average(tool_id),
        "votos": len(ratings(tool_id)),
        "tags": get_tags(tool_id),
    }


def _sort_key(item: dict) -> tuple:
    # sin valoraciones al final; a igual media, más votos primero
    prom = item["promedio"]
    return (prom is None, -(prom or 0.0), -item["votos"], item["id"])


def top(n: int = 5, tipo: str | None = None) -> list[dict]:
    """Las `n` herramientas mejor valoradas (solo las que tienen votos)."""
    out = []
    for t in registry.get_tools():
        if tipo and t.get("tipo") != tipo:
            continue
        s = summary(t["id"])
        if s["votos"]:
            out.append({**s, "nombre": t["nombre"], "tipo": t["tipo"]})
    out.sort(key=_sort_key)
    return out[:max(0, n)]


def search(query: str) -> list[dict]:
    """Busca en id/nombre/tipo/descripción y etiquetas; ordena por rating.

    Devuelve las herramientas del catálogo enriquecidas con `promedio`, `votos`
    y `tags`.
    """
    q = query.lower()
    out = []
    for t in registry.get_tools():
        s = summary(t["id"])
        hay = " ".join([t["id"], t["nombre"], t["tipo"], t.get("descripcion", ""),
                        " ".join(t.get("provee", [])), " ".join(s["tags"])]).lower()
        if q in hay:
            out.append({**t, "promedio": s["promedio"], "votos": s["votos"], "tags": s["tags"]})
    out.sort(key=_sort_key)
    return out
