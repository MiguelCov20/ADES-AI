""""Vacuna" contra bugs (feature #8) - ADES-AI.

Cada bug resuelto se guarda como patrón (firma del error normalizada + código
implicado + corrección) para que la fábrica no lo repita: antes de generar o
corregir código, `context_for(texto)` inyecta en el prompt los errores
parecidos ya resueltos.

  - Firma normalizada: tipo de excepción + mensaje, sin rutas, números de
    línea, direcciones de memoria ni números concretos.
  - Almacén SQLite global (`global_state_dir()/vaccines.db`): las vacunas son
    cross-proyecto (un bug de un proyecto protege a todos).
  - Búsqueda por similitud de embeddings (nomic-embed-text vía Ollama, con la
    misma función de `memory.knowledge`); sin Ollama cae a similitud léxica.

Uso:
    python -m memory.vaccine match "TypeError: unsupported operand ..."
"""
import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.config import DEFAULT_PROJECT, global_state_dir
from memory import knowledge

DEFAULT_MIN_SCORE = 0.80
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS vaccines (
    id TEXT PRIMARY KEY,
    ts REAL, updated REAL,
    signature TEXT, error_type TEXT,
    fix TEXT, fix_norm TEXT,
    project TEXT, code_pattern TEXT,
    sig_embedding TEXT, code_embedding TEXT,
    hits INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_vacc_sig ON vaccines(signature);
"""

# ---------------------------------------------------------------------------
# Normalización y extracción de firmas
# ---------------------------------------------------------------------------
_EXC_RE = re.compile(
    r"^\s*(?:E\s+)?((?:[A-Za-z_][\w]*\.)*[A-Za-z_]\w*"
    r"(?:Error|Exception|Warning|Exit|Interrupt|Failure|Failed|Timeout))\b(?::\s*(.*))?$")
_PYTEST_FAILED_RE = re.compile(r"^FAILED\s+\S+\s+-\s+(.+)$")
_PYTEST_E_RE = re.compile(r"^E\s+(.+)$")
_CODE_LINE_RE = re.compile(r'^\s*File\s+"[^"]+",\s+line\s+\d+')


def normalize_signature(text: str) -> str:
    """Quita lo variable de un mensaje de error: rutas, líneas, direcciones, números."""
    s = text or ""
    s = re.sub(r'File\s+"[^"]*"', 'File "<ruta>"', s)
    s = re.sub(r"[A-Za-z]:[\\/][^\s'\",:)]+", "<ruta>", s)            # rutas Windows
    s = re.sub(r"(?<![\w<])(?:\.{0,2}/)?(?:[\w.\-]+/)+[\w.\-]+", "<ruta>", s)  # rutas POSIX
    s = re.sub(r"\b0x[0-9a-fA-F]+\b", "<dir>", s)                     # direcciones
    s = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "<id>", s)    # uuids
    s = re.sub(r"\bline\s+\d+", "line <n>", s)
    s = re.sub(r"(?<=[\w>]):\d+(?::\d+)?\b", ":<n>", s)               # fichero:línea[:col]
    s = re.sub(r"(?<![\w<])-?\d+(?:\.\d+)?(?![\w>])", "<n>", s)        # números sueltos
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300]


def error_type(signature: str) -> str:
    m = re.match(r"^\s*([A-Za-z_][\w.]*)\s*:", signature or "")
    if m:
        return m.group(1).split(".")[-1]
    m = _EXC_RE.match(signature or "")
    return m.group(1).split(".")[-1] if m else ""


def extract_signature(feedback: str) -> str | None:
    """Extrae la firma del error de una salida de QA (traceback / pytest).

    Prioridad: última línea de excepción del traceback, línea `FAILED ... - X`
    de pytest, primera línea `E   assert ...`. Devuelve None si no hay error.
    """
    lines = [ln.rstrip() for ln in (feedback or "").splitlines() if ln.strip()]
    exc = None
    for ln in lines:
        m = _EXC_RE.match(ln)
        if m:
            exc = m.group(1) + (f": {m.group(2).strip()}" if m.group(2) else "")
    if exc:
        return normalize_signature(exc)
    for ln in lines:
        m = _PYTEST_FAILED_RE.match(ln.strip())
        if m:
            return normalize_signature(m.group(1))
    for ln in lines:
        m = _PYTEST_E_RE.match(ln)
        if m and m.group(1).lstrip().startswith("assert"):
            return normalize_signature("AssertionError: " + m.group(1).strip())
    for ln in lines:
        if re.search(r"\b(error|fail(ed|ure)?|exception)\b", ln, re.I):
            return normalize_signature(ln)
    return None


def extract_code_pattern(feedback: str, max_lines: int = 6) -> str:
    """Líneas de código implicadas según el traceback (`File ..., line N` o `>` de pytest)."""
    lines = (feedback or "").splitlines()
    code = []
    for i, ln in enumerate(lines):
        if _CODE_LINE_RE.match(ln) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt and not _CODE_LINE_RE.match(lines[i + 1]):
                code.append(nxt)
        elif ln.startswith(">"):
            code.append(ln[1:].strip())
    seen, out = set(), []
    for c in code:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return "\n".join(out[-max_lines:])


# ---------------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------------
def db_path() -> Path:
    return global_state_dir() / "vaccines.db"


@contextmanager
def _conn():
    c = sqlite3.connect(str(db_path()), timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        with c:
            yield c
    finally:
        c.close()


def _row(r: sqlite3.Row, with_embedding: bool = False) -> dict:
    d = dict(r)
    d.pop("fix_norm", None)
    se, ce = d.pop("sig_embedding", None), d.pop("code_embedding", None)
    if with_embedding:
        d["sig_embedding"] = json.loads(se) if se else None
        d["code_embedding"] = json.loads(ce) if ce else None
    return d


def add(error_signature: str, fix: str, project: str | None = None,
        code_pattern: str = "") -> dict:
    """Guarda una vacuna (firma normalizada + corrección).

    Si ya existe la misma firma con la misma corrección, solo suma `hits`.
    """
    sig = normalize_signature(error_signature)
    fix = (fix or "").strip()
    if not sig or not fix:
        raise ValueError("vaccine.add: firma y corrección son obligatorias")
    project = project or DEFAULT_PROJECT
    fix_norm = knowledge.normalize(fix)[:4000]
    now = time.time()
    with _LOCK, _conn() as c:
        dup = c.execute("SELECT id FROM vaccines WHERE signature=? AND fix_norm=?",
                        (sig, fix_norm)).fetchone()
        if dup is not None:
            c.execute("UPDATE vaccines SET hits=hits+1, updated=? WHERE id=?", (now, dup["id"]))
            out = _row(c.execute("SELECT * FROM vaccines WHERE id=?", (dup["id"],)).fetchone())
            out["duplicate"] = True
            return out
    sig_emb = knowledge.embed(sig)
    code_emb = knowledge.embed(code_pattern) if code_pattern.strip() else None
    vid = uuid.uuid4().hex[:16]
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO vaccines (id, ts, updated, signature, error_type, fix, fix_norm, "
            "project, code_pattern, sig_embedding, code_embedding, hits) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            (vid, now, now, sig, error_type(sig), fix, fix_norm, project, code_pattern,
             json.dumps(sig_emb) if sig_emb else None,
             json.dumps(code_emb) if code_emb else None))
        out = _row(c.execute("SELECT * FROM vaccines WHERE id=?", (vid,)).fetchone())
    out["duplicate"] = False
    return out


def all_vaccines(since: float | None = None, with_embedding: bool = False) -> list[dict]:
    with _LOCK, _conn() as c:
        if since is None:
            rows = c.execute("SELECT * FROM vaccines ORDER BY ts").fetchall()
        else:
            rows = c.execute("SELECT * FROM vaccines WHERE updated >= ? ORDER BY ts",
                             (since,)).fetchall()
    return [_row(r, with_embedding) for r in rows]


def match(text: str, k: int = 3, min_score: float = DEFAULT_MIN_SCORE) -> list[dict]:
    """Vacunas cuyo error (o código implicado) se parece a `text`.

    `text` puede ser un traceback, una salida de pytest, una firma o un trozo
    de código. Score = máx(similitud de firma, 0.95·similitud de código); una
    firma idéntica puntúa 1.0.
    """
    vaccines = all_vaccines(with_embedding=True)
    if not vaccines or not (text or "").strip():
        return []
    sig = extract_signature(text) or normalize_signature(text)
    q_sig = knowledge.embed(sig)
    q_code = knowledge.embed(text[:2000]) if text.strip() != sig else q_sig
    q_type = error_type(sig)
    out = []
    for v in vaccines:
        if v["signature"] == sig:
            score = 1.0
        else:
            s_sig = knowledge.similarity(sig, q_sig, v["signature"], v.pop("sig_embedding"))
            if q_type and v["error_type"] and q_type != v["error_type"]:
                s_sig *= 0.9  # tipos de excepción distintos: penaliza
            s_code = 0.0
            if v.get("code_pattern"):
                s_code = 0.95 * knowledge.similarity(text[:2000], q_code, v["code_pattern"],
                                                     v.get("code_embedding"))
            score = max(s_sig, s_code)
        v.pop("sig_embedding", None)
        v.pop("code_embedding", None)
        if score >= min_score:
            v["score"] = round(score, 4)
            out.append(v)
    out.sort(key=lambda d: (d["score"], d["hits"]), reverse=True)
    return out[:k]


def context_for(text: str) -> str:
    """Texto para el prompt con los bugs parecidos ya resueltos ("" si ninguno)."""
    hits = match(text)
    if not hits:
        return ""
    lines = ["Vacunas (errores parecidos ya resueltos; NO repitas estos fallos):"]
    for h in hits:
        fix = h["fix"] if len(h["fix"]) <= 600 else h["fix"][:600] + "\n..."
        lines.append(f"- Error: {h['signature']} (visto {h['hits']} vez/veces)")
        if h.get("code_pattern"):
            lines.append(f"  Código implicado: {h['code_pattern'][:300]}")
        lines.append("  Corrección:\n    " + fix.replace("\n", "\n    "))
    return "\n".join(lines)


def learn_from_failure(qa_feedback: str, fixed_code: str,
                       project: str | None = None) -> dict | None:
    """Convierte un fallo de QA ya corregido en vacuna.

    Extrae la firma del error del feedback de QA y guarda `fixed_code` como
    corrección. Devuelve None si no se reconoce ningún error o no hay código.
    """
    sig = extract_signature(qa_feedback)
    if not sig or not (fixed_code or "").strip():
        return None
    fix = fixed_code.strip()
    if len(fix) > 4000:
        fix = fix[:4000] + "\n# ... (truncado)"
    return add(sig, fix, project=project, code_pattern=extract_code_pattern(qa_feedback))


def forget(ids: list[str]) -> int:
    if not ids:
        return 0
    with _LOCK, _conn() as c:
        return c.execute(f"DELETE FROM vaccines WHERE id IN ({','.join('?' * len(ids))})",
                         tuple(ids)).rowcount


def forget_project(project: str) -> int:
    with _LOCK, _conn() as c:
        return c.execute("DELETE FROM vaccines WHERE project=?", (project,)).rowcount


def bump(vid: str, hits: int = 1, updated: float | None = None) -> None:
    with _LOCK, _conn() as c:
        c.execute("UPDATE vaccines SET hits=hits+?, updated=MAX(updated, ?) WHERE id=?",
                  (hits, updated or 0, vid))


def vacuum() -> None:
    with _LOCK:
        c = sqlite3.connect(str(db_path()), timeout=30)
        try:
            c.execute("VACUUM")
        finally:
            c.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description='"Vacuna" contra bugs (#8)')
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_m = sub.add_parser("match", help="busca bugs parecidos ya resueltos")
    p_m.add_argument("text")
    sub.add_parser("list", help="lista las vacunas")
    args = ap.parse_args(argv)
    if args.cmd == "match":
        print(context_for(args.text) or "[OK] sin vacunas parecidas")
    else:
        for v in all_vaccines():
            print(f"  {v['id']} x{v['hits']} [{v['project']}] {v['signature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
