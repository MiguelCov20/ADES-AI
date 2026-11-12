"""Project Bootstrapper (feature #1).

"Crea un proyecto de X" -> en un comando:
  1. registra el proyecto en el workspace (multi-proyecto #5),
  2. PM genera PRD + tickets y los mete en el backlog (#2),
  3. genera el esqueleto determinista: README, requirements, .gitignore,
     Dockerfile, CI de GitHub Actions, paquete y tests,
  4. la fábrica implementa el primer ticket (Dev⇄QA con sandbox) — opcional,
  5. `git init` + primer commit local, e indexa el código en Neo4j.

Uso:
    python -m agents.bootstrap "tienda online" --descripcion "API de productos y carrito"
"""
import argparse
import subprocess
import sys
from pathlib import Path

from core import projects

GITIGNORE = "__pycache__/\n*.py[cod]\n.venv/\n.env\n.pytest_cache/\n"
DOCKERFILE = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "{pkg}"]
"""
CI = """name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python -m pytest -q
"""


def _pkg(pid: str) -> str:
    return pid.replace("-", "_")


def skeleton(pid: str, nombre: str, descripcion: str, prd: str = "",
             tickets: list | None = None) -> dict[str, str]:
    """Archivos base deterministas (no dependen del LLM)."""
    pkg = _pkg(pid)
    tl = "\n".join(f"- [ ] {t.get('titulo', '')}" for t in (tickets or []))
    readme = (f"# {nombre}\n\n{descripcion}\n\n## Desarrollo\n\n```bash\n"
              "pip install -r requirements.txt\npython -m pytest -q\n```\n"
              + (f"\n## Backlog inicial\n\n{tl}\n" if tl else "")
              + (f"\n## PRD\n\n{prd[:4000]}\n" if prd else "")
              + "\n---\nGenerado por ADES-AI (Project Bootstrapper).\n")
    return {
        "README.md": readme,
        "requirements.txt": "pytest>=8\n",
        ".gitignore": GITIGNORE,
        "Dockerfile": DOCKERFILE.format(pkg=pkg),
        ".github/workflows/ci.yml": CI,
        f"{pkg}/__init__.py": f'"""{nombre}."""\n__version__ = "0.1.0"\n',
        f"{pkg}/__main__.py": f'from {pkg} import __version__\n\nprint("{nombre}", __version__)\n',
        "tests/__init__.py": "",
        "tests/test_smoke.py": (f"import {pkg}\n\n\ndef test_version():\n"
                                f"    assert {pkg}.__version__\n"),
    }


def _git(root: Path, *args) -> bool:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return r.returncode == 0


def bootstrap(nombre: str, descripcion: str = "", implement_first: bool = False,
              plan: bool = True, max_iter: int = 4) -> dict:
    proj = projects.create(nombre, descripcion=descripcion)
    pid, root = proj["id"], Path(proj["path"])
    prd, tickets = "", []
    if plan:
        from agents import backlog
        from agents.pm import pm_node
        out = pm_node({"requerimiento": f"Proyecto '{nombre}': {descripcion}", "project": pid})
        prd, tickets = out["prd"], out["tickets"]
        backlog.add_tickets(pid, tickets, origen=f"bootstrap:{nombre}")
    created = []
    for rel, content in skeleton(pid, nombre, descripcion, prd, tickets).items():
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            created.append(rel)
    result = {"project": pid, "path": str(root), "creados": created,
              "tickets": len(tickets), "prd": prd[:500]}
    if implement_first and tickets:
        from agents import backlog
        result["primer_ticket"] = backlog.work(pid, max_tickets=1, max_iter=max_iter)
    if not (root / ".git").exists():
        _git(root, "init", "-q")
    _git(root, "add", "-A")
    result["commit"] = _git(root, "-c", "user.name=ADES-AI", "-c", "user.email=ades@local",
                            "commit", "-q", "-m", "Bootstrap inicial (ADES-AI)")
    try:
        from memory.indexer import _driver_from_env, index_repo
        d = _driver_from_env()
        try:
            result["indexado"] = index_repo(str(root), d)
        finally:
            d.close()
    except Exception as e:  # noqa: BLE001
        result["indexado"] = f"no disponible: {type(e).__name__}"
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Project Bootstrapper (#1)")
    ap.add_argument("nombre")
    ap.add_argument("--descripcion", default="")
    ap.add_argument("--implementar", action="store_true", help="implementa el primer ticket")
    ap.add_argument("--sin-plan", action="store_true")
    a = ap.parse_args(argv)
    r = bootstrap(a.nombre, a.descripcion, implement_first=a.implementar, plan=not a.sin_plan)
    for k, v in r.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
