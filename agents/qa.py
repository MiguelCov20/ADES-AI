"""Nodo QA Tester - ADES-AI.

El veredicto ya NO depende de que un LLM "opine": se decide ejecutando el código.

  1. Validación anti-alucinación contra el grafo Neo4j (KPI 4): si el código
     referencia módulos/clases/funciones del proyecto que no existen -> FAIL.
  2. Tests de aceptación propios de QA (generados una vez a partir del
     requerimiento, independientes de los tests del Developer).
  3. Ejecución de TODOS los tests en el sandbox Docker (regla 5, --network none).
  4. Si los tests pasan, revisión LLM local del requisito (primera línea estricta
     'VEREDICTO: PASS|FAIL').

Corrige el bug del parser anterior: `"PASS\\nmaneja errores"` se marcaba FAIL
porque buscaba "ERROR" en todo el texto.
"""
import ast
import re

from agents.common import call_agent
from agents.prompts import get_prompt
from core import sandbox

QA_TEST_FILE = "test_qa_acceptance.py"
_VERDICT = re.compile(r"^\W*(?:VEREDICTO|VERDICT)?\s*:?\s*\**\s*(PASS|FAIL)\b", re.I)


def _parse_veredicto(text: str) -> str:
    """Lee el veredicto SOLO de la primera línea no vacía. Ambiguo -> FAIL (conservador)."""
    for line in text.strip().splitlines():
        if line.strip():
            m = _VERDICT.match(line.strip())
            return m.group(1).upper() if m else "FAIL"
    return "FAIL"


def _gen_acceptance_tests(state: dict, files: dict) -> str | None:
    """QA escribe tests de aceptación a partir del requerimiento (una vez por run)."""
    names = ", ".join(sorted(files))
    sigs = []
    for p, c in files.items():
        if p.endswith(".py") and not p.split("/")[-1].startswith("test_"):
            try:
                t = ast.parse(c)
                for n in t.body:
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                        sigs.append(f"{p}: {n.name}")
                    elif isinstance(n, ast.Assign):
                        sigs += [f"{p}: {x.id}" for x in n.targets if isinstance(x, ast.Name)]
            except SyntaxError:
                pass
    system = ("Eres QA. Escribe tests pytest de ACEPTACION, independientes del Developer, que "
              "verifiquen el requerimiento y sus criterios. Solo importa nombres que existan en "
              "la lista de simbolos. Sin red. Para FastAPI usa fastapi.testclient.TestClient. "
              "Prueba COMPORTAMIENTO (codigos de estado, valores devueltos, excepciones), no "
              "textos internos de errores de FastAPI/Pydantic ni archivos como requirements.txt; "
              "no leas archivos fuera del directorio actual. "
              f"Devuelve SOLO un bloque ```python``` con el contenido de {QA_TEST_FILE}.")
    crit = []
    for t in state.get("tickets") or []:
        crit += [c for c in t.get("criterios", []) if isinstance(c, str)]
    user = (f"Requerimiento: {state.get('requerimiento', '')}\n"
            + ("Criterios:\n" + "\n".join(f"- {c}" for c in crit) + "\n" if crit else "")
            + f"Archivos: {names}\nSimbolos disponibles:\n" + "\n".join(sigs[:80]))
    res = call_agent("qa", system, user, state, fallback=("ollama", "gpt-oss:20b"),
                     effort="medium")
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", res.text, re.S)
    code = blocks[0] if blocks else res.text
    code = re.sub(r"^\s*#\s*(FILE:\s*)?test_qa_acceptance\.py\s*\n", "", code)
    try:
        ast.parse(code)
    except SyntaxError:
        return None
    return code if "def test_" in code else None


def _graph_check(state: dict, files: dict) -> list[str]:
    idx = state.get("_graph_index")
    if idx is None:
        return []
    from memory.validator import validate_files
    out = []
    for path, findings in validate_files(files, idx).items():
        out += [f"{path}: {f}" for f in findings]
    return out


def qa_node(state: dict) -> dict:
    files = dict(state.get("files") or {})
    feedback_prev = state.get("qa_feedback", "")
    if not any(p.endswith(".py") for p in files):
        return {"qa_veredicto": "FAIL", "qa_feedback":
                "VEREDICTO: FAIL\nNo se encontraron archivos de codigo. Entrega cada archivo en "
                "un bloque ``` cuya primera linea sea '# FILE: ruta.py'.",
                "sandbox": {}}

    # 1. Anti-alucinación
    halluc = _graph_check(state, files)
    if halluc:
        fb = ("VEREDICTO: FAIL\nEl codigo referencia elementos del proyecto que NO existen "
              "en el grafo de codigo (alucinaciones). Usa solo lo que aparece en el mapa del "
              "repositorio:\n" + "\n".join(f"- {h}" for h in halluc))
        return {"qa_veredicto": "FAIL", "qa_feedback": fb, "alucinaciones": halluc,
                "alucinaciones_detectadas": state.get("alucinaciones_detectadas", 0) + len(halluc),
                "sandbox": {}}

    # 2. Tests de aceptación de QA
    qa_tests = state.get("qa_tests")
    regen = state.get("qa_tests_regen", 0)
    if qa_tests is None and state.get("qa_acceptance", True):
        qa_tests = _gen_acceptance_tests(state, files) or ""
    if qa_tests:
        files[QA_TEST_FILE] = qa_tests

    # 3. Sandbox Docker
    res = sandbox.run_tests(files)
    sb = {"passed": res.passed, "tests_run": res.tests_run, "tests_failed": res.tests_failed,
          "exit_code": res.exit_code}
    out = {"qa_tests": qa_tests, "sandbox": sb, "alucinaciones": []}

    if not res.passed:
        qa_failed = bool(qa_tests) and re.search(
            rf"(FAILED|ERROR) {re.escape(QA_TEST_FILE)}", res.output) is not None
        if qa_failed and regen < 1 and state.get("iteracion", 0) >= 2:
            # Si los tests de QA siguen fallando tras 2 entregas, pueden ser ellos los que
            # están mal (p. ej. leer ../requirements.txt): se regeneran UNA vez.
            out.update(qa_tests=None, qa_tests_regen=regen + 1)
        fb = ("VEREDICTO: FAIL\nLos tests fallan en el sandbox Docker "
              f"({res.tests_failed}/{res.tests_run} fallidos, exit={res.exit_code}).\n"
              f"Salida:\n{res.output[-3500:]}")
        try:
            from memory import vaccine
            v = vaccine.context_for(res.output[-2000:])
            if v:
                fb += "\n\nErrores parecidos ya resueltos antes:\n" + v
        except Exception:
            pass
        out.update(qa_veredicto="FAIL", qa_feedback=fb)
        return out

    # 4. Revisión del requisito (tests ya pasan)
    review = call_agent(
        "qa", get_prompt("qa"),
        f"Requerimiento: {state.get('requerimiento', '')}\n\nResultado del sandbox: "
        f"{res.tests_run} tests, todos pasan.\n\nCodigo:\n{state.get('codigo', '')[:8000]}",
        state, fallback=("ollama", "gpt-oss:20b"), effort="low", use_cache=False)
    veredicto = _parse_veredicto(review.text)
    if veredicto == "PASS" and feedback_prev:
        try:
            from memory import vaccine
            vaccine.learn_from_failure(feedback_prev, state.get("codigo", ""),
                                       project=state.get("project"))
        except Exception:
            pass
    out.update(qa_veredicto=veredicto,
               qa_feedback=review.text if veredicto == "FAIL" else review.text[:1500])
    return out
