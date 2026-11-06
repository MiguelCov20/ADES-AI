"""LLM-as-a-Judge — evalúa las salidas de los agentes (ADES-AI, Fase 8).

Usa un LLM (por defecto DeepSeek V4 vía OpenCode Go) como juez imparcial que
puntúa la salida de un agente contra la pregunta y los criterios.

Uso:
    from evals.judge import evaluate
    result = evaluate("escribe /ping", "el codigo...", criteria=["usa FastAPI"])
"""
import re

from agents.llm import get_llm

_JUDGE_PROMPT = """Eres un juez imparcial que evalua la salida de un agente de software.

Pregunta: {question}
{criteria_section}{expected_section}
Salida del agente:
---
{output}
---

Puntua la salida de 1 a 10 y da un veredicto.
Responde EXACTAMENTE en este formato (sin nada mas):
SCORE: <numero entero 1-10>
VERDICT: <PASS o FAIL>
RATIONALE: <explicacion breve en una linea>
"""


def _parse(text: str) -> dict:
    score = re.search(r"SCORE:\s*(\d+)", text)
    verdict = re.search(r"VERDICT:\s*(PASS|FAIL)", text, re.IGNORECASE)
    rationale = re.search(r"RATIONALE:\s*(.+)", text, re.IGNORECASE)
    return {
        "score": int(score.group(1)) if score else 0,
        "verdict": (verdict.group(1).upper() if verdict else "FAIL"),
        "rationale": (rationale.group(1).strip() if rationale else ""),
    }


def evaluate(question: str, output: str, criteria: list[str] | None = None,
             expected: str | None = None, provider: str = "opencode",
             model: str = "deepseek-v4-pro") -> dict:
    """Evalúa la salida de un agente. Devuelve {score, verdict, rationale}."""
    criteria_section = ""
    if criteria:
        criteria_section = "Criterios:\n" + "\n".join(f"- {c}" for c in criteria) + "\n"
    expected_section = f"Referencia esperada: {expected}\n" if expected else ""

    prompt = _JUDGE_PROMPT.format(
        question=question, criteria_section=criteria_section,
        expected_section=expected_section, output=output,
    )
    llm = get_llm(provider, model)
    resp = llm.invoke(prompt)
    result = _parse(resp.content if hasattr(resp, "content") else str(resp))
    result["question"] = question
    return result


if __name__ == "__main__":
    r = evaluate(
        "Escribe un endpoint /ping en FastAPI que devuelva 'pong'",
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/ping')\ndef ping():\n    return {'pong': True}",
        criteria=["usa FastAPI", "ruta /ping", "devuelve pong"],
    )
    print(r)
