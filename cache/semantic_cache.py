"""Caché semántico (Redis + embeddings) - ADES-AI, Fase 7.

Devuelve respuestas ya calculadas cuando una consulta es semánticamente
parecida a una previa (similitud coseno sobre embeddings de nomic-embed-text),
evitando volver a pagar al modelo. Almacena en Redis (ya en docker-compose).

Nota: es una implementación ligera; en producción puede sustituirse por
GPTCache (instalado) para caché distribuido y más backends.
"""
import hashlib
import json
import os
import urllib.request

import redis

OLLAMA_EMBED = "http://localhost:11434/api/embed"
PREFIX = "ades:semcache:"


def _embed(text: str) -> list[float]:
    payload = json.dumps({"model": "nomic-embed-text", "input": text}).encode("utf-8")
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
    """Caché semántico sobre Redis (clave = hash, valor = embedding + respuesta)."""

    def __init__(self, host: str = "localhost", port: int = 6379, threshold: float = 0.60):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        self.threshold = threshold

    def _key(self, prompt: str) -> str:
        return PREFIX + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    def add(self, prompt: str, response: str) -> str:
        key = self._key(prompt)
        self.r.set(key, json.dumps({"embedding": _embed(prompt), "response": response}))
        return key

    def lookup(self, prompt: str, threshold: float | None = None) -> str | None:
        """Devuelve la respuesta cacheada si hay una consulta similar; si no, None."""
        th = threshold if threshold is not None else self.threshold
        emb = _embed(prompt)
        best_key, best_score = None, 0.0
        for key in self.r.scan_iter(match=PREFIX + "*"):
            data = json.loads(self.r.get(key))
            score = _cosine(emb, data["embedding"])
            if score > best_score:
                best_key, best_score = key, score
        if best_score >= th:
            return json.loads(self.r.get(best_key))["response"]
        return None

    def size(self) -> int:
        return sum(1 for _ in self.r.scan_iter(match=PREFIX + "*"))

    def clear(self) -> None:
        for key in self.r.scan_iter(match=PREFIX + "*"):
            self.r.delete(key)


def main() -> int:
    c = SemanticCache()
    print(f"Caché semántico: {c.size()} entradas en Redis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
