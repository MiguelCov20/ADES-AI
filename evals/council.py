"""LLM Council como juez (feature #18), inspirado en karpathy/llm-council.

Tres etapas:
  1. Evaluación independiente: cada miembro puntúa la salida (SCORE/VERDICT/RATIONALE).
  2. Revisión cruzada anónima: cada miembro ve las evaluaciones de los DEMÁS
     anonimizadas ("Evaluador A", "Evaluador B"...) y emite una puntuación final.
  3. Chairman: agrega de forma determinista (mediana de scores + veredicto por
     mayoría + rationale del miembro más cercano a la mediana). Opcionalmente un
     modelo `chairman=(provider, model)` redacta la síntesis.

Tolerante a fallos: si un miembro falla (error, respuesta sin formato, o el
fallback del gateway lo hizo caer en un modelo que ya es otro miembro —
perdería la independencia del voto), se descarta y el Council sigue mientras
haya quórum (≥2 por defecto). Sin quórum lanza `CouncilQuorumError`.

Todas las llamadas pasan por `core.llm_gateway.chat` sin caché semántico.
"""
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor

from core.llm_gateway import chat
from evals.judge import JUDGE_SYSTEM, _parse, build_prompt

DEFAULT_MEMBERS: list[tuple[str, str]] = [
    ("ollama", "gpt-oss:20b"),
    ("opencode", "deepseek-v4.1-flash"),
    ("gemini", "gemini-flash-lite-latest"),
]

_REVIEW_PROMPT = """{base}

Otros evaluadores independientes (anonimos) ya evaluaron esta misma salida:
{peers}

Tu evaluacion inicial fue: SCORE {score}, VERDICT {verdict}.
Revisa criticamente las otras evaluaciones: si detectan problemas reales que pasaste
por alto, ajusta tu puntuacion; si estan equivocadas, mantenla. No sigas a la mayoria
sin motivo.
Responde EXACTAMENTE en este formato (sin nada mas):
SCORE: <numero entero 1-10>
VERDICT: <PASS o FAIL>
RATIONALE: <explicacion breve en una linea>
"""

_CHAIR_PROMPT = """Eres el presidente de un consejo de jueces. Pregunta evaluada: {question}
Evaluaciones finales (anonimas):
{peers}
Resultado agregado: SCORE mediano {score}, veredicto por mayoria {verdict}.
Escribe en UNA linea, en espanol, la justificacion consolidada del consejo."""


class CouncilQuorumError(RuntimeError):
    """No hay suficientes miembros válidos para emitir un veredicto."""


def _label(i: int) -> str:
    return f"Evaluador {chr(ord('A') + i)}"


def _ask(member: tuple[str, str], prompt: str, project, run_id) -> dict:
    provider, model = member
    res = chat("judge", JUDGE_SYSTEM, prompt, project=project, run_id=run_id,
               provider=provider, model=model, use_cache=False, temperature=0.0)
    parsed = _parse(res.text)
    if not parsed["parsed"]:
        raise ValueError(f"respuesta sin formato SCORE/VERDICT: {res.text[:120]!r}")
    parsed.pop("parsed")
    parsed.update(member=f"{provider}:{model}", used=f"{res.provider}:{res.model}",
                  cost=res.cost, tokens=res.tokens_in + res.tokens_out, latency=res.latency)
    return parsed


def _run_parallel(jobs: dict, fn) -> tuple[dict, dict]:
    """Ejecuta fn(key, arg) en paralelo. Devuelve ({key: resultado}, {key: error})."""
    ok, failed = {}, {}
    if not jobs:
        return ok, failed
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(fn, k, a) for k, a in jobs.items()}
        for k, f in futs.items():
            try:
                ok[k] = f.result()
            except Exception as e:  # noqa: BLE001
                failed[k] = f"{type(e).__name__}: {str(e)[:200]}"
    return ok, failed


def aggregate(evals: list[dict]) -> dict:
    """Chairman determinista: mediana de scores + mayoría de veredictos.

    Empate de veredictos -> PASS solo si la mediana es >= 6.
    """
    if not evals:
        raise CouncilQuorumError("sin evaluaciones que agregar")
    scores = [e["score"] for e in evals]
    med = statistics.median(scores)
    passes = sum(1 for e in evals if e["verdict"] == "PASS")
    fails = len(evals) - passes
    if passes != fails:
        verdict = "PASS" if passes > fails else "FAIL"
    else:
        verdict = "PASS" if med >= 6 else "FAIL"
    closest = min(evals, key=lambda e: (abs(e["score"] - med), e["verdict"] != verdict))
    return {"score": med, "verdict": verdict, "rationale": closest.get("rationale", ""),
            "votes": {"PASS": passes, "FAIL": fails},
            "spread": max(scores) - min(scores)}


def council_evaluate(question: str, output: str, criteria: list[str] | None = None,
                     expected: str | None = None, *,
                     members: list[tuple[str, str]] | None = None, quorum: int = 2,
                     review: bool = True, chairman: tuple[str, str] | None = None,
                     project: str | None = None) -> dict:
    """Evalúa con el Council. Devuelve {score, verdict, rationale, members, ...}."""
    members = [tuple(m) for m in (members or DEFAULT_MEMBERS)]
    run_id = f"council-{uuid.uuid4().hex[:10]}"
    base = build_prompt(question, output, criteria, expected)

    # Etapa 1: evaluaciones independientes
    first, failed = _run_parallel({m: base for m in members},
                                  lambda m, p: _ask(m, p, project, run_id))
    # Independencia: si el fallback hizo caer a un miembro en el modelo de otro, se descarta.
    seen = {}
    for m in members:
        if m not in first:
            continue
        used = first[m]["used"]
        if used in seen:
            failed[m] = f"fallback a {used}, ya representado por {seen[used]}"
            del first[m]
        else:
            seen[used] = f"{m[0]}:{m[1]}"
    if len(first) < quorum:
        raise CouncilQuorumError(f"quórum insuficiente ({len(first)}/{quorum}): {failed}")

    # Etapa 2: revisión cruzada anónima
    final = dict(first)
    reviews = {}
    if review and len(first) >= 2:
        order = [m for m in members if m in first]

        def review_prompt(m):
            peers = [first[o] for o in order if o != m]
            peer_txt = "\n".join(f"- {_label(i)}: SCORE {p['score']}, VERDICT {p['verdict']}. "
                                 f"{p['rationale']}" for i, p in enumerate(peers))
            return _REVIEW_PROMPT.format(base=base, peers=peer_txt, score=first[m]["score"],
                                         verdict=first[m]["verdict"])

        reviews, rev_failed = _run_parallel({m: review_prompt(m) for m in order},
                                            lambda m, p: _ask(m, p, project, run_id))
        for m, r in reviews.items():
            final[m] = {**r, "initial_score": first[m]["score"],
                        "initial_verdict": first[m]["verdict"]}
        for m, err in rev_failed.items():  # sin revisión: se mantiene la evaluación inicial
            final[m] = {**first[m], "review_error": err}

    evals = [final[m] for m in members if m in final]
    agg = aggregate(evals)

    # Etapa 3 (opcional): síntesis redactada por un modelo chairman
    if chairman:
        peers = "\n".join(f"- {_label(i)}: SCORE {e['score']}, VERDICT {e['verdict']}. "
                          f"{e['rationale']}" for i, e in enumerate(evals))
        try:
            res = chat("judge", JUDGE_SYSTEM, _CHAIR_PROMPT.format(
                question=question, peers=peers, score=agg["score"], verdict=agg["verdict"]),
                project=project, run_id=run_id, provider=chairman[0], model=chairman[1],
                use_cache=False, temperature=0.0)
            if res.text.strip():
                agg["rationale"] = res.text.strip().splitlines()[0][:500]
        except Exception as e:  # noqa: BLE001
            agg["chairman_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    calls = [*first.values(), *reviews.values()]
    return {
        **agg,
        "members": {f"{m[0]}:{m[1]}": final[m] for m in members if m in final},
        "failed": {f"{m[0]}:{m[1]}": err for m, err in failed.items()},
        "quorum": quorum, "n_valid": len(evals), "reviewed": bool(reviews),
        "cost": round(sum(c.get("cost", 0.0) for c in calls), 6),
        "run_id": run_id,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: `ades council "pregunta" <archivo_con_la_salida> [--criterio C ...]`."""
    import argparse
    import json
    import pathlib

    ap = argparse.ArgumentParser(description="LLM Council como juez")
    ap.add_argument("pregunta")
    ap.add_argument("salida", help="archivo con la salida a evaluar")
    ap.add_argument("--criterio", action="append", default=[])
    a = ap.parse_args(argv)
    out = pathlib.Path(a.salida).read_text(encoding="utf-8", errors="replace")
    r = council_evaluate(a.pregunta, out, criteria=a.criterio or None)
    print(json.dumps({k: r.get(k) for k in ("score", "verdict", "rationale", "votes", "failed")},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if r.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
