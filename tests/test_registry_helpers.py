"""Utilidades compartidas por los tests del Tool Registry (sin tests propios).

`reg_env` redirige TODAS las rutas del registry a `tmp_path` para no tocar
`registry/catalog.json`, `registry/state.json`, `docker-compose.yml`, etc.
`make_repo` crea repos git locales (sin red).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

COMPOSE_SAMPLE = """\
# ADES-AI — Infraestructura de memoria y caché
# Uso: docker compose up -d

services:
  # 1. Base de Datos de Grafos (Neo4j)
  graph_memory:
    image: neo4j:5.23.0
    container_name: neo4j_graphrag
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
    restart: unless-stopped

  gateway:
    image: maximhq/bifrost
    ports:
      - "8080:8080"
    restart: unless-stopped

  # (Espacio reservado para el contenedor de Agentes LangGraph)

volumes:
  neo4j_data:
"""


def git(cwd, *args) -> str:
    p = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=ades-test",
                        "-c", "user.email=ades-test@example.invalid", "-c", "init.defaultBranch=main",
                        *args], cwd=cwd, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def commit_files(repo: Path, files: dict[str, str], msg: str = "commit") -> str:
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def make_repo(path: Path, files: dict[str, str]) -> tuple[Path, str]:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    sha = commit_files(path, files, "inicial")
    return path, sha


class RegEnv:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.catalog = tmp / "catalog.json"
        self.state = tmp / "state.json"
        self.compose = tmp / "docker-compose.yml"
        self.mcp = tmp / "mcp_config.json"
        self.opencode = tmp / "opencode.json"
        self.skills = tmp / "skills"
        self.tools = tmp / "tools"
        self.quarantine = tmp / "quarantine"
        self.ratings = tmp / "ratings.json"

    def add_tool(self, tool: dict) -> dict:
        tool = {"nombre": tool["id"], "descripcion": "", "instalacion": "git clone",
                "licencia": "consultar", **tool}
        cat = json.loads(self.catalog.read_text(encoding="utf-8"))
        cat["herramientas"].append(tool)
        self.catalog.write_text(json.dumps(cat), encoding="utf-8")
        st = json.loads(self.state.read_text(encoding="utf-8"))
        st["herramientas"][tool["id"]] = {"activa": False, "integrada": False}
        self.state.write_text(json.dumps(st), encoding="utf-8")
        return tool

    def load_state(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def entry(self, tool_id: str) -> dict:
        return self.load_state()["herramientas"][tool_id]

    def set_entry(self, tool_id: str, **fields) -> None:
        st = self.load_state()
        st["herramientas"].setdefault(tool_id, {}).update(fields)
        self.state.write_text(json.dumps(st), encoding="utf-8")


@pytest.fixture
def reg_env(tmp_path, monkeypatch):
    from registry import integrator, quarantine, ratings, registry

    env = RegEnv(tmp_path)
    shutil.copy(ROOT / "registry" / "catalog.json", env.catalog)
    cat = json.loads(env.catalog.read_text(encoding="utf-8"))
    env.state.write_text(json.dumps({"version": "1.0", "proyecto": "test", "herramientas": {
        t["id"]: {"activa": False, "integrada": False} for t in cat["herramientas"]}}), encoding="utf-8")
    env.compose.write_text(COMPOSE_SAMPLE, encoding="utf-8")
    env.mcp.write_text(json.dumps({"mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                       "enabled": True}}}), encoding="utf-8")
    env.opencode.write_text(json.dumps({"plugins": []}), encoding="utf-8")

    monkeypatch.setattr(registry, "CATALOG_PATH", env.catalog)
    monkeypatch.setattr(registry, "STATE_PATH", env.state)
    monkeypatch.setattr(integrator, "COMPOSE_FILE", env.compose)
    monkeypatch.setattr(integrator, "MCP_CONFIG", env.mcp)
    monkeypatch.setattr(integrator, "OPENCODE_CONFIG", env.opencode)
    monkeypatch.setattr(integrator, "SKILLS_DIR", env.skills)
    monkeypatch.setattr(integrator, "TOOLS_DIR", env.tools)
    monkeypatch.setattr(quarantine, "QUARANTINE_DIR", env.quarantine)
    monkeypatch.setattr(ratings, "RATINGS_PATH", env.ratings)
    return env
