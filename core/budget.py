"""Token Budget Governor (feature #10).

Tope de gasto por proyecto (USD y tokens de pago). Según el consumo, limita el
nivel de modelo que el router puede usar:

    < 80% del presupuesto  -> "any"   (cualquier modelo)
    80% - 100%             -> "cheap" (solo modelos baratos de nube o locales)
    >= 100%                -> "local" (solo modelos locales, $0)

Presupuestos en `.ades/_global/budgets.json`:
    {"ades-ai": {"usd": 5.0, "paid_tokens": 2000000}}
"""
import json

from core import metrics_store
from core.config import global_state_dir

DEFAULT_BUDGET = {"usd": 5.0, "paid_tokens": 5_000_000}
CHEAP_MODELS = {"gemini-flash-lite-latest", "deepseek-v4.1-flash", "gemini-flash-latest"}


def _path():
    return global_state_dir() / "budgets.json"


def load() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def set_budget(project: str, usd: float | None = None, paid_tokens: int | None = None) -> dict:
    data = load()
    b = data.setdefault(project, dict(DEFAULT_BUDGET))
    if usd is not None:
        b["usd"] = float(usd)
    if paid_tokens is not None:
        b["paid_tokens"] = int(paid_tokens)
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return b


def get_budget(project: str) -> dict:
    return load().get(project, dict(DEFAULT_BUDGET))


def status(project: str) -> dict:
    b = get_budget(project)
    s = metrics_store.spent(project)
    frac = max(s["cost"] / b["usd"] if b["usd"] else 1.0,
               s["paid_tokens"] / b["paid_tokens"] if b["paid_tokens"] else 1.0)
    tier = "any" if frac < 0.8 else ("cheap" if frac < 1.0 else "local")
    return {"budget": b, "spent": s, "used_fraction": round(frac, 4), "tier": tier}


def allowed(provider: str, model: str, tier: str) -> bool:
    """¿Puede usarse este modelo con el nivel de presupuesto actual?"""
    if provider == "ollama" or tier == "any":
        return True
    if tier == "cheap":
        return model in CHEAP_MODELS
    return False  # tier == "local"
