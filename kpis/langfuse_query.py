"""Lectura de uso de tokens/costo desde Langfuse v4 (API v2 de observaciones)."""
import base64
import json
import os
import time
import urllib.parse
import urllib.request

from core import config  # noqa: F401  (carga .env)


def _get(path: str, params: dict) -> dict:
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    auth = base64.b64encode(
        f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()).decode()
    url = f"{host}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def session_observations(session_id: str) -> list[dict]:
    out, cursor = [], None
    while True:
        params = {"limit": 100, "fields": "core,basic,usage,model", "sessionId": session_id,
                  "type": "GENERATION"}
        if cursor:
            params["cursor"] = cursor
        data = _get("/api/public/v2/observations", params)
        out += data.get("data", [])
        cursor = (data.get("meta") or {}).get("cursor")
        if not cursor or not data.get("data"):
            return out


def session_usage(session_id: str, expected: int | None = None, wait_s: int = 90) -> dict:
    """Suma el uso de una sesión. Espera a que Langfuse ingiera `expected` observaciones."""
    t0 = time.time()
    while True:
        obs = session_observations(session_id)
        if expected is None or len(obs) >= expected or time.time() - t0 > wait_s:
            break
        time.sleep(3)
    return {
        "session": session_id, "observaciones": len(obs),
        "input": sum(o.get("inputUsage") or 0 for o in obs),
        "output": sum(o.get("outputUsage") or 0 for o in obs),
        "total": sum(o.get("totalUsage") or 0 for o in obs),
        "cost": round(sum(o.get("totalCost") or 0 for o in obs), 6),
        "pagados": sum(o.get("totalUsage") or 0 for o in obs if (o.get("totalCost") or 0) > 0),
    }
