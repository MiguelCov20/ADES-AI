"""Configuración de pytest para ADES-AI.

- Los tests unitarios usan un directorio de estado temporal (ADES_STATE_DIR) para
  no tocar `.ades/` real, y `core.llm_gateway.set_mock` para no llamar a modelos.
- Los tests marcados `@pytest.mark.live` usan servicios reales (Ollama, Docker,
  Neo4j, Redis, Langfuse, nube). Se ejecutan con:  pytest -m live
  Por defecto (pytest) se ejecutan todos; `pytest -m "not live"` solo unitarios.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="ades-test-")
os.environ.setdefault("ADES_STATE_DIR", _TMP)
os.environ.setdefault("ADES_WORKSPACE", str(Path(_TMP) / "workspace"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "live: usa servicios reales (Ollama/Docker/Neo4j/nube)")


@pytest.fixture
def mock_llm():
    """Instala un mock de LLM. Uso: mock_llm(lambda provider, model, messages: (texto, tin, tout))."""
    from core import llm_gateway

    def _install(fn):
        llm_gateway.set_mock(fn)
        return fn

    yield _install
    llm_gateway.set_mock(None)
