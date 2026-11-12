"""Tests del marketplace interno con ratings (#13)."""
import json

import pytest

from registry import ratings
from tests.test_registry_helpers import reg_env  # noqa: F401


def test_rate_y_promedio(reg_env):
    ratings.rate("llmfit", 5, "va genial", "ana")
    ratings.rate("llmfit", 3, "regular", "luis")
    assert ratings.average("llmfit") == 4.0
    assert ratings.summary("llmfit")["votos"] == 2
    data = json.loads(reg_env.ratings.read_text(encoding="utf-8"))
    assert data["valoraciones"]["llmfit"][0]["comentario"] == "va genial"


def test_mismo_autor_reemplaza(reg_env):
    ratings.rate("ecc", 1, "", "ana")
    ratings.rate("ecc", 4, "mejor tras probarla", "ana")
    assert ratings.average("ecc") == 4.0
    assert len(ratings.ratings("ecc")) == 1


@pytest.mark.parametrize("score", [0, 6, 2.5, "5", True])
def test_rate_valida_puntuacion(reg_env, score):
    with pytest.raises(ValueError):
        ratings.rate("ecc", score, "", "ana")


def test_rate_herramienta_inexistente(reg_env):
    with pytest.raises(ValueError):
        ratings.rate("no-existe", 5)


def test_sin_votos(reg_env):
    assert ratings.average("web-llm") is None
    assert ratings.top(5) == []


def test_top_ordena_por_media_y_votos(reg_env):
    ratings.rate("ecc", 5, autor="a")
    ratings.rate("llmfit", 5, autor="a")
    ratings.rate("llmfit", 5, autor="b")
    ratings.rate("web-llm", 2, autor="a")
    top = ratings.top(2)
    assert [t["id"] for t in top] == ["llmfit", "ecc"]  # empate a 5.0 -> más votos primero
    assert [t["id"] for t in ratings.top(10)] == ["llmfit", "ecc", "web-llm"]
    assert [t["id"] for t in ratings.top(10, tipo="sdk")] == ["web-llm"]


def test_tags(reg_env):
    assert ratings.tag("llmfit", "GPU", "hardware", "gpu") == ["gpu", "hardware"]
    assert ratings.untag("llmfit", "hardware") == ["gpu"]
    with pytest.raises(ValueError):
        ratings.tag("nope", "x")


def test_search_ordena_por_rating_y_busca_tags(reg_env):
    ratings.rate("web-llm", 2, autor="a")
    ratings.rate("llmfit", 5, autor="a")
    # 'model' aparece en llmfit ('modelos') y en web-llm? -> buscar por tag común
    ratings.tag("web-llm", "inferencia")
    ratings.tag("llmfit", "inferencia")
    res = ratings.search("inferencia")
    ids = [t["id"] for t in res]
    assert ids.index("llmfit") < ids.index("web-llm")
    assert res[0]["promedio"] == 5.0 and "inferencia" in res[0]["tags"]
    # las que no tienen votos van al final
    ratings.tag("ecc", "inferencia")
    assert [t["id"] for t in ratings.search("inferencia")][-1] == "ecc"
