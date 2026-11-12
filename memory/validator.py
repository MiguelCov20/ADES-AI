"""Validador anti-alucinación contra el grafo de código (Neo4j) — KPI 4.

Analiza el código generado por un agente (AST de Python) y comprueba que toda
referencia a código del PROYECTO exista en el grafo construido por
`memory/indexer.py`:

  - `from agents.llm import get_llm`  -> el módulo `agents.llm` existe y define `get_llm`
  - `import cache.token_metrics`      -> el módulo existe
  - `token_metrics.TokenMetrics(...)` -> el atributo existe en ese módulo
  - `TokenMetrics().record(...)`       -> el método existe en la clase (mejor esfuerzo)

Los módulos de terceros (fastapi, os, ...) no se validan contra el grafo; se
consideran del proyecto los paquetes de primer nivel presentes en el grafo.
"""
import ast
from dataclasses import dataclass, field


@dataclass
class GraphIndex:
    """Vista en memoria del grafo de un repo: módulo -> nombres; clase -> métodos."""
    modules: dict[str, set] = field(default_factory=dict)
    class_methods: dict[str, set] = field(default_factory=dict)  # "mod.Clase" -> {métodos}

    @property
    def top_packages(self) -> set:
        return {m.split(".")[0] for m in self.modules if m}

    @classmethod
    def from_neo4j(cls, driver, repo: str | None = None) -> "GraphIndex":
        idx = cls()
        q = ("MATCH (f:CodeFile) WHERE f.module IS NOT NULL "
             + ("AND f.repo = $repo " if repo else "")
             + "OPTIONAL MATCH (f)-[:CONTAINS]->(x) "
             "RETURN f.module AS module, f.path AS path, f.top_names AS top, "
             "collect(DISTINCT x.name) AS names")
        with driver.session() as s:
            for r in s.run(q, repo=repo):
                names = set(r["names"] or []) | set(r["top"] or [])
                idx.modules.setdefault(r["module"], set()).update(names)
            q2 = ("MATCH (f:CodeFile)-[:CONTAINS]->(c:Class) "
                  + ("WHERE f.repo = $repo " if repo else "")
                  + "OPTIONAL MATCH (c)-[:CONTAINS]->(m:Function) "
                  "RETURN f.module AS module, c.name AS cls, collect(m.name) AS methods")
            for r in s.run(q2, repo=repo):
                idx.class_methods[f"{r['module']}.{r['cls']}"] = set(r["methods"] or [])
        # paquetes intermedios (agents/__init__ puede no existir como CodeFile)
        for m in list(idx.modules):
            parts = m.split(".")
            for i in range(1, len(parts)):
                parent = ".".join(parts[:i])
                idx.modules.setdefault(parent, set()).add(parts[i])
        return idx


@dataclass
class Finding:
    kind: str       # unknown_module | unknown_name | unknown_attribute | unknown_method
    ref: str
    line: int

    def __str__(self) -> str:
        return f"línea {self.line}: {self.kind} -> {self.ref}"


def validate_code(code: str, idx: GraphIndex, local_modules: set | None = None) -> list[Finding]:
    """Devuelve las referencias a código del proyecto que NO existen en el grafo.

    `local_modules`: módulos creados en la misma entrega (p. ej. main.py) que no
    están en el grafo todavía y no deben marcarse.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [Finding("syntax_error", str(e), e.lineno or 0)]
    local_modules = local_modules or set()
    tops = idx.top_packages
    findings: list[Finding] = []
    alias_to_module: dict[str, str] = {}     # nombre local -> módulo del proyecto
    alias_to_class: dict[str, str] = {}      # nombre local -> "mod.Clase"

    def is_project(mod: str) -> bool:
        return mod.split(".")[0] in tops and mod.split(".")[0] not in local_modules

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if is_project(a.name):
                    if a.name not in idx.modules:
                        findings.append(Finding("unknown_module", a.name, node.lineno))
                    else:
                        alias_to_module[a.asname or a.name.split(".")[0]] = (
                            a.name if a.asname else a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mod = node.module
            if not is_project(mod):
                continue
            if mod not in idx.modules:
                findings.append(Finding("unknown_module", mod, node.lineno))
                continue
            for a in node.names:
                if a.name == "*":
                    continue
                sub = f"{mod}.{a.name}"
                if a.name in idx.modules[mod] or sub in idx.modules:
                    local = a.asname or a.name
                    if sub in idx.modules:
                        alias_to_module[local] = sub
                    if f"{mod}.{a.name}" in idx.class_methods:
                        alias_to_class[local] = f"{mod}.{a.name}"
                else:
                    findings.append(Finding("unknown_name", f"{mod}.{a.name}", node.lineno))

    # Atributos: modulo.Nombre y Clase.metodo / Clase().metodo
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id in alias_to_module:
            mod = alias_to_module[base.id]
            if node.attr not in idx.modules.get(mod, set()) and f"{mod}.{node.attr}" not in idx.modules:
                findings.append(Finding("unknown_attribute", f"{mod}.{node.attr}", node.lineno))
        cls = None
        if isinstance(base, ast.Name) and base.id in alias_to_class:
            cls = alias_to_class[base.id]
        elif (isinstance(base, ast.Call) and isinstance(base.func, ast.Name)
              and base.func.id in alias_to_class):
            cls = alias_to_class[base.func.id]
        if cls and not node.attr.startswith("__"):
            methods = idx.class_methods.get(cls, set())
            if methods and node.attr not in methods:
                findings.append(Finding("unknown_method", f"{cls}.{node.attr}", node.lineno))
    # dedupe
    seen, out = set(), []
    for f in findings:
        k = (f.kind, f.ref)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def validate_files(files: dict[str, str], idx: GraphIndex) -> dict[str, list[Finding]]:
    """Valida varios archivos generados. Ignora los módulos que la propia entrega crea."""
    local = {p.rsplit("/", 1)[-1].removesuffix(".py") for p in files if p.endswith(".py")}
    local |= {p.split("/")[0] for p in files if "/" in p}
    return {p: validate_code(c, idx, local) for p, c in files.items() if p.endswith(".py")}
