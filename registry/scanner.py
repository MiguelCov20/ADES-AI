"""Escaneo de seguridad de herramientas (feature #16) - ADES-AI, Fase 5.

Audita el código de una herramienta ANTES de integrarla (estilo AgentShield):

1. Reglas propias (regex) sobre el código del repo:
   `curl | sh`, `iwr | iex`, eval/exec de contenido descargado o ofuscado,
   `os.system`, `subprocess(..., shell=True)`, escritura en `~/.ssh`, y claves
   hardcodeadas (reutiliza `PATTERNS` de `environment/scan_secrets.py`).
2. `bandit -r` ejecutado DENTRO del contenedor Docker de QA
   (`core.sandbox.run_command`, `--network none`), nunca en el host.

Severidades: BAJA < MEDIA < ALTA < CRITICA. Veredicto:

- `rechazado`  : algún hallazgo CRITICA.
- `cuarentena` : algún hallazgo ALTA, o bandit pedido pero no se pudo ejecutar.
- `aprobado`   : solo hallazgos MEDIA/BAJA (o ninguno).

El veredicto es una recomendación: la aprobación final es humana
(`quarantine.approve`, feature #25).
"""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_SECRETS = ROOT / "environment" / "scan_secrets.py"

SEVERIDADES = ["BAJA", "MEDIA", "ALTA", "CRITICA"]
BANDIT_SEV = {"LOW": "BAJA", "MEDIUM": "MEDIA", "HIGH": "ALTA"}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}
DOC_EXTS = {".md", ".rst", ".txt", ".adoc"}
CODE_EXTS = {".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
             ".ps1", ".psm1", ".bat", ".cmd", ".rb", ".go", ".rs", ".php", ".pl", ".lua",
             ".yml", ".yaml", ".toml", ".json", ".cfg", ".ini", ".env", ".service"}
CODE_NAMES = {"Dockerfile", "Makefile", "Justfile", "Procfile"}
MAX_FILE_BYTES = 1_000_000
MAX_BANDIT_FILES = 3000

_PY = {".py", ".pyw"}
_ALL = None  # todas las extensiones de código

# (id, severidad, regex, descripción, extensiones o None=todas las de código)
RULES: list[tuple[str, str, re.Pattern, str, set | None]] = [
    ("curl-pipe-sh", "ALTA",
     re.compile(r"\b(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", re.I),
     "descarga y ejecuta un script remoto (curl|sh)", _ALL),
    ("iwr-pipe-iex", "ALTA",
     re.compile(r"\b(iwr|irm|Invoke-WebRequest|Invoke-RestMethod|DownloadString)\b[^\n]*"
                r"(\|\s*(iex|Invoke-Expression)\b|\)\s*\|\s*iex\b)|\biex\s*\([^\n]*DownloadString", re.I),
     "descarga y ejecuta un script remoto (PowerShell iex)", _ALL),
    ("exec-red", "CRITICA",
     re.compile(r"\b(exec|eval)\s*\([^\n]*(urlopen|requests\.(get|post)|urllib|httpx\.|"
                r"http\.client|socket\.|\.recv\()"),
     "eval/exec de contenido obtenido por red", _PY),
    ("eval-fetch-js", "CRITICA",
     re.compile(r"\b(eval|new\s+Function)\s*\([^\n]*\b(fetch|axios|XMLHttpRequest|https?\.get)\b"),
     "eval de contenido obtenido por red (JS)", {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}),
    ("exec-ofuscado", "ALTA",
     re.compile(r"\b(exec|eval)\s*\([^\n]*(b64decode|base64|codecs\.decode|zlib\.decompress|marshal\.loads)"),
     "eval/exec de código ofuscado (base64/zlib/marshal)", _PY),
    ("os-system", "MEDIA",
     re.compile(r"\bos\.system\s*\("),
     "os.system ejecuta comandos a traves de la shell", _PY),
    ("subprocess-shell", "MEDIA",
     re.compile(r"\bsubprocess\.\w+\s*\((?:[^()]|\([^()]*\)){0,400}?\bshell\s*=\s*True"),
     "subprocess con shell=True (riesgo de inyeccion de comandos)", _PY),
    ("ssh-escritura", "CRITICA",
     re.compile(r"open\([^\n]*\.ssh[^\n]*,\s*['\"][wa+]|"
                r"(^|[\s;&|])>>?\s*['\"]?(~|\$HOME|\$\{HOME\}|/root|/home/[\w.-]+)/\.ssh/|"
                r"\.ssh[^\n]*\.(write|write_text|write_bytes|appendFile|writeFile)\b|"
                r"\b(appendFile|writeFile)(Sync)?\([^\n]*\.ssh", re.M),
     "escribe en ~/.ssh (persistencia / robo de acceso)", _ALL),
    ("ssh-claves", "ALTA",
     re.compile(r"\.ssh[/\\](authorized_keys|id_rsa|id_ed25519|id_ecdsa)\b"),
     "accede a claves SSH del usuario", _ALL),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _secret_patterns() -> dict:
    """Reutiliza PATTERNS de environment/scan_secrets.py (fuente única de verdad)."""
    spec = importlib.util.spec_from_file_location("ades_scan_secrets", SCAN_SECRETS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PATTERNS


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not p.is_file():
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p, rel.as_posix()


def _is_code(p: Path) -> bool:
    return p.suffix.lower() in CODE_EXTS or p.name in CODE_NAMES


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan_rules(root: Path) -> list[dict]:
    """Aplica las reglas propias y el detector de secretos a todos los archivos."""
    secrets = _secret_patterns()
    out: list[dict] = []
    for p, rel in _iter_files(root):
        ext = p.suffix.lower()
        es_codigo, es_doc = _is_code(p), ext in DOC_EXTS
        if not (es_codigo or es_doc):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.split("\n")
        if es_codigo:
            for rid, sev, rx, desc, exts in RULES:
                if exts is not None and ext not in exts:
                    continue
                for m in rx.finditer(text):
                    linea = _line_of(text, m.start())
                    frag = lines[linea - 1].strip()[:160]
                    out.append({"origen": "reglas", "regla": rid, "severidad": sev,
                                "archivo": rel, "linea": linea, "detalle": desc, "codigo": frag})
        # secretos: también en documentación (nunca se guarda el valor)
        for n, line in enumerate(lines, 1):
            for name, rx in secrets.items():
                if rx.search(line):
                    out.append({"origen": "secretos", "regla": "secreto-hardcodeado", "severidad": "ALTA",
                                "archivo": rel, "linea": n, "detalle": f"posible secreto: {name}"})
    return out


_BANDIT_SUMMARY = r'''
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
res = d.get("results", [])
orden = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
res.sort(key=lambda r: orden.get(r.get("issue_severity"), 3))
conteo = {}
for r in res:
    conteo[r.get("issue_severity")] = conteo.get(r.get("issue_severity"), 0) + 1
print(json.dumps({"resumido": True, "conteo": conteo, "errors": len(d.get("errors", [])),
    "results": [{k: (r.get(k) or "")[:120] if isinstance(r.get(k), str) else r.get(k)
                 for k in ("filename", "line_number", "issue_severity", "issue_confidence",
                           "test_id", "issue_text")} for r in res[:25]]}))
'''


def _parse_json(output: str) -> dict | None:
    i, j = output.find("{"), output.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(output[i:j + 1])
    except json.JSONDecodeError:
        return None


def run_bandit(root: Path, timeout: int = 300) -> dict:
    """Ejecuta `bandit -r` dentro del sandbox Docker sobre los .py del repo.

    Devuelve {ejecutado, error, hallazgos, conteo, resumido}.
    """
    files: dict[str, str] = {}
    for p, rel in _iter_files(root):
        if p.suffix.lower() in _PY:
            try:
                files[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(files) >= MAX_BANDIT_FILES:
                break
    base = {"ejecutado": False, "error": None, "hallazgos": [], "conteo": {}, "resumido": False,
            "archivos_py": len(files)}
    if not files:
        return {**base, "ejecutado": True}
    try:
        from core import sandbox
        res = sandbox.run_command(files, ["bandit", "-r", ".", "-f", "json", "-q"], timeout=timeout)
        data = _parse_json(res.output)
        if data is None and not res.timed_out:
            # salida truncada por el sandbox (repos grandes): resumen calculado dentro del contenedor
            files["_ades_bandit_summary.py"] = _BANDIT_SUMMARY
            res = sandbox.run_command(files, [
                "sh", "-c", "bandit -r . -f json -q -x ./_ades_bandit_summary.py -o /tmp/bandit.json "
                            ">/dev/null 2>&1; python _ades_bandit_summary.py /tmp/bandit.json"],
                timeout=timeout)
            data = _parse_json(res.output)
    except Exception as e:  # docker no disponible, imagen no construible, etc.
        return {**base, "error": f"{type(e).__name__}: {e}"}
    if res.timed_out:
        return {**base, "error": "bandit excedio el tiempo limite en el sandbox"}
    if data is None or "results" not in data:
        return {**base, "error": f"salida de bandit no interpretable: {res.output[-300:]}"}

    hallazgos = []
    for r in data.get("results", []):
        hallazgos.append({
            "origen": "bandit", "regla": r.get("test_id", ""),
            "severidad": BANDIT_SEV.get(r.get("issue_severity", ""), "BAJA"),
            "archivo": str(r.get("filename", "")).removeprefix("./"),
            "linea": r.get("line_number"),
            "detalle": f"{r.get('issue_text', '')} (confianza {r.get('issue_confidence', '?')})",
        })
    conteo = data.get("conteo")
    if conteo is None:
        conteo = {}
        for r in data.get("results", []):
            conteo[r.get("issue_severity")] = conteo.get(r.get("issue_severity"), 0) + 1
    return {**base, "ejecutado": True, "hallazgos": hallazgos,
            "conteo": {BANDIT_SEV.get(k, "BAJA"): v for k, v in conteo.items()},
            "resumido": bool(data.get("resumido"))}


def verdict(resumen: dict, bandit_ok: bool) -> str:
    if resumen.get("CRITICA"):
        return "rechazado"
    if resumen.get("ALTA") or not bandit_ok:
        return "cuarentena"
    return "aprobado"


def scan_path(path: Path, use_bandit: bool = True) -> dict:
    """Escanea un directorio y devuelve el informe con severidades y veredicto."""
    path = Path(path)
    hallazgos = scan_rules(path)
    bandit = {"ejecutado": False, "error": "omitido (use_bandit=False)", "hallazgos": [],
              "conteo": {}, "resumido": False}
    if use_bandit:
        bandit = run_bandit(path)
        hallazgos += bandit["hallazgos"]

    resumen = {s: 0 for s in SEVERIDADES}
    for h in hallazgos:
        resumen[h["severidad"]] += 1
    if bandit.get("resumido"):  # en modo resumido solo vienen 25 hallazgos: usar el conteo real
        for s in SEVERIDADES:
            reglas = sum(1 for h in hallazgos if h["severidad"] == s and h["origen"] != "bandit")
            resumen[s] = reglas + bandit["conteo"].get(s, 0)

    commit = None
    if (path / ".git").exists():
        from registry import versioning
        commit = versioning.git(["rev-parse", "HEAD"], cwd=path, check=False) or None

    hallazgos.sort(key=lambda h: (-SEVERIDADES.index(h["severidad"]), h["archivo"], h["linea"] or 0))
    return {
        "ruta": str(path),
        "commit": commit,
        "fecha": _now(),
        "hallazgos": hallazgos,
        "resumen": resumen,
        "bandit": {k: v for k, v in bandit.items() if k != "hallazgos"},
        "veredicto": verdict(resumen, bandit["ejecutado"] or not use_bandit),
    }
