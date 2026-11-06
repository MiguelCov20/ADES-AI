"""RepoMap — esqueleto del código desde el grafo Neo4j (ADES-AI, Fase 7).

Genera una representación condensada del repositorio (archivo → clases →
funciones) a partir del grafo de código construido por `memory/indexer.py`.
Permite al agente entender la estructura sin cargar todo el código (ahorro de
~90% del código en contexto).

Uso:
    python -m memory.repomap [--repo <ruta>]
"""
import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def _driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )


def generate_repomap(driver=None) -> str:
    """Genera el RepoMap (texto condensado) a partir del grafo de código."""
    d = driver or _driver()
    with d.session() as s:
        files = s.run(
            "MATCH (f:CodeFile) RETURN f.path AS path ORDER BY f.path"
        ).data()
        classes = s.run(
            "MATCH (c:Class) RETURN c.name AS name, c.path AS path, c.docstring AS doc "
            "ORDER BY c.path"
        ).data()
        funcs = s.run(
            "MATCH (fn:Function) RETURN fn.name AS name, fn.path AS path, fn.kind AS kind, "
            "fn.params AS params ORDER BY fn.path"
        ).data()

    by_file: dict[str, dict] = {}
    for f in files:
        by_file[f["path"]] = {"classes": [], "functions": []}
    for c in classes:
        by_file.setdefault(c["path"], {"classes": [], "functions": []})["classes"].append(c["name"])
    for fn in funcs:
        by_file.setdefault(fn["path"], {"classes": [], "functions": []})["functions"].append(
            f"{fn['name']}({fn['params']})" if fn["kind"] == "function" else fn["name"]
        )

    lines = []
    for path, data in sorted(by_file.items()):
        rel = path.split("ADES-AI")[-1].lstrip("\\/") if "ADES-AI" in path else path
        lines.append(rel)
        for cls in data["classes"]:
            lines.append(f"  class {cls}")
        for f in data["functions"]:
            lines.append(f"  {f}")
    return "\n".join(lines)


def measure_savings(repo_path: str | None = None) -> dict:
    """Compara el tamaño del RepoMap con el código completo (ahorro)."""
    repomap = generate_repomap()
    repomap_chars = len(repomap)

    full_chars = 0
    if repo_path:
        from pathlib import Path
        root = Path(repo_path)
        for f in root.rglob("*.py"):
            if any(p in {"__pycache__", ".git", ".venv", "venv", "site-packages"} for p in f.parts):
                continue
            full_chars += len(f.read_bytes())

    if full_chars == 0:
        full_chars = repomap_chars  # sin repo path, comparación trivial
    return {
        "repomap_chars": repomap_chars,
        "full_code_chars": full_chars,
        "reduction_pct": round(100 * (1 - repomap_chars / full_chars), 1),
        "repomap": repomap,
    }


def main(argv: list[str]) -> int:
    repo = None
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    result = measure_savings(repo)
    print("=== RepoMap (esqueleto del código) ===\n")
    print(result["repomap"])
    print("\n=== Ahorro ===")
    print(f"  RepoMap: {result['repomap_chars']} chars")
    print(f"  Código completo: {result['full_code_chars']} chars")
    print(f"  Reducción: {result['reduction_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
