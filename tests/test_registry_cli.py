"""Tests de los subcomandos nuevos de `registry/cli.py`."""
from registry import cli
from tests.test_registry_helpers import commit_files, make_repo, reg_env  # noqa: F401


def test_rate_tag_top_search(reg_env, capsys):
    assert cli.main(["rate", "llmfit", "5", "--comentario", "ok", "--autor", "ana"]) == 0
    assert cli.main(["rate", "llmfit", "9"]) == 1
    assert cli.main(["tag", "llmfit", "gpu"]) == 0
    assert cli.main(["top", "-n", "3"]) == 0
    assert cli.main(["search", "gpu"]) == 0
    out = capsys.readouterr().out
    assert "media 5.00" in out and "1. llmfit" in out and "tags: gpu" in out


def test_conflicts_cmd(reg_env, capsys):
    assert cli.main(["conflicts", "llmfit"]) == 0
    reg_env.add_tool({"id": "fs2", "tipo": "mcp", "url": "npm:x", "provee": ["filesystem"]})
    assert cli.main(["conflicts", "fs2"]) == 1
    assert "[mcp] con 'filesystem' (ACTIVA)" in capsys.readouterr().out


def test_scan_approve_quarantine_integrate_pin_update_rollback(reg_env, tmp_path, capsys):
    repo, sha1 = make_repo(tmp_path / "origen", {"tool.py": "V = 1\n"})
    reg_env.add_tool({"id": "demo", "tipo": "tool", "url": str(repo)})

    assert cli.main(["activate", "demo"]) == 1                      # sin verificar
    assert cli.main(["integrate", "demo", "--no-bandit"]) == 2      # queda en cuarentena
    assert cli.main(["quarantine"]) == 0
    assert cli.main(["scan", "demo", "--no-bandit"]) == 0
    assert cli.main(["approve", "demo", "--autor", "ana"]) == 0
    assert cli.main(["integrate", "demo", "--no-bandit"]) == 0
    assert cli.main(["activate", "demo"]) == 0

    sha2 = commit_files(repo, {"tool.py": "V = 2\n"}, "v2")
    assert cli.main(["update", "demo", "--no-bandit"]) == 0
    assert cli.main(["rollback", "demo"]) == 0
    assert cli.main(["pin", "demo", sha2, "--no-bandit"]) == 0
    assert cli.main(["update", "demo", "--no-bandit"]) == 1         # fijada
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "[CUARENTENA] demo" in out and "VEREDICTO: aprobado" in out
    assert "aprobada por ana" in out
    assert f"{sha1[:10]} -> {sha2[:10]}" in out and f"{sha2[:10]} -> {sha1[:10]}" in out
    assert "esta fijada" in out
