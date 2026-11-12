"""Configuración central y rutas de estado de ADES-AI.

Todo el estado de runtime (métricas, backlog, presupuestos, cuarentena, etc.)
vive en `.ades/` (gitignored), separado por proyecto para soportar el modo
multi-proyecto (feature #5).
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

STATE_DIR = Path(os.getenv("ADES_STATE_DIR", ROOT / ".ades"))
WORKSPACE_DIR = Path(os.getenv("ADES_WORKSPACE", ROOT / "workspace"))
DEFAULT_PROJECT = os.getenv("ADES_PROJECT", "ades-ai")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# Timeout por llamada LLM en nube (s). Evita que un 503 de Gemini cuelgue la fábrica.
LLM_TIMEOUT = float(os.getenv("ADES_LLM_TIMEOUT", "120"))


def state_dir(project: str | None = None) -> Path:
    """Directorio de estado de un proyecto (se crea si no existe)."""
    p = STATE_DIR / (project or DEFAULT_PROJECT)
    p.mkdir(parents=True, exist_ok=True)
    return p


def global_state_dir() -> Path:
    p = STATE_DIR / "_global"
    p.mkdir(parents=True, exist_ok=True)
    return p
