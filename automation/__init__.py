"""Automatización avanzada de ADES-AI (features de la sección 6 del plan).

Módulos:
  - `watchdog`        (#3)  vigilancia 24/7 del repo: compila, ejecuta tests en Docker y alerta.
  - `prefetch`        (#12) prefetch contextual predictivo (RepoMap parcial + embeddings con TTL).
  - `voice`           (#28) control por voz/texto en español -> invocación del CLI `ades`.
  - `model_serving`   (#30) ModelPool OpenAI-compatible (vLLM u Ollama) + generador de compose vLLM.
  - `skill_generator` (#31) genera SKILL.md a partir de tareas repetidas del historial.
  - `self_improve`    (#32) propone mejoras de prompts y solo las aplica si no hay regresión.
"""
