"""Evaluación de calidad RAG (ADES-AI, Fase 8).

Mide tres métricas estándar de RAG usando el juez LLM de `evals.judge`:
  - faithfulness: ¿la respuesta está respaldada por el contexto recuperado?
  - answer_relevance: ¿la respuesta responde a la pregunta?
  - context_relevance: ¿el contexto recuperado es relevante para la pregunta?

Nota: es una implementación ligera con LLM-as-judge; en producción puede
sustituirse por Ragas o DeepEval (no instalados para evitar conflictos de
dependencias con cognee/fastembed/litellm, ver notas de Fase 7).
"""
from evals.judge import evaluate


def _score(question: str, answer: str, criterion: str) -> int:
    r = evaluate(question, answer, criteria=[criterion])
    return r["score"]


def evaluate_rag(question: str, answer: str, contexts: list[str],
                 provider: str = "opencode", model: str = "deepseek-v4-pro") -> dict:
    """Evalúa una respuesta RAG. Devuelve métricas 1-10 y un promedio."""
    ctx_text = "\n".join(f"- {c}" for c in contexts)

    faithfulness = evaluate(
        f"Responde a: {question}", answer,
        criteria=["La respuesta debe estar respaldada por el contexto dado"],
        expected=f"Contexto:\n{ctx_text}", provider=provider, model=model,
    )["score"]

    answer_relevance = evaluate(
        question, answer,
        criteria=["La respuesta debe responder directamente a la pregunta"],
        provider=provider, model=model,
    )["score"]

    context_relevance = evaluate(
        f"¿Este contexto es relevante para la pregunta '{question}'?", ctx_text,
        criteria=["El contexto debe contener información relevante a la pregunta"],
        provider=provider, model=model,
    )["score"]

    scores = {"faithfulness": faithfulness, "answer_relevance": answer_relevance,
              "context_relevance": context_relevance}
    scores["promedio"] = round(sum(scores.values()) / 3, 1)
    return scores


if __name__ == "__main__":
    r = evaluate_rag(
        "¿Qué framework prefiere el usuario?",
        "El usuario prefiere FastAPI sobre Django.",
        ["El usuario prefiere FastAPI para APIs REST", "El usuario usa PostgreSQL"],
    )
    print(r)
