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
"""
import json
import subprocess
from pathlib import Path

from registry import registry

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / ".opencode" / "skills"
TOOLS_DIR = ROOT / "registry" / "tools"
MCP_CONFIG = ROOT / "mcp_servers" / "mcp_config.json"
OPENCODE_CONFIG = ROOT / "opencode.json"
COMPOSE_FILE = ROOT / "docker-compose.yml"

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


def method_for(tool: dict) -> str:
    return TYPE_TO_METHOD.get(tool.get("tipo", "tool"), "tool")


def integrate(tool_id: str, dry_run: bool = True) -> dict:
    """Integra una herramienta. Devuelve {id, tipo, metodo, plan, ejecutado}."""
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")

    metodo = method_for(tool)
    plan = _plan(tool, metodo)

    if dry_run:
        return {"id": tool_id, "tipo": tool["tipo"], "metodo": metodo,
                "plan": plan, "ejecutado": False}

    _execute(tool, metodo)

    # marcar como integrada en el estado
    state = registry.load_state()
    state["herramientas"].setdefault(tool_id, {})
    state["herramientas"][tool_id]["integrada"] = True
    registry.save_state(state)

    return {"id": tool_id, "tipo": tool["tipo"], "metodo": metodo,
            "plan": plan, "ejecutado": True}


def _plan(tool: dict, metodo: str) -> str:
    url = tool["url"]
    tid = tool["id"]
    if metodo == "skill":
        return f"git clone {url} {SKILLS_DIR / tid}"
    if metodo == "mcp":
        return f"anadir entrada '{tid}' a {MCP_CONFIG.relative_to(ROOT)}"
    if metodo == "tool":
        return f"git clone {url} {TOOLS_DIR / tid}"
    if metodo == "plugin":
        return f"registrar '{tid}' en {OPENCODE_CONFIG.relative_to(ROOT)} -> plugins"
    if metodo == "model":
        return f"ollama pull {tid}"
    if metodo == "app":
        return f"anadir servicio '{tid}' a {COMPOSE_FILE.relative_to(ROOT)}"
    return "metodo desconocido"


def _execute(tool: dict, metodo: str) -> None:
    url = tool["url"]
    tid = tool["id"]
    if metodo == "skill":
        target = SKILLS_DIR / tid
        if not target.exists():
            subprocess.run(["git", "clone", "--depth", "1", url, str(target)], check=True)
    elif metodo == "tool":
        target = TOOLS_DIR / tid
        if not target.exists():
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--depth", "1", url, str(target)], check=True)
    elif metodo == "plugin":
        _add_plugin(tid, url)
    elif metodo == "mcp":
        _add_mcp(tid, url)
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


def _add_mcp(tid: str, url: str) -> None:
    MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if MCP_CONFIG.exists():
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    else:
        cfg = {"mcpServers": {}}
    servers = cfg.setdefault("mcpServers", {})
    if tid not in servers:
        servers[tid] = {"command": "npx", "args": [url], "enabled": True}
        MCP_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _add_app_service(tid: str, url: str) -> None:
    """Añade un servicio al docker-compose.yml (integración tipo 'app').

    Inserta un bloque de servicio antes de la sección `volumes:`, preservando
    los comentarios existentes. La imagen queda como `{tid}:latest` (placeholder)
    porque la imagen real del repo hay que confirmarla; se deja un TODO con la
    URL para ajustarla.
    """
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    if f"\n  {tid}:\n" in text:
        return  # ya existe

    block = (
        f"  # App integrada via Tool Registry: {tid}\n"
        f"  {tid}:\n"
        f"    image: {tid}:latest  # TODO: ajustar a la imagen real ({url})\n"
        f"    container_name: {tid}_app\n"
        f"    restart: unless-stopped\n"
    )
    if "volumes:" in text:
        text = text.replace("volumes:", block + "\nvolumes:", 1)
    else:
        text = text.rstrip() + "\n\n" + block
    COMPOSE_FILE.write_text(text, encoding="utf-8")


def activate(tool_id: str) -> bool:
    """Activa una herramienta (sin desinstalar). Devuelve True si existía."""
    state = registry.load_state()
    if tool_id not in state["herramientas"]:
        return False
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
