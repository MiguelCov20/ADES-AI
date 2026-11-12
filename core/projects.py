"""Multi-proyecto simultáneo (feature #5).

Un workspace con N proyectos; cada uno tiene:
  - su carpeta de código: `workspace/<proyecto>/` (o una ruta existente registrada),
  - su estado aislado: `.ades/<proyecto>/` (backlog, runs, memoria del proyecto),
  - su presupuesto (core.budget) y sus métricas (filtradas por proyecto).

Registro en `.ades/_global/projects.json`.
"""
import json
import re
import time
from pathlib import Path

from core.config import ROOT, WORKSPACE_DIR, global_state_dir, state_dir


def _path() -> Path:
    return global_state_dir() / "projects.json"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s:
        raise ValueError("Nombre de proyecto inválido")
    return s


def load() -> dict:
    p = _path()
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data.setdefault("ades-ai", {"path": str(ROOT), "created": 0, "descripcion": "ADES-AI"})
    return data


def save(data: dict) -> None:
    _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create(name: str, path: str | None = None, descripcion: str = "") -> dict:
    data = load()
    pid = slug(name)
    if pid in data:
        return {"id": pid, **data[pid]}
    p = Path(path) if path else WORKSPACE_DIR / pid
    p.mkdir(parents=True, exist_ok=True)
    data[pid] = {"path": str(p.resolve()), "created": time.time(), "descripcion": descripcion}
    save(data)
    state_dir(pid)
    return {"id": pid, **data[pid]}


def get(pid: str) -> dict:
    data = load()
    if pid not in data:
        raise KeyError(f"Proyecto '{pid}' no existe")
    return {"id": pid, **data[pid]}


def path_of(pid: str) -> Path:
    return Path(get(pid)["path"])


def list_projects() -> list[dict]:
    return [{"id": k, **v} for k, v in load().items()]


def remove(pid: str) -> bool:
    """Quita el proyecto del registro (no borra archivos)."""
    data = load()
    if pid not in data or pid == "ades-ai":
        return False
    del data[pid]
    save(data)
    return True
