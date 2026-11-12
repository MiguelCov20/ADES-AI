"""LLM-as-a-Judge — evalúa las salidas de los agentes (ADES-AI, Fase 8).

Dos modos:
  - Juez único: un modelo (por defecto DeepSeek V4 vía OpenCode Go) puntúa la
    salida contra la pregunta y los criterios.
  - LLM Council (#18): varios modelos evalúan, se revisan anónimamente entre sí
    y un "chairman" agrega (ver `evals.council`). Se activa con `council=True`
    o, por defecto, con la variable de entorno `ADES_JUDGE=council`.

Toda llamada pasa por `core.llm_gateway.chat` (fallback, presupuesto, tracing,
métricas). El juez no usa el caché semántico: cada evaluación es fresca.

Uso:
    from evals.judge import evaluate
    result = evaluate("escribe /ping", "el codigo...", criteria=["usa FastAPI"])
"""
import os
import re

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

JUDGE_SYSTEM = ("Eres un evaluador estricto e imparcial de salidas de agentes de software. "
                "Sigues exactamente el formato de respuesta pedido.")


def build_prompt(question: str, output: str, criteria: list[str] | None = None,
                 expected: str | None = None) -> str:
    criteria_section = ""
    if criteria:
        criteria_section = "Criterios:\n" + "\n".join(f"- {c}" for c in criteria) + "\n"
    expected_section = f"Referencia esperada: {expected}\n" if expected else ""
    return _JUDGE_PROMPT.format(question=question, criteria_section=criteria_section,
                                expected_section=expected_section, output=output)


def _parse(text: str) -> dict:
    text = text or ""
    score = re.search(r"SCORE:\s*\**\s*(\d+)", text, re.IGNORECASE)
    verdict = re.search(r"VERDICT:\s*\**\s*(PASS|FAIL)", text, re.IGNORECASE)
    rationale = re.search(r"RATIONALE:\s*\**\s*(.+)", text, re.IGNORECASE)
    return {
        "score": max(0, min(10, int(score.group(1)))) if score else 0,
        "verdict": (verdict.group(1).upper() if verdict else "FAIL"),
        "rationale": (rationale.group(1).strip() if rationale else ""),
        "parsed": bool(score and verdict),
    }


def council_default() -> bool:
    """True si `ADES_JUDGE=council` (el Council es el juez por defecto)."""
    return os.getenv("ADES_JUDGE", "").strip().lower() == "council"


def evaluate(question: str, output: str, criteria: list[str] | None = None,
             expected: str | None = None, provider: str = "opencode",
             model: str = "deepseek-v4-pro", *, council: bool | None = None,
             members: list[tuple[str, str]] | None = None,
             project: str | None = None) -> dict:
    """Evalúa la salida de un agente. Devuelve {score, verdict, rationale, question}.

    `council=None` usa el valor de `ADES_JUDGE`; con Council el resultado incluye
    además la clave `council` con el detalle por miembro.
    """
    if council is None:
        council = council_default()
    if council:
        from evals.council import council_evaluate
        r = council_evaluate(question, output, criteria=criteria, expected=expected,
                             members=members, project=project)
        return {"score": r["score"], "verdict": r["verdict"], "rationale": r["rationale"],
                "question": question, "judge": "council", "council": r}

    from core.llm_gateway import chat
    res = chat("judge", JUDGE_SYSTEM, build_prompt(question, output, criteria, expected),
               project=project, provider=provider, model=model, use_cache=False,
               temperature=0.0)
    result = _parse(res.text)
    result.pop("parsed", None)
    result["question"] = question
    result["judge"] = f"{res.provider}:{res.model}"
    return result


if __name__ == "__main__":
    r = evaluate(
        "Escribe un endpoint /ping en FastAPI que devuelva 'pong'",
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/ping')\ndef ping():\n    return {'pong': True}",
        criteria=["usa FastAPI", "ruta /ping", "devuelve pong"],
    )
    print(r)
