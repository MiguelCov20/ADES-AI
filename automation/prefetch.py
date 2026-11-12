"""Prefetch contextual predictivo (feature #12).

A partir de la tarea/ticket actual predice qué contexto se va a pedir y lo
precalienta antes de que el agente lo solicite:

  1. Predicción de archivos/símbolos relacionados:
       - vía el grafo de código Neo4j (labels `CodeFile`/`Class`/`Function` con
         propiedades `path`, `module`, `name`) si está disponible;
       - si no, búsqueda léxica en el repo (rutas, `class`/`def` y contenido).
  2. Precalentado: genera el RepoMap parcial de esos archivos y sus embeddings
     (nomic-embed-text vía Ollama, opcional) y lo guarda en un caché en memoria +
     disco (`state_dir(project)/prefetch/`) con TTL.
  3. `get(task)` busca en el caché por clave exacta o por similitud de la tarea
     (embeddings si hay, Jaccard léxico si no) y mide el hit-rate.

API: `prefetch(task, project) -> dict`, `get(task, project) -> str | None`,
`stats(project) -> dict`.
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from core.config import DEFAULT_PROJECT, ROOT, state_dir

DEFAULT_TTL = float(os.getenv("ADES_PREFETCH_TTL", "900"))
EXCLUDES = {".git", "__pycache__", ".venv", "venv", "node_modules", ".ades", ".opencode",
            ".pytest_cache", "dist", "build", "workspace"}
STOPWORDS = set("""
a al algo como con de del desde el ella en es esta este esto hay la las lo los mas me mi
no o para pero por que se si sin su sus un una uno unos y ya the and for with from into
of to in on is are be add que crea crear haz hacer implementa implementar arregla
arreglar corrige corregir anade agrega agregar nuevo nueva usa usar debe tiene cuando
todo todos cada fix make new use
""".split())

_SYM = re.compile(r"^[ \t]*(class|def|async def)\s+([A-Za-z_]\w*)\s*(\([^)]*\))?", re.M)
_MEM: dict[str, dict[str, dict]] = {}
_LOCK = threading.Lock()


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def keywords(task: str) -> list[str]:
    """Palabras clave de la tarea (identificadores divididos snake/Camel, sin stopwords)."""
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", _strip_accents(task))
    out = []
    for w in raw:
        parts = [w]
        parts += re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", w).split("_")
        for p in parts:
            p = p.lower().strip("_")
            if len(p) >= 3 and p not in STOPWORDS and p not in out:
                out.append(p)
    return out


def task_key(task: str) -> str:
    norm = " ".join(sorted(set(keywords(task)))) or task.strip().lower()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _default_embed(text: str) -> list[float]:
    from cache.semantic_cache import _embed
    return _embed(text)


class Prefetcher:
    """Predice y precalienta el contexto de una tarea para un proyecto."""

    def __init__(self, project: str | None = None, repo: str | os.PathLike | None = None, *,
                 ttl: float = DEFAULT_TTL, top_k: int = 8, use_graph: bool = True,
                 driver=None, embed_fn=None, use_embeddings: bool = True,
                 similarity: float = 0.6, embed_similarity: float = 0.92):
        self.project = project or DEFAULT_PROJECT
        if repo is None:
            try:
                from core import projects
                repo = projects.path_of(self.project)
            except Exception:  # noqa: BLE001
                repo = ROOT
        self.repo = Path(repo).resolve()
        self.ttl = ttl
        self.top_k = top_k
        self.use_graph = use_graph
        self._driver = driver
        self.embed_fn = embed_fn if embed_fn is not None else (
            _default_embed if use_embeddings else None)
        self.similarity = similarity
        self.embed_similarity = embed_similarity
        self.dir = state_dir(self.project) / "prefetch"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- predicción
    def _graph_driver(self):
        if self._driver is not None:
            return self._driver
        from memory.repomap import _driver
        d = _driver()
        d.verify_connectivity()
        self._driver = d
        return d

    def predict_graph(self, kws: list[str]) -> list[dict]:
        """Archivos/símbolos relacionados según el grafo Neo4j (puede lanzar si no hay grafo)."""
        d = self._graph_driver()
        repo_prefix = str(self.repo)
        with d.session() as s:
            rows = s.run(
                "UNWIND $kws AS kw "
                "OPTIONAL MATCH (f:CodeFile) WHERE toLower(f.path) CONTAINS kw "
                "  OR toLower(coalesce(f.module,'')) CONTAINS kw "
                "WITH kw, collect(DISTINCT {path: f.path, name: f.name, kind: 'file'}) AS fs "
                "OPTIONAL MATCH (n) WHERE (n:Class OR n:Function) AND toLower(n.name) CONTAINS kw "
                "RETURN kw, fs, collect(DISTINCT {path: n.path, name: n.name, "
                "  kind: CASE WHEN n:Class THEN 'class' ELSE coalesce(n.kind,'function') END, "
                "  params: n.params}) AS syms",
                kws=kws).data()
        scores: dict[str, dict] = {}
        for r in rows:
            for f in r["fs"]:
                if not f.get("path"):
                    continue
                e = scores.setdefault(f["path"], {"score": 0.0, "symbols": []})
                e["score"] += 3
            for n in r["syms"]:
                if not n.get("path"):
                    continue
                e = scores.setdefault(n["path"], {"score": 0.0, "symbols": []})
                e["score"] += 2
                label = (f"class {n['name']}" if n["kind"] == "class"
                         else f"{n['name']}({n.get('params') or ''})")
                if label not in e["symbols"]:
                    e["symbols"].append(label)
        out = []
        for path, e in scores.items():
            p = Path(path)
            full = p if p.is_absolute() else self.repo / p
            if not str(full.resolve()).lower().startswith(repo_prefix.lower()):
                continue  # el grafo puede tener varios repos indexados
            out.append({"path": path, "score": e["score"], "symbols": e["symbols"],
                        "source": "graph"})
        out.sort(key=lambda x: -x["score"])
        return out[: self.top_k]

    def _iter_py(self):
        for dirpath, dirnames, filenames in os.walk(self.repo):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDES and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield Path(dirpath) / fn

    def predict_lexical(self, kws: list[str]) -> list[dict]:
        """Fallback sin grafo: puntúa los .py del repo por coincidencias léxicas."""
        out = []
        for p in self._iter_py():
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = p.relative_to(self.repo).as_posix().lower()
            low = src.lower()
            syms = _SYM.findall(src)
            score = 0.0
            matched = []
            for kw in kws:
                if kw in rel:
                    score += 3
                for kind, name, params in syms:
                    if kw in name.lower():
                        score += 2
                        lab = f"class {name}" if kind == "class" else f"{name}{params}"
                        if lab not in matched:
                            matched.append(lab)
                score += min(low.count(kw), 5) * 0.2
            if score > 0:
                out.append({"path": p.relative_to(self.repo).as_posix(), "score": round(score, 2),
                            "symbols": matched, "source": "lexical"})
        out.sort(key=lambda x: (-x["score"], x["path"]))
        return out[: self.top_k]

    def predict(self, task: str) -> list[dict]:
        kws = keywords(task)
        if not kws:
            return []
        if self.use_graph:
            try:
                res = self.predict_graph(kws)
                if res:
                    return res
            except Exception:  # noqa: BLE001  Neo4j caído / sin grafo
                pass
        return self.predict_lexical(kws)

    # ------------------------------------------------------------ precalentado
    def _file_map(self, item: dict) -> str:
        p = Path(item["path"])
        p = p if p.is_absolute() else self.repo / p
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            syms = [f"class {n}" if k == "class" else f"{n}{a or '()'}"
                    for k, n, a in _SYM.findall(src)]
        except OSError:
            syms = item.get("symbols", [])
        try:
            rel = p.resolve().relative_to(self.repo).as_posix()
        except ValueError:
            rel = item["path"]
        lines = [rel] + [f"  {s.strip()}" for s in syms[:40]]
        return "\n".join(lines)

    def repomap_partial(self, items: list[dict]) -> str:
        return "\n".join(self._file_map(it) for it in items)

    def _embed(self, text: str):
        if self.embed_fn is None:
            return None
        try:
            return self.embed_fn(text)
        except Exception:  # noqa: BLE001  Ollama caído: seguimos sin embeddings
            return None

    def prefetch(self, task: str) -> dict:
        """Predice y precalienta el contexto de `task`. Devuelve la entrada cacheada."""
        t0 = time.time()
        items = self.predict(task)
        repomap = self.repomap_partial(items)
        task_vec = self._embed(task)
        file_vecs = {}
        if task_vec is not None:
            for it in items:
                v = self._embed(self._file_map(it))
                if v is not None:
                    file_vecs[it["path"]] = v
        entry = {"key": task_key(task), "task": task, "keywords": keywords(task),
                 "created": time.time(), "ttl": self.ttl, "files": items,
                 "repomap": repomap, "task_embedding": task_vec,
                 "file_embeddings": file_vecs,
                 "source": items[0]["source"] if items else "none",
                 "elapsed": round(time.time() - t0, 3)}
        with _LOCK:
            _MEM.setdefault(self.project, {})[entry["key"]] = entry
        (self.dir / f"{entry['key']}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                                       encoding="utf-8")
        return entry

    # ------------------------------------------------------------------ lectura
    def _alive(self, e: dict) -> bool:
        return time.time() - e["created"] <= e.get("ttl", self.ttl)

    def _entries(self) -> list[dict]:
        with _LOCK:
            mem = _MEM.setdefault(self.project, {})
            for f in self.dir.glob("*.json"):
                if f.name == "stats.json" or f.stem in mem:
                    continue
                try:
                    mem[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
            dead = [k for k, e in mem.items() if not self._alive(e)]
            for k in dead:
                mem.pop(k, None)
                (self.dir / f"{k}.json").unlink(missing_ok=True)
            return list(mem.values())

    def lookup(self, task: str) -> dict | None:
        entries = self._entries()
        key = task_key(task)
        for e in entries:
            if e["key"] == key:
                return e
        kws = set(keywords(task))
        best, best_s = None, 0.0
        for e in entries:
            s = _jaccard(kws, set(e.get("keywords", [])))
            if s > best_s:
                best, best_s = e, s
        if best is not None and best_s >= self.similarity:
            return best
        if any(e.get("task_embedding") for e in entries):
            v = self._embed(task)
            if v is not None:
                for e in entries:
                    if e.get("task_embedding") and \
                            _cosine(v, e["task_embedding"]) >= self.embed_similarity:
                        return e
        return None

    def get(self, task: str) -> str | None:
        """RepoMap parcial precalentado para `task` (None si no hay prefetch válido)."""
        e = self.lookup(task)
        self._count(hit=e is not None)
        return e["repomap"] if e is not None else None

    def _count(self, hit: bool) -> None:
        p = self.dir / "stats.json"
        with _LOCK:
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                st = {"hits": 0, "misses": 0}
            st["hits" if hit else "misses"] += 1
            p.write_text(json.dumps(st), encoding="utf-8")

    def stats(self) -> dict:
        try:
            st = json.loads((self.dir / "stats.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            st = {"hits": 0, "misses": 0}
        total = st["hits"] + st["misses"]
        return {**st, "lookups": total, "hit_rate": round(st["hits"] / total, 3) if total else 0.0,
                "cached": len(self._entries())}

    def clear(self) -> None:
        with _LOCK:
            _MEM.pop(self.project, None)
        for f in self.dir.glob("*.json"):
            f.unlink(missing_ok=True)


def prefetch(task: str, project: str | None = None, **kw) -> dict:
    return Prefetcher(project, **kw).prefetch(task)


def get(task: str, project: str | None = None, **kw) -> str | None:
    return Prefetcher(project, **kw).get(task)


def stats(project: str | None = None, **kw) -> dict:
    return Prefetcher(project, **kw).stats()


def main(argv: list[str] | None = None) -> int:
    """`ades prefetch <tarea> [--project P] [--no-graph] [--no-embed]` | `ades prefetch --stats`."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Prefetch contextual predictivo (#12)")
    ap.add_argument("task", nargs="*")
    ap.add_argument("--project", default=None)
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    pf = Prefetcher(a.project, use_graph=not a.no_graph, use_embeddings=not a.no_embed)
    if a.stats or not a.task:
        print(json.dumps(pf.stats(), indent=2))
        return 0
    e = pf.prefetch(" ".join(a.task))
    print(f"fuente={e['source']} archivos={len(e['files'])} t={e['elapsed']}s")
    print(e["repomap"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
