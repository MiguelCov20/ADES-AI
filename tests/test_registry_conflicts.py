"""Tests del detector de conflictos (#14)."""
import pytest

from registry import conflicts, integrator, quarantine
from tests.test_registry_helpers import reg_env  # noqa: F401


def _aprobar(env, tool_id):
    env.set_entry(tool_id, estado=quarantine.APROBADA)


def test_pilotos_tienen_provee_y_sin_conflictos(reg_env):
    from registry import registry
    for t in registry.get_tools():
        assert t.get("provee"), f"{t['id']} sin campo provee"
        assert conflicts.check_conflicts(t["id"]) == []


def test_misma_capacidad(reg_env):
    reg_env.add_tool({"id": "otro-fit", "tipo": "tool", "url": "x",
                      "provee": ["Recomendacion-Modelos"]})
    c = conflicts.check_conflicts("otro-fit")
    assert len(c) == 1 and c[0]["tipo"] == "capacidad" and c[0]["con"] == "llmfit"
    assert c[0]["activa"] is False and conflicts.blocking(c) == []


def test_dos_mcp_filesystem(reg_env):
    reg_env.add_tool({"id": "fs2", "tipo": "mcp", "url": "npm:otro-fs", "provee": ["filesystem"]})
    c = conflicts.check_conflicts("fs2")
    assert [(x["tipo"], x["con"], x["activa"]) for x in c] == [("mcp", "filesystem", True)]


def test_mismo_puerto_compose_y_catalogo(reg_env):
    reg_env.add_tool({"id": "app1", "tipo": "app", "url": "x", "puertos": ["8080:80"]})
    reg_env.add_tool({"id": "app2", "tipo": "app", "url": "y", "puertos": [8080]})
    c = conflicts.check_conflicts("app1")
    tipos = {(x["tipo"], x["con"]) for x in c}
    assert ("puerto", "gateway") in tipos and ("puerto", "app2") in tipos
    assert any(x["con"] == "gateway" and x["activa"] for x in c)


def test_mismo_nombre_de_skill(reg_env):
    reg_env.add_tool({"id": "ecc-fork", "tipo": "skill", "url": "x", "nombre": "ECC (Everything Claude Code)"})
    c = conflicts.check_conflicts("ecc-fork")
    assert ("skill", "ecc") in {(x["tipo"], x["con"]) for x in c}
    # skill local con el mismo id no gestionada por el registry
    (reg_env.skills / "ecc").mkdir(parents=True)
    assert any(x["tipo"] == "skill" and x["activa"] for x in conflicts.check_conflicts("ecc"))


def test_activate_se_niega_con_conflicto_activo(reg_env):
    reg_env.add_tool({"id": "otro-fit", "tipo": "tool", "url": "x", "provee": ["deteccion-hardware"]})
    _aprobar(reg_env, "llmfit")
    _aprobar(reg_env, "otro-fit")
    assert integrator.activate("llmfit") is True
    with pytest.raises(ValueError, match="compite"):
        integrator.activate("otro-fit")
    assert reg_env.entry("otro-fit")["activa"] is False
    assert integrator.activate("otro-fit", force=True) is True


def test_integrate_se_niega_con_conflicto_activo(reg_env):
    reg_env.add_tool({"id": "fs2", "tipo": "mcp", "url": "npm:otro-fs", "provee": ["filesystem"]})
    with pytest.raises(ValueError, match="compite"):
        integrator.integrate("fs2", dry_run=False)
    # dry-run informa sin bloquear
    assert integrator.integrate("fs2", dry_run=True)["conflictos"]
    # con force pasa (y acaba en cuarentena porque no está aprobada)
    assert integrator.integrate("fs2", dry_run=False, force=True)["cuarentena"] is True
