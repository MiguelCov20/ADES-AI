"""Agente Reclutador (meta-agente) - ADES-AI, Fase 3.

Crea, modifica y elimina a los demás agentes del roster. Para cada agente
elige el LLM óptimo (nube OpenCode Go vs local Ollama) según su rol, y le
asigna skills, herramientas y permisos. Registra todo en `roster.json`.

Uso:
    python -m agents.reclutador list
    python -m agents.reclutador create "Agente UX" "disenar interfaces y experiencia de usuario"
    python -m agents.reclutador delete agente_ux
"""
import argparse
import re
import sys

from agents import roster

# Heurística de asignación de LLM óptimo (nube vs local) según el rol.
ROLE_LLM_MAP = [
    (("frontend", "react", "next", "interfaces", "experiencia", "visual", "disen", "web"),
     "ollama", "qwen3.8:27b-iq3"),
    (("arquitect", "pm", "manager", "revisor", "review", "seguridad", "research", "analista"),
     "opencode", "deepseek-v4-pro"),
    (("explor", "clasif", "router", "resumen", "doc", "busqueda"), "ollama", "llama3.2:3b"),
]


def _slug(nombre: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")


def suggest_llm(rol: str) -> dict:
    """Elige el LLM óptimo (nube vs local) para un rol dado."""
    r = rol.lower()
    for keywords, provider, model in ROLE_LLM_MAP:
        if any(k in r for k in keywords):
            return {"provider": provider, "model": model}
    # Por defecto: backend / tareas de codificación -> gpt-oss:20b local ($0)
    return {"provider": "ollama", "model": "gpt-oss:20b"}


def create_agent(nombre: str, rol: str, provider: str | None = None,
                 model: str | None = None, skills=None, herramientas=None,
                 permisos=None) -> dict:
    """Crea un agente y lo registra en roster.json."""
    data = roster.load_roster()
    agent_id = _slug(nombre)
    if not agent_id:
        raise ValueError("El nombre no genera un id valido.")
    if any(a["id"] == agent_id for a in data["agents"]):
        raise ValueError(f"Ya existe un agente con id '{agent_id}'.")

    llm = {"provider": provider, "model": model} if provider else suggest_llm(rol)
    agente = {
        "id": agent_id,
        "nombre": nombre,
        "rol": rol,
        "llm": llm,
        "skills": skills or [],
        "herramientas": herramientas or [],
        "permisos": permisos or [],
    }
    data["agents"].append(agente)
    roster.save_roster(data)
    return agente


def delete_agent(agent_id: str) -> bool:
    """Elimina un agente del roster. Devuelve True si existía."""
    data = roster.load_roster()
    antes = len(data["agents"])
    data["agents"] = [a for a in data["agents"] if a["id"] != agent_id]
    roster.save_roster(data)
    return len(data["agents"]) < antes


def list_agents() -> list[dict]:
    return roster.get_agents()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Reclutador (meta-agente) - Fase 3")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="lista los agentes del roster")

    p_create = sub.add_parser("create", help="crea un agente")
    p_create.add_argument("nombre")
    p_create.add_argument("rol")
    p_create.add_argument("--provider", default=None)
    p_create.add_argument("--model", default=None)

    p_del = sub.add_parser("delete", help="elimina un agente")
    p_del.add_argument("id")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        for a in list_agents():
            llm = a["llm"]
            print(f"  {a['id']:14s} {a['nombre']:20s} -> {llm['provider']}/{llm['model']}")
    elif args.cmd == "create":
        ag = create_agent(args.nombre, args.rol, args.provider, args.model)
        print(f"[OK] agente creado: {ag['id']} -> {ag['llm']['provider']}/{ag['llm']['model']}")
    elif args.cmd == "delete":
        ok = delete_agent(args.id)
        print(f"[OK] agente '{args.id}' eliminado" if ok else f"[!] no existe '{args.id}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
