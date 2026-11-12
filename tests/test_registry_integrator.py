"""Tests del integrador: bugs de docker-compose (app) y mcp_config (mcp)."""
import json
import subprocess

import pytest
import yaml

from registry import integrator, quarantine
from tests.test_registry_helpers import ROOT, make_repo, reg_env  # noqa: F401


# ---------- Bug 1: servicio app en docker-compose.yml ----------

def test_app_service_dentro_de_services_y_yaml_valido(reg_env):
    integrator._add_app_service("llm-council", "https://github.com/karpathy/llm-council")
    data = yaml.safe_load(reg_env.compose.read_text(encoding="utf-8"))
    svc = data["services"]["llm-council"]
    assert svc["profiles"] == ["registry"]
    assert svc["image"] == "llm-council:latest"
    # el volumes anidado de neo4j y el volumes de nivel superior siguen intactos
    assert data["services"]["graph_memory"]["volumes"] == ["neo4j_data:/data"]
    assert "neo4j_data" in data["volumes"]
    assert "llm-council" not in (data["volumes"] or {})


def test_app_service_idempotente_y_varios(reg_env):
    integrator._add_app_service("app-a", "u1")
    integrator._add_app_service("app-a", "u1")
    integrator._add_app_service("app-b", "u2")
    text = reg_env.compose.read_text(encoding="utf-8")
    assert text.count("\n  app-a:\n") == 1
    data = yaml.safe_load(text)
    assert {"app-a", "app-b", "graph_memory", "gateway"} <= set(data["services"])
    # se preservan los comentarios
    assert "# (Espacio reservado para el contenedor de Agentes LangGraph)" in text


def test_app_service_compose_real_del_repo(reg_env):
    """El docker-compose.yml real del repo (copia) sigue siendo válido tras insertar."""
    reg_env.compose.write_text((ROOT / "docker-compose.yml").read_text(encoding="utf-8"), encoding="utf-8")
    integrator._add_app_service("llm-council", "https://github.com/karpathy/llm-council")
    data = yaml.safe_load(reg_env.compose.read_text(encoding="utf-8"))
    assert "llm-council" in data["services"]
    assert data["services"]["llm-council"]["profiles"] == ["registry"]


def test_app_service_sin_seccion_services(reg_env):
    reg_env.compose.write_text("volumes:\n  datos:\n", encoding="utf-8")
    integrator._add_app_service("app-x", "u")
    data = yaml.safe_load(reg_env.compose.read_text(encoding="utf-8"))
    assert "app-x" in data["services"] and "datos" in data["volumes"]


def test_app_service_compose_invalido_no_se_toca(reg_env):
    roto = "services:\n  a: [\n"
    reg_env.compose.write_text(roto, encoding="utf-8")
    with pytest.raises(ValueError):
        integrator._add_app_service("app-x", "u")
    assert reg_env.compose.read_text(encoding="utf-8") == roto


@pytest.mark.live
def test_app_service_docker_compose_config(reg_env):
    """`docker compose config` acepta el archivo y el perfil excluye el placeholder."""
    integrator._add_app_service("llm-council", "https://github.com/karpathy/llm-council")
    base = ["docker", "compose", "-f", str(reg_env.compose)]
    sin_perfil = subprocess.run(base + ["config", "--services"], capture_output=True, text=True)
    assert sin_perfil.returncode == 0, sin_perfil.stderr
    assert "llm-council" not in sin_perfil.stdout.split()
    assert "graph_memory" in sin_perfil.stdout.split()
    con_perfil = subprocess.run(base + ["--profile", "registry", "config", "--services"],
                                capture_output=True, text=True)
    assert con_perfil.returncode == 0, con_perfil.stderr
    assert "llm-council" in con_perfil.stdout.split()


# ---------- Bug 2: entrada MCP ----------

def test_mcp_entry_desde_catalogo():
    e = integrator.mcp_entry({"id": "x", "url": "https://github.com/a/b",
                              "mcp_command": "uvx", "mcp_args": ["mcp-server-x"]})
    assert e == {"command": "uvx", "args": ["mcp-server-x"], "enabled": True}


@pytest.mark.parametrize("url,pkg", [
    ("npm:firecrawl-mcp", "firecrawl-mcp"),
    ("@modelcontextprotocol/server-memory", "@modelcontextprotocol/server-memory"),
    ("https://www.npmjs.com/package/@scope/pkg", "@scope/pkg"),
])
def test_mcp_entry_npm(url, pkg):
    e = integrator.mcp_entry({"id": "x", "url": url})
    assert e == {"command": "npx", "args": ["-y", pkg], "enabled": True}


def test_mcp_entry_github_queda_deshabilitada():
    e = integrator.mcp_entry({"id": "mi-mcp", "url": "https://github.com/a/mi-mcp"})
    assert e["enabled"] is False
    assert e["_pendiente"] == "definir comando de arranque"
    assert "command" not in e  # nunca npx <url de github>


def test_integrar_mcp_github_clona_y_deja_pendiente(reg_env, tmp_path):
    repo, sha = make_repo(tmp_path / "src-mcp", {"server.py": "print('mcp')\n"})
    reg_env.add_tool({"id": "mi-mcp", "tipo": "mcp", "url": str(repo)})

    r1 = integrator.integrate("mi-mcp", dry_run=False, use_bandit=False)
    assert r1["cuarentena"] is True and r1["ejecutado"] is False
    assert "mi-mcp" not in json.loads(reg_env.mcp.read_text())["mcpServers"]

    quarantine.approve("mi-mcp", "tester")
    r2 = integrator.integrate("mi-mcp", dry_run=False, use_bandit=False)
    assert r2["ejecutado"] is True
    entry = json.loads(reg_env.mcp.read_text())["mcpServers"]["mi-mcp"]
    assert entry["enabled"] is False and entry["_pendiente"]
    assert (reg_env.tools / "mi-mcp" / "server.py").exists()
    assert reg_env.entry("mi-mcp")["commit"] == sha
    # la entrada existente no se pisa
    assert json.loads(reg_env.mcp.read_text())["mcpServers"]["filesystem"]["enabled"] is True


def test_integrar_mcp_npm(reg_env):
    reg_env.add_tool({"id": "mem", "tipo": "mcp", "url": "npm:@modelcontextprotocol/server-memory"})
    r1 = integrator.integrate("mem", dry_run=False)
    assert r1["cuarentena"] is True and r1["veredicto"] == "cuarentena"
    assert "no es un repositorio git" in quarantine.load_report("mem")["nota"]
    quarantine.approve("mem", "tester")
    integrator.integrate("mem", dry_run=False)
    entry = json.loads(reg_env.mcp.read_text())["mcpServers"]["mem"]
    assert entry == {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"], "enabled": True}


def test_dry_run_sin_efectos(reg_env):
    r = integrator.integrate("llm-council", dry_run=True)
    assert r["ejecutado"] is False and r["metodo"] == "app"
    assert "perfil 'registry'" in r["plan"]
    assert "llm-council" not in reg_env.compose.read_text(encoding="utf-8")
    assert not reg_env.quarantine.exists()
