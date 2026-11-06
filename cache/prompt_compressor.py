"""Compresión de prompts con LLMLingua-2 - ADES-AI, Fase 7.

Reduce el tamaño de prompts y contextos RAG (hasta ~20x) con pérdida mínima,
usando el modelo LLMLingua-2 (BERT multilingual). El modelo se descarga en la
primera llamada a `compress`.

Uso:
    from cache.prompt_compressor import compress
    out = compress("texto largo a comprimir...", rate=0.5)
"""
from typing import Any

_compressor = None

MODEL = "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"


def _get_compressor() -> Any:
    global _compressor
    if _compressor is None:
        from llmlingua import PromptCompressor
        _compressor = PromptCompressor(model_name=MODEL, device_map="cpu", use_llmlingua2=True)
    return _compressor


def compress(context: str | list[str], instruction: str = "", question: str = "",
             rate: float = 0.5) -> dict:
    """Comprime un contexto/prompt. Devuelve {compressed_prompt, ratio, origen}. """
    c = _get_compressor()
    ctx = [context] if isinstance(context, str) else context
    original = " ".join(ctx)
    result = c.compress_prompt(ctx, instruction=instruction, question=question, rate=rate)
    compressed = result["compressed_prompt"]
    return {
        "compressed_prompt": compressed,
        "original_chars": len(original),
        "compressed_chars": len(compressed),
        "ratio": round(len(compressed) / len(original), 3) if original else 0.0,
    }


if __name__ == "__main__":
    sample = ("FastAPI es un framework web moderno de Python para construir APIs REST. "
              "Ofrece validacion automatica con Pydantic, documentacion interactiva con "
              "OpenAPI y Swagger UI, y un rendimiento muy alto gracias a su base asincrona.")
    r = compress(sample, rate=0.5)
    print("original :", sample)
    print("comprimido:", r["compressed_prompt"])
    print(f"ratio: {r['ratio']} ({r['original_chars']} -> {r['compressed_chars']} chars)")
