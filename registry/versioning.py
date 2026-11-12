"""Version pinning + rollback (feature #15) - ADES-AI, Fase 5.

Cada herramienta integrada por `git clone` (skill, tool/cli/sdk, MCP de GitHub)
registra en `state.json` el commit instalado:

    "llmfit": {"commit": "<sha>", "rama": "main", "fijada": null,
               "historial": [{"commit": "<sha anterior>", "fecha": ..., "motivo": "update"}]}

- `pin(id, ref)`     fija la herramienta a un commit/tag/rama concreto.
- `update(id)`       trae la última versión de la rama (respeta el pin salvo force).
- `rollback(id)`     vuelve al commit anterior del historial.

Antes de aplicar código nuevo (update/pin) se re-escanea con el escáner de
seguridad (#16): si el veredicto no es `aprobado` se vuelve al commit anterior
(`rechazado` siempre; `cuarentena` salvo `force=True`).
"""
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from registry import registry

_REMOTE_GIT = re.compile(r"^(git@|ssh://|git://|https?://(www\.)?(github\.com|gitlab\.com|bitbucket\.org)/)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(args: list[str], cwd: Path | str | None = None, check: bool = True) -> str:
    """Ejecuta git y devuelve stdout (sin espacios finales). Lanza RuntimeError si falla."""
    p = subprocess.run(["git", "-c", "advice.detachedHead=false", *args], cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} fallo: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def is_git_source(url: str) -> bool:
    """True si la URL/ruta apunta a un repositorio git clonable."""
    if not url:
        return False
    if _REMOTE_GIT.match(url) or url.startswith("file://") or url.endswith(".git"):
        return True
    try:
        return (Path(url) / ".git").exists()
    except (OSError, ValueError):
        return False


def clone(url: str, target: Path) -> None:
    """Clona `url` en `target` (shallow para remotos; completo para rutas locales)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    args = ["clone", "-q"]
    if _REMOTE_GIT.match(url):
        args += ["--depth", "1"]
    git([*args, url, str(target)])


def head(path: Path) -> str:
    return git(["rev-parse", "HEAD"], cwd=path)


def current_branch(path: Path) -> str | None:
    b = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, check=False)
    return None if b in ("", "HEAD") else b


def install_dir(tool: dict) -> Path | None:
    """Directorio donde vive el clon integrado de la herramienta (None si no se clona)."""
    from registry import integrator
    metodo = integrator.method_for(tool)
    if metodo == "skill":
        return integrator.SKILLS_DIR / tool["id"]
    if metodo == "tool":
        return integrator.TOOLS_DIR / tool["id"]
    if metodo == "mcp" and integrator.mcp_source(tool) == "git":
        return integrator.TOOLS_DIR / tool["id"]
    return None


def _entry(state: dict, tool_id: str) -> dict:
    return state["herramientas"].setdefault(tool_id, {"activa": False, "integrada": False})


def _require(tool_id: str) -> tuple[dict, Path]:
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")
    path = install_dir(tool)
    if path is None:
        raise ValueError(f"'{tool_id}' (tipo {tool['tipo']}) no se instala por git: no es versionable.")
    if not (path / ".git").exists():
        raise ValueError(f"'{tool_id}' no esta integrada en {path} (ejecuta integrate primero).")
    return tool, path


def record_install(tool_id: str, path: Path) -> dict:
    """Registra en el estado el commit instalado (llamado por el integrador)."""
    state = registry.load_state()
    e = _entry(state, tool_id)
    e["commit"] = head(path)
    e["rama"] = current_branch(path)
    e.setdefault("historial", [])
    e.setdefault("fijada", None)
    registry.save_state(state)
    return e


def history(tool_id: str) -> list[dict]:
    return list(registry.load_state()["herramientas"].get(tool_id, {}).get("historial", []))


def _checkout(path: Path, sha: str) -> None:
    git(["checkout", "-q", "--detach", sha], cwd=path)


def _resolve(path: Path, ref: str) -> str:
    """Resuelve `ref` a un sha; si no está en local lo trae de origin."""
    sha = git(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], cwd=path, check=False)
    if sha:
        return sha
    git(["fetch", "-q", "origin", ref], cwd=path)
    return git(["rev-parse", "FETCH_HEAD^{commit}"], cwd=path)


def _apply(tool_id: str, path: Path, new_sha: str, motivo: str, force: bool,
           scan: bool, use_bandit: bool) -> dict:
    """Hace checkout de `new_sha` guardando el commit actual en el historial.

    Si `scan`, re-escanea el código nuevo y revierte si el veredicto no lo permite.
    """
    state = registry.load_state()
    e = _entry(state, tool_id)
    old = e.get("commit") or head(path)
    if new_sha == old:
        return {"id": tool_id, "commit": old, "anterior": old, "cambio": False, "motivo": motivo}

    _checkout(path, new_sha)
    informe = None
    if scan:
        from registry import scanner
        informe = scanner.scan_path(path, use_bandit=use_bandit)
        v = informe["veredicto"]
        if v == "rechazado" or (v == "cuarentena" and not force):
            _checkout(path, old)
            raise ValueError(f"El commit {new_sha[:10]} de '{tool_id}' obtuvo veredicto '{v}' en el "
                             f"escaneo de seguridad; se mantiene {old[:10]}"
                             f"{'' if v == 'rechazado' else ' (usa force=True para aceptarlo)'}.")

    state = registry.load_state()
    e = _entry(state, tool_id)
    e.setdefault("historial", []).append({"commit": old, "fecha": _now(), "motivo": motivo})
    e["commit"] = new_sha
    if informe is not None:
        e["escaneo"] = {"veredicto": informe["veredicto"], "fecha": informe["fecha"],
                        "commit": new_sha, "resumen": informe["resumen"]}
    registry.save_state(state)
    return {"id": tool_id, "commit": new_sha, "anterior": old, "cambio": True, "motivo": motivo,
            "veredicto": informe["veredicto"] if informe else None}


def pin(tool_id: str, ref: str, force: bool = False, scan: bool = True,
        use_bandit: bool = True) -> dict:
    """Fija la herramienta a `ref` (commit, tag o rama) y la marca como fijada."""
    _, path = _require(tool_id)
    sha = _resolve(path, ref)
    res = _apply(tool_id, path, sha, f"pin {ref}", force, scan, use_bandit)
    state = registry.load_state()
    _entry(state, tool_id)["fijada"] = sha
    registry.save_state(state)
    return {**res, "fijada": sha}


def unpin(tool_id: str) -> None:
    """Quita el pin (la próxima `update` vuelve a seguir la rama)."""
    state = registry.load_state()
    if tool_id in state["herramientas"]:
        state["herramientas"][tool_id]["fijada"] = None
        registry.save_state(state)


def update(tool_id: str, force: bool = False, scan: bool = True, use_bandit: bool = True) -> dict:
    """Actualiza a la última versión de la rama registrada (o HEAD remoto).

    Respeta el pin: si está fijada, solo actualiza con `force=True` (y quita el pin).
    """
    _, path = _require(tool_id)
    e = registry.load_state()["herramientas"].get(tool_id, {})
    if e.get("fijada") and not force:
        raise ValueError(f"'{tool_id}' esta fijada en {e['fijada'][:10]}; usa unpin o force=True.")
    git(["fetch", "-q", "origin", e.get("rama") or "HEAD"], cwd=path)
    sha = git(["rev-parse", "FETCH_HEAD^{commit}"], cwd=path)
    res = _apply(tool_id, path, sha, "update", force, scan, use_bandit)
    if force:
        unpin(tool_id)
    return res


def rollback(tool_id: str) -> dict:
    """Vuelve al commit anterior del historial (y lo saca del historial)."""
    _, path = _require(tool_id)
    state = registry.load_state()
    e = _entry(state, tool_id)
    hist = e.get("historial") or []
    if not hist:
        raise ValueError(f"'{tool_id}' no tiene historial: no hay version anterior a la que volver.")
    prev = hist.pop()
    actual = e.get("commit")
    _checkout(path, prev["commit"])
    e["commit"] = prev["commit"]
    if e.get("fijada"):
        e["fijada"] = prev["commit"]
    registry.save_state(state)
    return {"id": tool_id, "commit": prev["commit"], "anterior": actual, "cambio": True,
            "motivo": "rollback"}
