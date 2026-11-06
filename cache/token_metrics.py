"""Métricas de tokens y costo - ADES-AI, Fase 7.

Registra llamadas, hits del caché semántico, tokens y costo estimado por
tarea/proyecto, para medir el ahorro del routing y del caché (hit-rate).

Los costos por modelo son APROXIMADOS y configurables; los modelos locales
cuestan $0. Ajusta `COST_PER_1M` con los precios reales de tu proveedor.
"""

# Costo USD por 1M de tokens (input, output). Valores aproximados/configurables.
COST_PER_1M = {
    "gemini-flash-latest": {"input": 0.10, "output": 0.40},
    "gemini-flash-lite-latest": {"input": 0.075, "output": 0.30},
    "gemini-4-argon": {"input": 1.25, "output": 5.00},
    "deepseek-v4-pro": {"input": 0.50, "output": 2.00},
    "deepseek-v4.1-flash": {"input": 0.10, "output": 0.40},
    "gpt-oss:20b": {"input": 0.0, "output": 0.0},
    "qwen3.8:27b-iq3": {"input": 0.0, "output": 0.0},
    "llama3.2:3b": {"input": 0.0, "output": 0.0},
}


class TokenMetrics:
    """Acumulador de métricas de tokens/costo por tarea."""

    def __init__(self):
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_cost = 0.0
        self.by_task: dict[str, dict] = {}

    def _cost(self, model: str, in_tok: int, out_tok: int) -> float:
        c = COST_PER_1M.get(model, COST_PER_1M["gpt-oss:20b"])
        return (in_tok * c["input"] + out_tok * c["output"]) / 1_000_000

    def record(self, task: str, model: str, input_tokens: int, output_tokens: int,
               cache_hit: bool = False) -> None:
        cost = self._cost(model, input_tokens, output_tokens)
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost += cost
        if cache_hit:
            self.cache_hits += 1
        t = self.by_task.setdefault(task, {"calls": 0, "hits": 0, "tokens": 0, "cost": 0.0})
        t["calls"] += 1
        t["tokens"] += input_tokens + output_tokens
        t["cost"] += cost
        if cache_hit:
            t["hits"] += 1

    def hit_rate(self) -> float:
        return round(self.cache_hits / self.calls, 3) if self.calls else 0.0

    def report(self) -> dict:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "hit_rate": self.hit_rate(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost": round(self.total_cost, 6),
            "by_task": self.by_task,
        }
