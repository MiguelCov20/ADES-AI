"""Indexador de código: Tree-sitter -> Neo4j (ADES-AI, Fase 2).

Analiza un repositorio (por ahora Python) con Tree-sitter y escribe la
estructura (archivos, clases, funciones, imports, herencia y llamadas) en el
grafo de Neo4j. Es determinista (sin LLM): sirve de "RepoMap" anti-alucinación
para los agentes.

Uso:
    python memory/indexer.py --repo <ruta> [--reset] [--summary]
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from tree_sitter import Language, Parser
import tree_sitter_python

from memory import schemas

# --- helpers de Tree-sitter -------------------------------------------------

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "ignore")


def _named(node) -> Optional[Any]:
    """Devuelve el primer hijo con nombre (o None)."""
    for child in node.children:
        if child.is_named:
            return child
    return None


def _extract_docstring(body_node, src: bytes) -> str:
    """Docstring de un cuerpo (primera sentencia expression_statement -> string)."""
    for child in body_node.children:
        if child.type == "expression_statement":
            s = _named(child)
            if s is not None and s.type == "string":
                return _text(s, src).strip('"\'').strip()
        elif child.is_named:
            break  # la primera sentencia nombrada no es el docstring
    return ""


# --- Extracción -------------------------------------------------------------

def _walk(node, src: bytes, path: str, owner: str, out: dict) -> None:
    """Recorre el AST acumulando clases, funciones e imports."""
    if node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        full = f"{path}::{name}"
        superclasses = []
        sup = node.child_by_field_name("superclasses")
        if sup is not None:
            for sc in sup.children:
                if sc.type in ("identifier", "attribute"):
                    superclasses.append(_text(sc, src))
        body = node.child_by_field_name("body")
        doc = _extract_docstring(body, src) if body is not None else ""
        out["classes"].append({
            "full_name": full,
            "name": name,
            "superclasses": superclasses,
            "docstring": doc,
            "path": path,
        })
        if body is not None:
            _walk(body, src, path, name, out)  # métodos heredan owner = nombre de clase
        return

    if node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        full = f"{path}::{owner}.{name}" if owner else f"{path}::{name}"
        params = node.child_by_field_name("parameters")
        n_params = sum(1 for c in params.children if c.is_named) if params else 0
        body = node.child_by_field_name("body")
        doc = _extract_docstring(body, src) if body is not None else ""
        calls = _collect_calls(body, src) if body is not None else []
        out["functions"].append({
            "full_name": full,
            "name": name,
            "kind": "method" if owner else "function",
            "owner": owner,
            "params": n_params,
            "docstring": doc,
            "calls": calls,
            "path": path,
        })
        if body is not None:
            _walk(body, src, path, "", out)  # funciones anidadas no llevan owner de clase
        return

    if node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                out["imports"].append(_text(child, src))
            elif child.type == "aliased_import":
                dn = _named(child)
                if dn is not None and dn.type == "dotted_name":
                    out["imports"].append(_text(dn, src))
        return

    if node.type == "import_from_statement":
        mod = node.child_by_field_name("module_name")
        if mod is not None:
            out["imports"].append(_text(mod, src))
        return

    # recursión general (no descendemos dentro de class/function que ya manejamos)
    for child in node.children:
        if child.type in ("class_definition", "function_definition",
                          "import_statement", "import_from_statement"):
            _walk(child, src, path, owner, out)
        elif child.is_named:
            _walk(child, src, path, owner, out)


def _collect_calls(body_node, src: bytes) -> list[str]:
    """Nombres de funciones llamadas dentro de un cuerpo (mejor esfuerzo)."""
    calls: list[str] = []

    def rec(n):
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                calls.append(_text(fn, src))
        for c in n.children:
            rec(c)

    rec(body_node)
    return calls


def parse_file(path: Path) -> dict:
    """Analiza un archivo .py y devuelve clases, funciones e imports."""
    src = path.read_bytes()
    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(src)
    out: dict = {"path": str(path), "classes": [], "functions": [], "imports": []}
    _walk(tree.root_node, src, str(path), "", out)
    return out


# --- Escritura a Neo4j ------------------------------------------------------

def _write(driver, parsed: dict) -> None:
    """Escribe un archivo analizado en Neo4j (idempotente vía MERGE)."""
    path = parsed["path"]
    language = "python" if path.endswith(".py") else "unknown"

    with driver.session() as session:
        session.run(
            "MERGE (f:CodeFile {path: $path}) "
            "SET f.name = $name, f.language = $language",
            path=path, name=Path(path).name, language=language,
        )

        for m in set(parsed["imports"]):
            session.run(
                "MERGE (mod:Module {name: $name})",
                name=m,
            )
            session.run(
                "MATCH (f:CodeFile {path: $path}), (mod:Module {name: $name}) "
                "MERGE (f)-[:IMPORTS]->(mod)",
                path=path, name=m,
            )

        for cls in parsed["classes"]:
            session.run(
                "MERGE (c:Class {full_name: $full_name}) "
                "SET c.name = $name, c.path = $path, c.docstring = $doc",
                full_name=cls["full_name"], name=cls["name"],
                path=cls["path"], doc=cls["docstring"],
            )
            session.run(
                "MATCH (f:CodeFile {path: $path}), (c:Class {full_name: $full_name}) "
                "MERGE (f)-[:CONTAINS]->(c)",
                path=path, full_name=cls["full_name"],
            )
            for sup in cls["superclasses"]:
                session.run(
                    "MATCH (c:Class {full_name: $full_name}), (s:Class {name: $sup}) "
                    "MERGE (c)-[:INHERITS]->(s)",
                    full_name=cls["full_name"], sup=sup,
                )

        for fn in parsed["functions"]:
            session.run(
                "MERGE (fn:Function {full_name: $full_name}) "
                "SET fn.name = $name, fn.kind = $kind, fn.path = $path, "
                "fn.params = $params, fn.docstring = $doc, fn.calls = $calls",
                full_name=fn["full_name"], name=fn["name"], kind=fn["kind"],
                path=fn["path"], params=fn["params"], doc=fn["docstring"],
                calls=fn["calls"],
            )
            if fn["owner"]:
                owner_fqn = f"{path}::{fn['owner']}"
                session.run(
                    "MATCH (c:Class {full_name: $owner}), (fn:Function {full_name: $full_name}) "
                    "MERGE (c)-[:CONTAINS]->(fn)",
                    owner=owner_fqn, full_name=fn["full_name"],
                )
            else:
                session.run(
                    "MATCH (f:CodeFile {path: $path}), (fn:Function {full_name: $full_name}) "
                    "MERGE (f)-[:CONTAINS]->(fn)",
                    path=path, full_name=fn["full_name"],
                )


def index_repo(repo_path: str, driver, reset: bool = False, verbose: bool = False) -> dict:
    """Indexa todos los .py de un repo y devuelve un resumen de conteos."""
    root = Path(repo_path).resolve()
    if reset:
        schemas.clear_graph(driver)
    schemas.init_schema(driver)

    files = sorted(root.rglob("*.py"))
    counts = {"files": 0, "classes": 0, "functions": 0, "imports": 0}

    for f in files:
        # evitar __pycache__, venv, .git
        if any(part in {"__pycache__", ".git", ".venv", "venv", "site-packages"}
               for part in f.parts):
            continue
        try:
            parsed = parse_file(f)
        except Exception as e:
            if verbose:
                print(f"  [skip] {f}: {e}")
            continue
        _write(driver, parsed)
        counts["files"] += 1
        counts["classes"] += len(parsed["classes"])
        counts["functions"] += len(parsed["functions"])
        counts["imports"] += len(set(parsed["imports"]))
        if verbose:
            print(f"  [ok] {f.relative_to(root)}: "
                  f"{len(parsed['classes'])} clases, {len(parsed['functions'])} funciones")

    return counts


# --- CLI --------------------------------------------------------------------

def _driver_from_env():
    load_dotenv()
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "")
    return GraphDatabase.driver(uri, auth=(user, pwd))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Indexa un repo en el grafo de Neo4j (Fase 2)")
    ap.add_argument("--repo", required=True, help="ruta del repositorio a indexar")
    ap.add_argument("--reset", action="store_true", help="limpia el grafo antes de indexar")
    ap.add_argument("--summary", action="store_true", help="muestra un resumen del grafo")
    args = ap.parse_args(argv)

    driver = _driver_from_env()
    try:
        driver.verify_connectivity()
        counts = index_repo(args.repo, driver, reset=args.reset, verbose=True)
        print("\n=== Resumen de indexado ===")
        print(f"  archivos : {counts['files']}")
        print(f"  clases   : {counts['classes']}")
        print(f"  funciones: {counts['functions']}")
        print(f"  imports  : {counts['imports']}")

        if args.summary:
            with driver.session() as session:
                r = session.run(
                    "MATCH (f:CodeFile) RETURN count(f) AS files").single()
                c = session.run(
                    "MATCH (c:Class) RETURN count(c) AS n").single()
                fn = session.run(
                    "MATCH (x:Function) RETURN count(x) AS n").single()
                m = session.run(
                    "MATCH (x:Module) RETURN count(x) AS n").single()
                print("\n=== Estado del grafo (Neo4j) ===")
                print(f"  CodeFile: {r['files']}, Class: {c['n']}, "
                      f"Function: {fn['n']}, Module: {m['n']}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
