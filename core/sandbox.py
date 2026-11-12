"""Sandbox Docker efímero (regla 5 de AGENTS.md: QA nunca ejecuta fuera de Docker).

- `extract_files(texto)`: extrae los archivos que entrega el Developer
  (bloques ``` con `# FILE: ruta` o `# ruta.py` en la primera línea).
- `run_tests(files)`: copia los archivos a un directorio temporal y ejecuta
  `pytest` dentro del contenedor `ades-sandbox:py311` con `--network none`,
  sin privilegios y con límites de CPU/RAM/tiempo.
- `run_command(files, cmd)`: igual, para otros comandos (bandit, py_compile...).

Lo usan QA (bucle Dev⇄QA), la instalación en sandbox del Tool Registry (#16),
el benchmark harness (#17) y la auditoría anti-IA (#24).
"""
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from core.config import global_state_dir

IMAGE = "ades-sandbox:py311"
DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "environment" / "sandbox"

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\n(.*?)```", re.S)
_HEADER = re.compile(
    r"^\s*(?:#|//)\s*(?:FILE:\s*)?([\w./-]+\.(?:py|txt|toml|cfg|ini|json|ya?ml|md))\s*$",
    re.I)
_TITLE = re.compile(r"(?:FILE:|Archivo:|File:)\s*`?([\w./-]+\.\w+)`?", re.I)


@dataclass
class SandboxResult:
    passed: bool
    exit_code: int
    output: str
    tests_run: int = 0
    tests_failed: int = 0
    timed_out: bool = False


def extract_files(text: str) -> dict[str, str]:
    """Extrae {ruta: contenido} de la respuesta del Developer."""
    files: dict[str, str] = {}
    for m in _FENCE.finditer(text):
        body = m.group(1)
        lines = body.splitlines()
        name = None
        if lines:
            h = _HEADER.match(lines[0])
            if h:
                name = h.group(1)
                body = "\n".join(lines[1:]) + "\n"
        if name is None:  # título justo antes del bloque: "FILE: main.py" / "### main.py"
            before = text[max(0, m.start() - 200):m.start()].strip().splitlines()
            if before:
                t = _TITLE.search(before[-1]) or re.search(r"([\w./-]+\.py)\b", before[-1])
                if t:
                    name = t.group(1)
        if name is None:
            continue
        name = name.lstrip("./").replace("\\", "/")
        if ".." in name.split("/"):
            continue  # nunca escribir fuera del directorio de trabajo
        files[name] = body
    if not files and "def " in text and "```" not in text:
        files["main.py"] = text  # código sin bloques
    if not files:  # un único bloque python sin nombre
        blocks = [b for b in _FENCE.findall(text) if "def " in b or "import " in b]
        if len(blocks) == 1:
            files["main.py"] = blocks[0]
    return files


def image_available() -> bool:
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return r.returncode == 0


def ensure_image() -> None:
    if not image_available():
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(DOCKERFILE_DIR)],
                       check=True, capture_output=True)


def _workdir(files: dict[str, str]) -> Path:
    d = global_state_dir() / "sandbox" / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def run_command(files: dict[str, str], cmd: list[str], timeout: int = 180,
                network: bool = False, keep: bool = False) -> SandboxResult:
    """Ejecuta `cmd` dentro del contenedor con los archivos montados en /work."""
    ensure_image()
    work = _workdir(files)
    name = f"ades-sbx-{uuid.uuid4().hex[:10]}"
    docker_cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "bridge" if network else "none",
        "--memory", "768m", "--cpus", "1.5", "--pids-limit", "256",
        "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{work}:/work", "-w", "/work", IMAGE, *cmd,
    ]
    try:
        p = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        out = (p.stdout + "\n" + p.stderr).strip()
        res = SandboxResult(passed=p.returncode == 0, exit_code=p.returncode, output=out[-60000:])
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        res = SandboxResult(passed=False, exit_code=-1, output="TIMEOUT", timed_out=True)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return res


_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors)")


def run_tests(files: dict[str, str], timeout: int = 180) -> SandboxResult:
    """Ejecuta pytest en el sandbox. Sin tests -> compila e importa los módulos."""
    has_tests = any(Path(n).name.startswith("test_") or Path(n).name.endswith("_test.py")
                    for n in files)
    if has_tests:
        res = run_command(files, ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                  "--no-header"], timeout=timeout)
        counts = {"passed": 0, "failed": 0, "error": 0}
        for n, kind in _SUMMARY.findall(res.output):
            counts["error" if kind.startswith("error") else kind] += int(n)
        res.tests_run = counts["passed"] + counts["failed"] + counts["error"]
        res.tests_failed = counts["failed"] + counts["error"]
        if res.exit_code == 5:  # pytest: no se recolectaron tests
            res.passed = False
        return res
    mods = [n for n in files if n.endswith(".py")]
    code = ("import importlib.util,sys\nsys.path.insert(0,'.')\n"
            "for f in %r:\n"
            "    s=importlib.util.spec_from_file_location(f[:-3].replace('/','.'),f)\n"
            "    m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "print('IMPORT_OK')\n") % mods
    return run_command({**files, "_ades_import_check.py": code},
                       ["python", "_ades_import_check.py"], timeout=timeout)
