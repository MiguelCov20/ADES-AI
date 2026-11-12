"""Detector de conflictos entre herramientas (feature #14) - ADES-AI, Fase 5.

Avisa cuando dos herramientas compiten entre sí antes de activarlas o
integrarlas. Tipos de conflicto:

| tipo        | cuándo                                                              |
|-------------|---------------------------------------------------------------------|
| `capacidad` | otra herramienta del catálogo declara la misma capacidad (`provee`) |
| `mcp`       | un servidor de `mcp_config.json` ya cubre esa capacidad (su nombre   |
|             | o su campo `provee`), p.ej. dos MCP de `filesystem`                 |
| `puerto`    | mismo puerto de host (`puertos` del catálogo o `docker-compose.yml`)|
| `skill`     | ya hay una skill con el mismo nombre (catálogo o `.opencode/skills`)|

Cada conflicto lleva `activa=True` si la herramienta rival está activa (o es un
servicio/servidor que arranca por defecto). `integrator.activate()` e
`integrator.integrate()` se niegan si hay conflictos activos, salvo `force=True`.
"""
import json

import yaml

from registry import registry


def _norm(values) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def _ports(values) -> set[str]:
    """Normaliza puertos a su número de host como texto ('8080:80' -> '8080')."""
    out = set()
    for v in values or []:
        if isinstance(v, dict):  # sintaxis larga de compose: {target, published}
            v = v.get("published", "")
        s = str(v).strip().strip('"').split("/")[0]
        parts = s.split(":")
        # formatos compose: "8080", "8080:80", "127.0.0.1:8080:80"
        host = parts[-2] if len(parts) >= 2 else parts[0]
        if host:
            out.add(host)
    return out


def _compose_services() -> dict:
    from registry import integrator
    if not integrator.COMPOSE_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(integrator.COMPOSE_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data.get("services") or {}


def _mcp_servers() -> dict:
    from registry import integrator
    if not integrator.MCP_CONFIG.exists():
        return {}
    try:
        cfg = json.loads(integrator.MCP_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cfg.get("mcpServers") or {}


def check_conflicts(tool_id: str) -> list[dict]:
    """Lista los conflictos de `tool_id` con el resto del ecosistema.

    Devuelve una lista de {tipo, con, detalle, activa}. Lista vacía = sin conflictos.
    """
    from registry import integrator

    tool = registry.get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Herramienta '{tool_id}' no esta en el catalogo.")
    state = registry.load_state().get("herramientas", {})
    provee = _norm(tool.get("provee"))
    puertos = _ports(tool.get("puertos"))
    out: list[dict] = []

    # 1) capacidades y puertos frente al resto del catálogo
    for other in registry.get_tools():
        oid = other["id"]
        if oid == tool_id:
            continue
        activa = bool(state.get(oid, {}).get("activa"))
        comunes = provee & _norm(other.get("provee"))
        if comunes:
            out.append({"tipo": "capacidad", "con": oid, "activa": activa,
                        "detalle": f"ambas proveen: {', '.join(sorted(comunes))}"})
        p = puertos & _ports(other.get("puertos"))
        if p:
            out.append({"tipo": "puerto", "con": oid, "activa": activa,
                        "detalle": f"mismo puerto de host: {', '.join(sorted(p))}"})
        if (tool.get("tipo") == "skill" and other.get("tipo") == "skill"
                and tool.get("nombre", "").strip().lower() == other.get("nombre", "").strip().lower()):
            out.append({"tipo": "skill", "con": oid, "activa": activa,
                        "detalle": f"mismo nombre de skill: {tool.get('nombre')}"})

    # 2) servidores MCP ya configurados que cubren la misma capacidad
    if provee:
        for name, srv in _mcp_servers().items():
            if name == tool_id or not isinstance(srv, dict):
                continue
            caps = {name.lower()} | _norm(srv.get("provee"))
            comunes = provee & caps
            if comunes:
                out.append({"tipo": "mcp", "con": name, "activa": bool(srv.get("enabled", True)),
                            "detalle": f"el servidor MCP '{name}' ya provee: {', '.join(sorted(comunes))}"})

    # 3) puertos ocupados por servicios de docker-compose.yml
    if puertos:
        for name, svc in _compose_services().items():
            if name == tool_id or not isinstance(svc, dict):
                continue
            p = puertos & _ports(svc.get("ports"))
            if p:
                # un servicio con `profiles` no arranca con `docker compose up -d`
                out.append({"tipo": "puerto", "con": name, "activa": not svc.get("profiles"),
                            "detalle": f"puerto {', '.join(sorted(p))} ya usado en docker-compose ('{name}')"})

    # 4) skill local con el mismo nombre que no gestiona el registry
    if tool.get("tipo") == "skill":
        local = integrator.SKILLS_DIR / tool_id
        if local.exists() and not state.get(tool_id, {}).get("integrada"):
            out.append({"tipo": "skill", "con": f"{integrator.SKILLS_DIR.name}/{tool_id}", "activa": True,
                        "detalle": f"ya existe una skill local '{tool_id}' no gestionada por el registry"})
    return out


def blocking(conflicts: list[dict]) -> list[dict]:
    """Conflictos que bloquean (la herramienta rival está activa)."""
    return [c for c in conflicts if c.get("activa")]


def format_conflicts(conflicts: list[dict]) -> str:
    return "; ".join(f"[{c['tipo']}] con '{c['con']}': {c['detalle']}"
                     f"{' (activa)' if c.get('activa') else ''}" for c in conflicts)
