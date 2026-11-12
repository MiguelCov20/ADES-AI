"""Integrador de herramientas del Tool Registry - ADES-AI, Fase 5.

Aplica la integración de una herramienta según su tipo (6 métodos):

| tipo            | acción del integrador                              |
|-----------------|----------------------------------------------------|
| skill           | clonar a `.opencode/skills/<id>/`                  |
| mcp             | añadir entrada a `mcp_servers/mcp_config.json`     |
| tool / cli / sdk| instalar binario o añadir dependencia              |
| plugin          | registrar en `opencode.json` -> `plugins`          |
| model           | `ollama pull <modelo>`                             |
| app             | añadir servicio a `docker-compose.yml`             |

`integrate()` acepta `dry_run=True` (devuelve el plan sin ejecutar) para poder
probar la selección de método sin efectos secundarios.

Con `dry_run=False` la integración pasa por:
1. Detector de conflictos (#14): se niega si compite con una herramienta activa
   (salvo `force=True`).
2. Cuarentena (#25) + escaneo de seguridad (#16): si la herramienta no está
   aprobada, se clona y escanea en `registry/quarantine/<id>` y se queda ahí
   hasta `quarantine.approve(id, autor)`.
3. Instalación desde la copia verificada de cuarentena y registro del commit
   (#15, version pinning).
"""
import json
import re
import subprocess
from pathlib import Path

import yaml

from registry import conflicts, quarantine, registry, versioning

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / ".opencode" / "skills"
TOOLS_DIR = ROOT / "registry" / "tools"
MCP_CONFIG = ROOT / "mcp_servers" / "mcp_config.json"
OPENCODE_CONFIG = ROOT / "opencode.json"
COMPOSE_FILE = ROOT / "docker-compose.yml"

# Perfil de compose para las apps del registry: no arrancan con `docker compose up -d`.
COMPOSE_PROFILE = "registry"

# Mapeo tipo -> método (los tipos `cli` y `sdk` se integran como `tool`).
TYPE_TO_METHOD = {
    "skill": "skill",
    "mcp": "mcp",
    "tool": "tool",
    "cli": "tool",
    "plugin": "plugin",
    "model": "model",
    "app": "app",
    "sdk": "tool",
}

_NPM_SCOPED = re.compile(r"^@[a-z0-9][\w.-]*/[a-z0-9][\w.-]*(@[\w.^~<>=-]+)?$", re.I)
_NPMJS_URL = re.compile(r"^https?://(www\.)?npmjs\.com/package/(@[^/?#]+/[^/?#]+|[^/?#]+)", re.I)


def method_for(tool: dict) -> str:
    return TYPE_TO_METHOD.get(tool.get("tipo", "tool"), "tool")


def npm_package(url: str) -> str | None:
    """Nombre del paquete npm si la URL lo es (`npm:pkg`, `@scope/pkg`, npmjs.com/package/...)."""
    url = (url or "").strip()
    if url.startswith("npm:"):
        return url[4:].strip() or None
    if _NPM_SCOPED.match(url):
        return url
    m = _NPMJS_URL.match(url)
    return m.group(2) if m else None


def mcp_source(tool: dict) -> str:
    """Origen de un MCP: `comando` (catálogo), `npm`, `git` o `desconocido`."""
    if tool.get("mcp_command"):
        return "comando"
    if npm_package(tool.get("url", "")):
        return "npm"
    if versioning.is_git_source(tool.get("url", "")):
        return "git"
    return "desconocido"


def integrate(tool_id: str, dry_run: bool = True, force: bool = False,
              use_bandit: bool = True) -> dict:
    """Integra una herramienta. Devuelve {id, tipo, metodo, plan, ejecutado, conflictos, estado}.

    Si no está aprobada, la deja en cuarentena con su informe de escaneo
    (`ejecutado=False`, `cuarentena=True`).
    """
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")

    metodo = method_for(tool)
    plan = _plan(tool, metodo)
    conflictos = conflicts.check_conflicts(tool_id)
    base = {"id": tool_id, "tipo": tool["tipo"], "metodo": metodo, "plan": plan,
            "conflictos": conflictos, "estado": quarantine.status(tool_id)}

    if dry_run:
        return {**base, "ejecutado": False}

    bloq = conflicts.blocking(conflictos)
    if bloq and not force:
        raise ValueError(f"'{tool_id}' compite con herramientas activas: "
                         f"{conflicts.format_conflicts(bloq)}. Usa force=True para integrarla igualmente.")

    if not quarantine.is_approved(tool_id):
        informe = quarantine.scan(tool_id, use_bandit=use_bandit)
        return {**base, "ejecutado": False, "cuarentena": True,
                "estado": quarantine.status(tool_id), "veredicto": informe["veredicto"],
                "informe": str(quarantine.report_path(tool_id)),
                "plan": f"en cuarentena ({quarantine.quarantine_path(tool_id)}); veredicto "
                        f"'{informe['veredicto']}'. Revisa el informe y ejecuta approve antes de integrar."}

    _execute(tool, metodo)

    # marcar como integrada en el estado y registrar el commit instalado
    state = registry.load_state()
    state["herramientas"].setdefault(tool_id, {})
    state["herramientas"][tool_id]["integrada"] = True
    registry.save_state(state)
    path = versioning.install_dir(tool)
    if path is not None and (path / ".git").exists():
        if not registry.load_state()["herramientas"][tool_id].get("commit"):
            versioning.record_install(tool_id, path)

    return {**base, "ejecutado": True, "estado": quarantine.status(tool_id)}


def _plan(tool: dict, metodo: str) -> str:
    url = tool["url"]
    tid = tool["id"]
    if metodo == "skill":
        return f"git clone {url} {SKILLS_DIR / tid}"
    if metodo == "mcp":
        src = mcp_source(tool)
        extra = {"comando": f"comando del catalogo: {tool.get('mcp_command')}",
                 "npm": f"npx -y {npm_package(url)}",
                 "git": f"git clone {url} {TOOLS_DIR / tid}; entrada deshabilitada hasta definir comando",
                 "desconocido": "entrada deshabilitada hasta definir comando"}[src]
        return f"anadir entrada '{tid}' a {_rel(MCP_CONFIG)} ({extra})"
    if metodo == "tool":
        return f"git clone {url} {TOOLS_DIR / tid}"
    if metodo == "plugin":
        return f"registrar '{tid}' en {_rel(OPENCODE_CONFIG)} -> plugins"
    if metodo == "model":
        return f"ollama pull {tid}"
    if metodo == "app":
        return f"anadir servicio '{tid}' a {_rel(COMPOSE_FILE)} (perfil '{COMPOSE_PROFILE}')"
    return "metodo desconocido"


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _install_repo(tool: dict, target: Path) -> None:
    """Instala el repo en `target` desde la copia verificada de cuarentena.

    Garantiza que se instala exactamente el commit aprobado.
    """
    if target.exists():
        return
    src = quarantine.quarantine_path(tool["id"])
    if not (src / ".git").exists():
        raise ValueError(f"No hay copia verificada de '{tool['id']}' en cuarentena ({src}); "
                         "ejecuta scan y approve de nuevo.")
    target.parent.mkdir(parents=True, exist_ok=True)
    versioning.git(["clone", "-q", str(src), str(target)])
    versioning.git(["remote", "set-url", "origin", tool["url"]], cwd=target)
    aprobado = (registry.load_state()["herramientas"].get(tool["id"], {})
                .get("aprobacion", {}).get("commit"))
    if aprobado and versioning.head(target) != aprobado:
        versioning.git(["checkout", "-q", "--detach", aprobado], cwd=target)


def _execute(tool: dict, metodo: str) -> None:
    url = tool["url"]
    tid = tool["id"]
    if metodo == "skill":
        _install_repo(tool, SKILLS_DIR / tid)
    elif metodo == "tool":
        _install_repo(tool, TOOLS_DIR / tid)
    elif metodo == "plugin":
        _add_plugin(tid, url)
    elif metodo == "mcp":
        _add_mcp(tool)
    elif metodo == "model":
        subprocess.run(["ollama", "pull", tid], check=False)
    elif metodo == "app":
        _add_app_service(tid, url)


def _add_plugin(tid: str, url: str) -> None:
    cfg = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    plugins = cfg.setdefault("plugins", [])
    if url not in plugins:
        plugins.append(url)
        OPENCODE_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mcp_entry(tool: dict) -> dict:
    """Construye la entrada de `mcp_config.json` para un MCP del catálogo.

    - `mcp_command`/`mcp_args` en el catálogo -> se usan tal cual.
    - paquete npm (`npm:pkg`, `@scope/pkg`) -> `npx -y <pkg>`.
    - repo de GitHub -> se clona en `registry/tools/<id>` y la entrada queda
      deshabilitada con `_pendiente` (nunca una entrada rota activa).
    """
    url = tool.get("url", "")
    src = mcp_source(tool)
    if src == "comando":
        entry = {"command": tool["mcp_command"], "args": list(tool.get("mcp_args", [])), "enabled": True}
        if tool.get("mcp_env"):
            entry["env"] = dict(tool["mcp_env"])
        return entry
    if src == "npm":
        return {"command": "npx", "args": ["-y", npm_package(url), *tool.get("mcp_args", [])],
                "enabled": True}
    entry = {"enabled": False, "_pendiente": "definir comando de arranque", "_fuente": url}
    if src == "git":
        entry["cwd"] = str(TOOLS_DIR / tool["id"])
    return entry


def _add_mcp(tool: dict) -> None:
    tid = tool["id"]
    if mcp_source(tool) == "git":
        _install_repo(tool, TOOLS_DIR / tid)
    MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if MCP_CONFIG.exists():
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    else:
        cfg = {"mcpServers": {}}
    servers = cfg.setdefault("mcpServers", {})
    if tid not in servers:
        servers[tid] = mcp_entry(tool)
        MCP_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_TOP_KEY = re.compile(r"^[^\s#][^:]*:")
_SERVICES = re.compile(r"^services:\s*(#.*)?$")


def _add_app_service(tid: str, url: str) -> None:
    """Añade un servicio al docker-compose.yml (integración tipo 'app').

    Inserta el bloque al final de la sección `services:` (antes de la siguiente
    clave de nivel superior, p.ej. `volumes:` en columna 0), preservando los
    comentarios existentes. La imagen queda como `{tid}:latest` (placeholder) y
    el servicio va en el perfil `registry`, así `docker compose up -d` no intenta
    arrancar una imagen inexistente (`docker compose --profile registry up -d`
    para lanzarlo tras ajustar la imagen). Valida el YAML antes de escribir.
    """
    text = COMPOSE_FILE.read_text(encoding="utf-8") if COMPOSE_FILE.exists() else ""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{COMPOSE_FILE} no es YAML valido; no se modifica: {e}") from e
    if tid in (data.get("services") or {}):
        return  # ya existe

    block = (
        f"  # App integrada via Tool Registry: {tid} ({url})\n"
        f"  {tid}:\n"
        f"    image: {tid}:latest  # TODO: ajustar a la imagen real o usar build\n"
        f"    container_name: {tid}_app\n"
        f"    profiles: [\"{COMPOSE_PROFILE}\"]  # no arranca con `docker compose up -d`\n"
        f"    restart: unless-stopped\n"
    )

    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((i for i, ln in enumerate(lines) if _SERVICES.match(ln.rstrip("\r\n"))), None)
    if start is None:
        sep = "\n" if lines else ""
        new_text = "".join(lines) + sep + "services:\n" + block
    else:
        end = next((j for j in range(start + 1, len(lines)) if _TOP_KEY.match(lines[j])), len(lines))
        # no separar los comentarios/espacios que preceden a la siguiente sección
        k = end
        while k > start + 1 and (not lines[k - 1].strip() or lines[k - 1].startswith("#")):
            k -= 1
        tail = lines[k:]
        new_text = "".join(lines[:k]) + "\n" + block + ("\n" if tail and tail[0].strip() else "") + "".join(tail)

    try:
        parsed = yaml.safe_load(new_text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"La insercion del servicio '{tid}' produciria YAML invalido: {e}") from e
    if tid not in (parsed.get("services") or {}):
        raise ValueError(f"La insercion del servicio '{tid}' no quedo dentro de 'services'.")
    COMPOSE_FILE.write_text(new_text, encoding="utf-8")


def activate(tool_id: str, force: bool = False) -> bool:
    """Activa una herramienta (sin desinstalar). Devuelve True si existía.

    Lanza ValueError si no está aprobada (cuarentena, #25) o si compite con una
    herramienta activa (#14, salvo `force=True`).
    """
    state = registry.load_state()
    if tool_id not in state["herramientas"]:
        return False
    estado = quarantine.status(tool_id)
    if estado != quarantine.APROBADA:
        raise ValueError(f"'{tool_id}' esta en estado '{estado}': no se puede activar sin "
                         "escaneo y aprobacion (scan + approve).")
    if registry.get_tool(tool_id) is not None:
        bloq = conflicts.blocking(conflicts.check_conflicts(tool_id))
        if bloq and not force:
            raise ValueError(f"'{tool_id}' compite con herramientas activas: "
                             f"{conflicts.format_conflicts(bloq)}. Usa force=True para activarla igualmente.")
    state["herramientas"][tool_id]["activa"] = True
    registry.save_state(state)
    return True


def deactivate(tool_id: str) -> bool:
    """Desactiva una herramienta (sin desinstalar). Devuelve True si existía."""
    state = registry.load_state()
    if tool_id not in state["herramientas"]:
        return False
    state["herramientas"][tool_id]["activa"] = False
    registry.save_state(state)
    return True


def list_state() -> dict:
    return registry.load_state()
