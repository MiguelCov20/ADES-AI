"""Tests del modo cuarentena (#25) y su integración con el escaneo (#16)."""
import pytest

from registry import integrator, quarantine
from tests.test_registry_helpers import commit_files, make_repo, reg_env  # noqa: F401

LIMPIO = {"tool.py": "def run():\n    return 'ok'\n"}


@pytest.fixture
def tool_repo(reg_env, tmp_path):
    repo, sha = make_repo(tmp_path / "origen", LIMPIO)
    reg_env.add_tool({"id": "demo", "tipo": "tool", "url": str(repo)})
    return repo, sha


def test_no_verificada_no_se_activa(reg_env):
    with pytest.raises(ValueError, match="sin_verificar"):
        integrator.activate("llmfit")
    assert reg_env.entry("llmfit")["activa"] is False


def test_integrate_deja_en_cuarentena(reg_env, tool_repo):
    _, sha = tool_repo
    r = integrator.integrate("demo", dry_run=False, use_bandit=False)
    assert r["cuarentena"] is True and r["ejecutado"] is False and r["veredicto"] == "aprobado"
    assert quarantine.status("demo") == quarantine.CUARENTENA
    assert (reg_env.quarantine / "demo" / "tool.py").exists()      # clonado en cuarentena
    assert not (reg_env.tools / "demo").exists()                   # NO en su destino
    assert quarantine.load_report("demo")["commit"] == sha
    with pytest.raises(ValueError, match="cuarentena"):
        integrator.activate("demo")
    assert [q["id"] for q in quarantine.list_quarantine()] == ["demo"]


def test_approve_requiere_escaneo_y_autor(reg_env, tool_repo):
    with pytest.raises(ValueError, match="escaneada"):
        quarantine.approve("demo", "ana")
    quarantine.scan("demo", use_bandit=False)
    with pytest.raises(ValueError, match="autor"):
        quarantine.approve("demo", "  ")


def test_flujo_completo_aprobar_integrar_activar(reg_env, tool_repo):
    _, sha = tool_repo
    integrator.integrate("demo", dry_run=False, use_bandit=False)
    a = quarantine.approve("demo", "ana")
    assert a["autor"] == "ana" and a["commit"] == sha and a["forzada"] is False
    assert quarantine.list_quarantine() == []
    r = integrator.integrate("demo", dry_run=False, use_bandit=False)
    assert r["ejecutado"] is True
    assert (reg_env.tools / "demo" / "tool.py").exists()
    e = reg_env.entry("demo")
    assert e["integrada"] is True and e["commit"] == sha and e["estado"] == "aprobada"
    assert integrator.activate("demo") is True


def test_se_instala_el_commit_aprobado_aunque_el_origen_avance(reg_env, tool_repo):
    repo, sha = tool_repo
    quarantine.scan("demo", use_bandit=False)
    quarantine.approve("demo", "ana")
    commit_files(repo, {"tool.py": "# version nueva sin escanear\n"}, "nuevo")
    integrator.integrate("demo", dry_run=False, use_bandit=False)
    assert reg_env.entry("demo")["commit"] == sha
    assert "def run" in (reg_env.tools / "demo" / "tool.py").read_text(encoding="utf-8")


def test_rechazada_no_se_aprueba_sin_force(reg_env, tmp_path):
    repo, _ = make_repo(tmp_path / "malo", {"x.sh": "echo k >> ~/.ssh/authorized_keys\n"})
    reg_env.add_tool({"id": "malo", "tipo": "tool", "url": str(repo)})
    r = integrator.integrate("malo", dry_run=False, use_bandit=False)
    assert r["veredicto"] == "rechazado" and r["estado"] == quarantine.RECHAZADA
    with pytest.raises(ValueError, match="RECHAZADA"):
        quarantine.approve("malo", "ana")
    a = quarantine.approve("malo", "ana", force=True)
    assert a["forzada"] is True and quarantine.is_approved("malo")


def test_reescaneo_de_commit_nuevo_revoca_aprobacion(reg_env, tool_repo):
    repo, _ = tool_repo
    quarantine.scan("demo", use_bandit=False)
    quarantine.approve("demo", "ana")
    quarantine.scan("demo", use_bandit=False)          # mismo commit: sigue aprobada
    assert quarantine.is_approved("demo")
    commit_files(repo, {"nuevo.py": "x = 1\n"}, "nuevo")
    quarantine.scan("demo", use_bandit=False, refresh=True)
    assert quarantine.status("demo") == quarantine.CUARENTENA


@pytest.mark.live
def test_scan_con_bandit_en_docker(reg_env, tmp_path):
    repo, _ = make_repo(tmp_path / "bandit-repo",
                        {"a.py": "import subprocess\nsubprocess.call(x, shell=True)\n"})
    reg_env.add_tool({"id": "br", "tipo": "tool", "url": str(repo)})
    inf = quarantine.scan("br", use_bandit=True)
    assert inf["bandit"]["ejecutado"] is True, inf["bandit"]
    assert any(h["origen"] == "bandit" and h["regla"] == "B602" for h in inf["hallazgos"])
    assert inf["veredicto"] == "cuarentena" and quarantine.status("br") == quarantine.CUARENTENA
