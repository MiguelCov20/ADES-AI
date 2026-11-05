"""Cargador del roster de agentes (ADES-AI, Fase 3).

El roster.json es el registro de agentes (modelo, skills, herramientas y
permisos). Este módulo lo lee/escribe de forma idempotente.
"""
import json
from pathlib import Path

ROSTER_PATH = Path(__file__).resolve().parent / "roster.json"


def load_roster() -> dict:
    with open(ROSTER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_roster(roster: dict) -> None:
    with open(ROSTER_PATH, "w", encoding="utf-8") as f:
        json.dump(roster, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_agents() -> list[dict]:
    return load_roster().get("agents", [])


def get_agent(agent_id: str) -> dict | None:
    for a in get_agents():
        if a["id"] == agent_id:
            return a
    return None
