"""Cliente MCP para el backend LangGraph - ADES-AI, Fase 6.

Conecta el orquestador (Developer, QA, etc.) a los servidores MCP definidos en
`mcp_config.json` mediante el SDK oficial `mcp`. Permite listar herramientas y
llamarlas (p. ej. `filesystem.read_file`, `filesystem.write_file`), con lo que
el Developer puede leer/escribir archivos reales del proyecto.

Uso:
    from mcp_servers import client
    client.list_tools("filesystem")                    # -> ['read_file', 'write_file', ...]
    client.call_tool("filesystem", "read_file", {"path": "README.md"})
"""
import asyncio
import json
import os
import re
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG_PATH = Path(__file__).resolve().parent / "mcp_config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def server_names() -> list[str]:
    return list(load_config()["mcpServers"].keys())


def _resolve_env(env: dict | None) -> dict:
    """Resuelve `${VAR}` desde os.environ; omite los secretos no definidos."""
    out = {}
    for k, v in (env or {}).items():
        m = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", str(v))
        if m:
            val = os.getenv(m.group(1))
            if val is None:
                continue
            out[k] = val
        else:
            out[k] = str(v)
    return out


def _params(name: str) -> StdioServerParameters:
    cfg = load_config()["mcpServers"][name]
    return StdioServerParameters(
        command=cfg["command"],
        args=cfg.get("args", []),
        env=_resolve_env(cfg.get("env")),
    )


async def _list_tools(name: str) -> list[str]:
    async with stdio_client(_params(name)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [t.name for t in result.tools]


def list_tools(name: str) -> list[str]:
    """Lista las herramientas de un servidor MCP (síncrono)."""
    return asyncio.run(_list_tools(name))


async def _call_tool(name: str, tool: str, arguments: dict):
    async with stdio_client(_params(name)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments=arguments)
            return result


def call_tool(name: str, tool: str, arguments: dict):
    """Llama a una herramienta de un servidor MCP (síncrono)."""
    return asyncio.run(_call_tool(name, tool, arguments))


def read_file(path: str) -> str:
    """Lee un archivo real a través del servidor MCP filesystem."""
    result = call_tool("filesystem", "read_file", {"path": str(path)})
    parts = [c.text for c in result.content if hasattr(c, "text")]
    return "\n".join(parts)


def list_directory(path: str) -> list[str]:
    """Lista un directorio real a través del servidor MCP filesystem."""
    result = call_tool("filesystem", "list_directory", {"path": str(path)})
    parts = [c.text for c in result.content if hasattr(c, "text")]
    return parts


def main() -> int:
    print("Servidores MCP configurados:")
    for name in server_names():
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
