"""Caché semántico (Redis + embeddings) - ADES-AI, Fase 7.

Devuelve respuestas ya calculadas cuando una consulta es semánticamente casi
idéntica a una previa (coseno sobre embeddings de nomic-embed-text), evitando
volver a pagar al modelo.

Correcciones (v1.1):
  - Umbral por defecto 0.60 -> 0.95 (configurable con ADES_SEMCACHE_THRESHOLD).
    Con 0.60, "endpoint de login en Django" devolvía la respuesta de "/ping en
    FastAPI" (falso positivo). Ver tests/test_semantic_cache.py.
  - Espacios de nombres (`namespace`): la caché se separa por agente/modelo/
    sistema, para que dos agentes distintos no compartan respuestas.
  - Prefijo de tarea de nomic (`search_query:`) para embeddings más precisos.
"""
import hashlib
import json
import os
import urllib.request

import redis

from core.config import OLLAMA_URL, REDIS_HOST, REDIS_PORT

OLLAMA_EMBED = OLLAMA_URL + "/api/embed"
PREFIX = "ades:semcache:"
DEFAULT_THRESHOLD = float(os.getenv("ADES_SEMCACHE_THRESHOLD", "0.95"))


def _embed(text: str) -> list[float]:
    payload = json.dumps({"model": "nomic-embed-text",
                          "input": "search_query: " + text[:8000]}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_EMBED, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"][0]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    """Caché semántico sobre Redis. Un hash por namespace: campo = sha(prompt)."""

    def __init__(self, host: str = REDIS_HOST, port: int = REDIS_PORT,
                 threshold: float = DEFAULT_THRESHOLD, namespace: str = "default"):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        self.threshold = threshold
        self.namespace = namespace

    @property
    def _hkey(self) -> str:
        return PREFIX + self.namespace

    @staticmethod
    def _field(prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]

    def _key(self, prompt: str) -> str:  # compat
        return f"{self._hkey}:{self._field(prompt)}"

    def add(self, prompt: str, response: str, embedding: list[float] | None = None) -> str:
        field = self._field(prompt)
        self.r.hset(self._hkey, field, json.dumps(
            {"embedding": embedding or _embed(prompt), "response": response}))
        return field

    def lookup_scored(self, prompt: str, threshold: float | None = None):
        """Devuelve (respuesta|None, mejor_score, embedding_de_la_consulta)."""
        th = threshold if threshold is not None else self.threshold
        field = self._field(prompt)
        exact = self.r.hget(self._hkey, field)
        if exact:  # coincidencia exacta: sin embedding
            return json.loads(exact)["response"], 1.0, None
        emb = _embed(prompt)
        best_resp, best_score = None, 0.0
        for _, raw in self.r.hscan_iter(self._hkey):
            data = json.loads(raw)
            score = _cosine(emb, data["embedding"])
            if score > best_score:
                best_resp, best_score = data["response"], score
        return (best_resp if best_score >= th else None), best_score, emb

    def lookup(self, prompt: str, threshold: float | None = None) -> str | None:
        return self.lookup_scored(prompt, threshold)[0]

    def size(self) -> int:
        return self.r.hlen(self._hkey)

    def clear(self) -> None:
        self.r.delete(self._hkey)


def main() -> int:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    for k in r.scan_iter(match=PREFIX + "*"):
        print(f"  {k}: {r.hlen(k) if r.type(k) == 'hash' else 1} entradas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
