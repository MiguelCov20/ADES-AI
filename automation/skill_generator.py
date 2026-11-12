"""Auto-skill Generator (feature #31).

Analiza el historial de la fábrica para detectar tareas que se repiten y genera
con el LLM una skill (`SKILL.md`, mismo formato que `.opencode/skills/*/SKILL.md`):

  1. `collect_tasks()`: tareas de `core.metrics_store` (tabla `calls`: task, agent,
     run_id) y de `evals.tracing.load_traces()` (input, agent).
  2. `cluster_tasks()`: clustering voraz por similitud léxica (Jaccard sobre
     palabras clave) o por embeddings si se pasa `embed_fn`. Las ocurrencias se
     cuentan por run distinto para no inflar con las llamadas de un mismo run.
  3. `generate()`: el LLM redacta la SKILL.md; se valida/normaliza el frontmatter.
  4. `stage()`: escribe en `state_dir()/skills_staging/auto-<slug>/SKILL.md`.
     Nada se publica sin `publish(slug)`, que copia a `.opencode/skills/auto-<slug>/`.
"""
import json
import re
import shutil
import time
import unicodedata
from pathlib import Path

from core.config import ROOT, state_dir

SKILLS_DIR = ROOT / ".opencode" / "skills"
STOP = set("""
a al algo como con de del desde el en es esta este esto la las lo los mas mi no o para
pero por que se si sin su sus un una uno unos y ya the and for with from of to in on
is are by eres tu usted responde solo json requerimiento tarea
""".split())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9_]{2,}", _norm(text)) if w not in STOP}


def slugify(text: str, max_words: int = 5) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", _norm(text)) if w not in STOP]
    return "-".join(words[:max_words])[:50].strip("-") or "tarea"


def staging_dir(project: str | None = None) -> Path:
    d = state_dir(project) / "skills_staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------- recolección
def collect_tasks(project: str | None = None, since: float | None = None,
                  include_traces: bool = True) -> list[dict]:
    """[{task, agent, run, source}] del historial (métricas SQLite + trazas)."""
    from core import metrics_store
    where, params = ["task IS NOT NULL", "task != ''", "cache_hit = 0"], []
    if project:
        where.append("project = ?")
        params.append(project)
    if since:
        where.append("ts >= ?")
        params.append(since)
    rows = metrics_store.query(
        f"SELECT task, agent, run_id, ts FROM calls WHERE {' AND '.join(where)} ORDER BY ts",
        tuple(params))
    out = [{"task": r["task"], "agent": r["agent"], "run": r["run_id"] or f"m{i}",
            "source": "metrics"} for i, r in enumerate(rows)]
    if include_traces:
        from evals import tracing
        for i, t in enumerate(tracing.load_traces()):
            if since and t.get("ts", 0) < since:
                continue
            md = t.get("metadata") or {}
            if md.get("cache_hit") or (project and md.get("project") not in (None, project)):
                continue
            text = (t.get("input") or "").strip()
            if text:
                # el input de la traza es "contexto\n\nusuario": nos quedamos con la petición
                out.append({"task": text.split("\n\n")[-1][:300], "agent": t.get("agent", ""),
                            "run": f"t{t.get('ts', i)}", "source": "traces"})
    return out


# ------------------------------------------------------------------ clustering
def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def cluster_tasks(tasks: list[dict], threshold: float = 0.5, embed_fn=None,
                  embed_threshold: float = 0.85) -> list[dict]:
    """Clustering voraz: cada tarea se une al primer cluster suficientemente similar."""
    clusters: list[dict] = []
    for t in tasks:
        toks = tokens(t["task"])
        if not toks:
            continue
        vec = None
        if embed_fn is not None:
            try:
                vec = embed_fn(t["task"])
            except Exception:  # noqa: BLE001
                vec = None
        best, best_s = None, 0.0
        for c in clusters:
            if vec is not None and c.get("vec") is not None:
                s = _cos(vec, c["vec"])
                ok = s >= embed_threshold
            else:
                s = len(toks & c["tokens"]) / len(toks | c["tokens"])
                ok = s >= threshold
            if ok and s > best_s:
                best, best_s = c, s
        if best is None:
            clusters.append({"tokens": set(toks), "core": set(toks), "vec": vec, "items": [t]})
        else:
            best["items"].append(t)
            best["core"] &= toks or best["core"]
    for c in clusters:
        runs = {i["run"] for i in c["items"]}
        uniq = list(dict.fromkeys(i["task"] for i in c["items"]))
        c["count"] = len(runs)
        c["examples"] = uniq[:8]
        c["agents"] = sorted({i["agent"] for i in c["items"] if i["agent"]})
        c["representative"] = uniq[0]
        c["slug"] = slugify(" ".join(sorted(c["core"])) if len(c["core"]) >= 2
                            else c["representative"])
    clusters.sort(key=lambda c: -c["count"])
    return clusters


def detect(min_count: int = 3, threshold: float = 0.5, project: str | None = None,
           tasks: list[dict] | None = None, embed_fn=None) -> list[dict]:
    """Clusters con >= `min_count` ocurrencias (runs distintos)."""
    tasks = collect_tasks(project) if tasks is None else tasks
    res = []
    for c in cluster_tasks(tasks, threshold=threshold, embed_fn=embed_fn):
        if c["count"] >= min_count:
            res.append({k: v for k, v in c.items() if k not in ("tokens", "core", "vec", "items")})
    return res


# ------------------------------------------------------------------- generación
SYSTEM = (
    "Eres el generador de skills de ADES-AI. Una skill es un archivo SKILL.md que un agente "
    "carga bajo demanda para resolver un tipo de tarea repetida. Formato OBLIGATORIO:\n"
    "---\nname: <nombre corto>\ndescription: <una linea: que hace y cuando usarla>\n---\n\n"
    "## Objetivo\n\n<1-3 frases>\n\n## Workflow\n\n1. <paso>\n2. <paso>\n\n## Notas\n\n- <nota>\n"
    "Escribe en español, conciso (menos de 40 lineas). No inventes comandos, rutas ni APIs "
    "que no aparezcan en los ejemplos; si no sabes algo, descríbelo de forma genérica. "
    "Responde SOLO con el contenido del SKILL.md."
)


def _fix_format(text: str, cluster: dict) -> str:
    t = text.strip()
    m = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", t, re.S)
    if m and "## " in m.group(1):
        t = m.group(1).strip()
    i = t.find("---")
    if i > 0:
        t = t[i:]
    meta: dict = {}
    body = t
    # Puede haber uno o varios frontmatter, cerrados o no (los LLM pequeños olvidan el
    # `---` final): se consumen todos y se conserva el primer valor de cada clave.
    while body.lstrip().startswith("---"):
        lines = body.lstrip()[3:].lstrip("\n").splitlines()
        i = 0
        while i < len(lines) and re.match(r"^[A-Za-z_-]+\s*:", lines[i]):
            k, v = lines[i].split(":", 1)
            meta.setdefault(k.strip().lower(), v.strip().strip('"'))
            i += 1
        if i < len(lines) and lines[i].strip() == "---":
            i += 1
        body = "\n".join(lines[i:])
    name = meta.get("name") or f"Auto {cluster['slug'].replace('-', ' ')}"
    desc = meta.get("description") or f"Skill generada para tareas como: {cluster['representative'][:100]}"
    body = body.strip()
    if "## Objetivo" not in body:
        body = f"## Objetivo\n\n{cluster['representative'][:200]}\n\n" + body
    if "## Workflow" not in body:
        body += "\n\n## Workflow\n\n1. Revisa los ejemplos de la sección Notas y aplica el mismo patrón."
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n{body.strip()}\n"


def validate_skill(text: str) -> list[str]:
    """Problemas de formato de una SKILL.md (lista vacía = válida)."""
    errs = []
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not fm:
        return ["falta el frontmatter ---"]
    if not re.search(r"^name:\s*\S", fm.group(1), re.M):
        errs.append("falta name")
    if not re.search(r"^description:\s*\S", fm.group(1), re.M):
        errs.append("falta description")
    if re.search(r"^---\s*\n\s*name\s*:", text[fm.end():], re.M):
        errs.append("frontmatter duplicado")
    for sec in ("## Objetivo", "## Workflow"):
        if sec not in text:
            errs.append(f"falta la sección {sec}")
    return errs


def generate(cluster: dict, *, provider: str | None = "ollama", model: str | None = "gpt-oss:20b",
             project: str | None = None) -> str:
    from core.llm_gateway import chat
    ejemplos = "\n".join(f"- {e}" for e in cluster["examples"])
    user = (f"Tarea repetida {cluster['count']} veces (agentes: "
            f"{', '.join(cluster.get('agents', [])) or 'n/d'}). Ejemplos reales:\n{ejemplos}\n\n"
            "Escribe la SKILL.md que ayude a resolver este tipo de tarea.")
    res = chat("skill_generator", SYSTEM, user, provider=provider, model=model, project=project,
               use_cache=False)
    return _fix_format(res.text, cluster)


def stage(cluster: dict, text: str, project: str | None = None) -> Path:
    d = staging_dir(project) / f"auto-{cluster['slug']}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(
        {"slug": cluster["slug"], "count": cluster["count"], "examples": cluster["examples"],
         "agents": cluster.get("agents", []), "ts": time.time()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return d / "SKILL.md"


def list_staged(project: str | None = None) -> list[str]:
    return sorted(p.parent.name[len("auto-"):] for p in staging_dir(project).glob("auto-*/SKILL.md"))


def publish(slug: str, project: str | None = None, skills_dir: str | Path | None = None,
            force: bool = False) -> Path:
    """Publica una skill en staging a `.opencode/skills/auto-<slug>/SKILL.md`."""
    slug = slug[len("auto-"):] if slug.startswith("auto-") else slug
    src = staging_dir(project) / f"auto-{slug}" / "SKILL.md"
    if not src.exists():
        raise FileNotFoundError(f"No hay skill en staging con slug '{slug}'")
    errs = validate_skill(src.read_text(encoding="utf-8"))
    if errs:
        raise ValueError(f"SKILL.md inválida: {', '.join(errs)}")
    dst_dir = Path(skills_dir or SKILLS_DIR) / f"auto-{slug}"
    dst = dst_dir / "SKILL.md"
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} ya existe (usa force=True)")
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def run(min_count: int = 3, threshold: float = 0.5, project: str | None = None,
        provider: str | None = "ollama", model: str | None = "gpt-oss:20b",
        tasks: list[dict] | None = None, max_skills: int = 3,
        skills_dir: str | Path | None = None) -> list[dict]:
    """Detecta tareas repetidas y deja las skills nuevas en staging (no publica)."""
    published = {p.name for p in Path(skills_dir or SKILLS_DIR).glob("auto-*")}
    staged = set(list_staged(project))
    out = []
    for c in detect(min_count, threshold, project, tasks):
        if len(out) >= max_skills:
            break
        if f"auto-{c['slug']}" in published or c["slug"] in staged:
            continue
        text = generate(c, provider=provider, model=model, project=project)
        path = stage(c, text, project)
        out.append({"slug": c["slug"], "count": c["count"], "path": str(path),
                    "errores_formato": validate_skill(text)})
    return out


def main(argv: list[str] | None = None) -> int:
    """`ades skills detect|generate|staged|publish <slug>` (generate solo deja en staging)."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Auto-skill Generator (#31)")
    ap.add_argument("cmd", choices=["detect", "generate", "staged", "publish"])
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--project", default=None)
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.cmd == "detect":
        r = detect(a.min, project=a.project)
    elif a.cmd == "generate":
        r = run(a.min, project=a.project, model=a.model)
    elif a.cmd == "staged":
        r = list_staged(a.project)
    else:
        if not a.slug:
            ap.error("publish necesita el slug")
        r = str(publish(a.slug, project=a.project, force=a.force))
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
