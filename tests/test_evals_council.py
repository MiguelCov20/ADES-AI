"""Tests del juez (evals.judge) y del LLM Council (#18)."""
import pytest

from evals import council, judge

GOOD = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/ping')\ndef ping():\n    return 'pong'"
Q = "Escribe un endpoint /ping en FastAPI que devuelva 'pong'"


def _user(messages) -> str:
    return messages[-1].content


def _scripted(first: dict, review: dict | None = None, fail: set = frozenset()):
    """Mock: puntuación por modelo en etapa 1 y en revisión cruzada."""
    log = []

    def fn(provider, model, messages):
        u = _user(messages)
        stage = "review" if "Otros evaluadores" in u else "first"
        log.append((stage, model, u))
        if model in fail:
            raise RuntimeError("503 UNAVAILABLE")
        s = (review or first).get(model, first.get(model)) if stage == "review" else first[model]
        v = "PASS" if s >= 6 else "FAIL"
        return f"SCORE: {s}\nVERDICT: {v}\nRATIONALE: opinión de {model}", 100, 20

    fn.log = log
    return fn


def test_juez_unico_usa_gateway(mock_llm):
    seen = []

    def fn(provider, model, messages):
        seen.append((provider, model))
        return "SCORE: 8\nVERDICT: PASS\nRATIONALE: correcto", 50, 10

    mock_llm(fn)
    r = judge.evaluate(Q, GOOD, criteria=["usa FastAPI"], council=False)
    assert seen == [("opencode", "deepseek-v4-pro")]
    assert r["score"] == 8 and r["verdict"] == "PASS" and r["question"] == Q
    assert r["judge"] == "opencode:deepseek-v4-pro"


def test_parse_tolera_markdown_y_formato_roto():
    assert judge._parse("**SCORE:** 7\n**VERDICT:** pass\nRATIONALE: ok")["score"] == 7
    bad = judge._parse("no sé")
    assert bad["score"] == 0 and bad["verdict"] == "FAIL" and not bad["parsed"]


def test_council_tres_etapas_y_mediana(mock_llm):
    fn = mock_llm(_scripted({"gpt-oss:20b": 9, "deepseek-v4.1-flash": 7,
                             "gemini-flash-lite-latest": 3},
                            review={"gemini-flash-lite-latest": 5}))
    r = council.council_evaluate(Q, GOOD, criteria=["usa FastAPI"])
    assert r["n_valid"] == 3 and r["reviewed"] and not r["failed"]
    assert r["score"] == 7 and r["verdict"] == "PASS"
    assert r["votes"] == {"PASS": 2, "FAIL": 1}
    assert r["members"]["gemini:gemini-flash-lite-latest"]["initial_score"] == 3
    assert r["members"]["gemini:gemini-flash-lite-latest"]["score"] == 5
    assert r["rationale"] == "opinión de deepseek-v4.1-flash"  # el más cercano a la mediana
    reviews = [u for stage, _, u in fn.log if stage == "review"]
    assert len(reviews) == 3
    # anonimato: la revisión muestra "Evaluador A/B", nunca el nombre de los otros modelos
    for u in reviews:
        assert "Evaluador A" in u and "Evaluador B" in u and "Evaluador C" not in u


def test_council_tolera_un_miembro_caido(mock_llm):
    # gemini falla; el gateway hace fallback -> gemini-flash-lite (falla) -> deepseek-v4.1-flash,
    # que ya es miembro: el Council lo descarta para no duplicar votos.
    mock_llm(_scripted({"gpt-oss:20b": 8, "deepseek-v4.1-flash": 6,
                        "gemini-flash-lite-latest": 1}, fail={"gemini-flash-lite-latest"}))
    r = council.council_evaluate(Q, GOOD)
    assert r["n_valid"] == 2
    assert "gemini:gemini-flash-lite-latest" in r["failed"]
    assert r["score"] == 7 and r["verdict"] == "PASS"


def test_council_sin_quorum(mock_llm):
    mock_llm(_scripted({"gpt-oss:20b": 8, "deepseek-v4.1-flash": 6,
                        "gemini-flash-lite-latest": 1},
                       fail={"gemini-flash-lite-latest", "deepseek-v4.1-flash", "llama3.2:3b"}))
    with pytest.raises(council.CouncilQuorumError):
        council.council_evaluate(Q, GOOD)


def test_council_respuesta_sin_formato_cuenta_como_fallo(mock_llm):
    def fn(provider, model, messages):
        if model == "gpt-oss:20b":
            return "Me parece bien.", 10, 5
        return "SCORE: 4\nVERDICT: FAIL\nRATIONALE: incompleto", 10, 5

    mock_llm(fn)
    r = council.council_evaluate(Q, "pass", members=[("ollama", "gpt-oss:20b"),
                                                     ("opencode", "deepseek-v4.1-flash"),
                                                     ("gemini", "gemini-flash-lite-latest")])
    assert "ollama:gpt-oss:20b" in r["failed"] and r["n_valid"] == 2
    assert r["verdict"] == "FAIL"


def test_aggregate_empate_de_votos():
    e = [{"score": 7, "verdict": "PASS", "rationale": "a"},
         {"score": 5, "verdict": "FAIL", "rationale": "b"}]
    assert council.aggregate(e)["verdict"] == "PASS"  # mediana 6 -> PASS
    e[0]["score"] = 6
    assert council.aggregate(e)["verdict"] == "FAIL"  # mediana 5.5


def test_ades_judge_council_es_el_default(monkeypatch, mock_llm):
    mock_llm(_scripted({"gpt-oss:20b": 8, "deepseek-v4.1-flash": 8,
                        "gemini-flash-lite-latest": 9}))
    monkeypatch.setenv("ADES_JUDGE", "council")
    r = judge.evaluate(Q, GOOD)
    assert r["judge"] == "council" and r["council"]["n_valid"] == 3 and r["score"] == 8
    monkeypatch.delenv("ADES_JUDGE")
    assert judge.council_default() is False


def test_chairman_redacta_rationale(mock_llm):
    base = _scripted({"gpt-oss:20b": 8, "deepseek-v4.1-flash": 7,
                      "gemini-flash-lite-latest": 9})

    def fn(provider, model, messages):
        if "presidente" in _user(messages):
            return "El consejo considera la solución correcta.", 50, 10
        return base(provider, model, messages)

    mock_llm(fn)
    r = council.council_evaluate(Q, GOOD, chairman=("ollama", "gpt-oss:20b"))
    assert r["rationale"] == "El consejo considera la solución correcta."


# ----------------------------------------------------------------------------- live
@pytest.mark.live
def test_live_council_modelos_reales():
    """Council real: gpt-oss:20b local + deepseek-v4.1-flash + gemini-flash-lite (centavos)."""
    r = council.council_evaluate(Q, GOOD, criteria=["usa FastAPI", "ruta /ping",
                                                    "devuelve pong"])
    print("\nCouncil:", {k: (v["score"], v["verdict"], v["used"]) for k, v in r["members"].items()},
          "failed:", r["failed"], "->", r["score"], r["verdict"], f"${r['cost']}")
    assert r["n_valid"] >= 2 and 1 <= r["score"] <= 10
    assert r["verdict"] == "PASS"
