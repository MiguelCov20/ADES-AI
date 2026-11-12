"""Agente "Watchdog" 24/7 (feature #3).

Vigila el repositorio de un proyecto (por defecto el registrado en `core.projects`)
por polling de mtimes + hash (sin dependencias nuevas). Ante un cambio:

  1. Compila los `.py` cambiados con `compile()` (equivale a py_compile pero sin
     escribir `.pyc`; NO ejecuta el código).
  2. Ejecuta los tests del proyecto en el sandbox Docker (`core.sandbox`). Regla 5
     de AGENTS.md: QA nunca ejecuta código fuera de Docker, así que no existe modo
     "local" para los tests.
  3. Si algo se rompe, emite una alerta:
       - log en `state_dir(project)/watchdog.log`,
       - entrada JSON en `state_dir(project)/alerts.jsonl`,
       - notificación toast de Windows vía PowerShell (best-effort, desactivable con
         `notify=False` o `ADES_WATCHDOG_TOAST=0`).

Uso:
    python -m automation.watchdog --project ades-ai --once
    python -m automation.watchdog --project ades-ai --interval 60
    python -m automation.watchdog --project ades-ai --install-task [--apply]
"""
import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from core.config import DEFAULT_PROJECT, ROOT, state_dir

DEFAULT_EXCLUDES = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".ades",
                    ".opencode", ".pytest_cache", ".mypy_cache", "dist", "build", ".idea",
                    ".vscode", "workspace"}
WATCH_EXT = (".py", ".toml", ".cfg", ".ini", ".txt", ".json", ".yaml", ".yml")
SANDBOX_EXT = (".py", ".toml", ".cfg", ".ini", ".txt", ".json", ".yaml", ".yml")
MAX_FILE_BYTES = 512_000
TASK_PREFIX = "ADES-AI Watchdog"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_repo(project: str, repo: str | os.PathLike | None) -> Path:
    if repo:
        return Path(repo).resolve()
    try:
        from core import projects
        return projects.path_of(project)
    except Exception:  # noqa: BLE001
        return ROOT


def toast_script(title: str, message: str) -> str:
    """Script PowerShell que muestra un toast de Windows (API WinRT, sin módulos extra)."""
    def esc(s: str) -> str:
        return s.replace("'", "''").replace("\r", " ").replace("\n", " ")[:250]
    aumid = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null; "
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$n = $t.GetElementsByTagName('text'); "
        f"$n.Item(0).AppendChild($t.CreateTextNode('{esc(title)}')) > $null; "
        f"$n.Item(1).AppendChild($t.CreateTextNode('{esc(message)}')) > $null; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{aumid}').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )


def windows_toast(title: str, message: str) -> bool:
    """Muestra un toast de Windows. Best-effort: devuelve False si no se pudo."""
    if os.name != "nt":
        return False
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            toast_script(title, message)],
                           capture_output=True, timeout=20)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


class Watchdog:
    """Vigilante de un repositorio.

    `sandbox_runner(files: dict[str, str]) -> SandboxResult` y `notifier(title, msg)`
    son inyectables (tests). Por defecto se usan `core.sandbox.run_tests` y el toast.
    """

    def __init__(self, project: str | None = None, repo: str | os.PathLike | None = None, *,
                 notify: bool | None = None, run_tests: bool = True, sandbox_runner=None,
                 notifier=None, exclude_dirs: set | None = None, max_files: int = 400,
                 test_timeout: int = 300, check_on_baseline: bool = True):
        self.project = project or DEFAULT_PROJECT
        self.repo = _resolve_repo(self.project, repo)
        if notify is None:
            notify = os.getenv("ADES_WATCHDOG_TOAST", "1") not in ("0", "false", "no")
        self.notify = notify
        self.run_tests_enabled = run_tests
        self.sandbox_runner = sandbox_runner
        self.notifier = notifier or windows_toast
        self.exclude_dirs = set(exclude_dirs or DEFAULT_EXCLUDES)
        self.max_files = max_files
        self.test_timeout = test_timeout
        self.check_on_baseline = check_on_baseline
        self.dir = state_dir(self.project)
        self.log_path = self.dir / "watchdog.log"
        self.alerts_path = self.dir / "alerts.jsonl"
        self.snapshot_path = self.dir / "watchdog_snapshot.json"
        self.status_path = self.dir / "watchdog_status.json"
        self.log = logging.getLogger(f"ades.watchdog.{self.project}")
        if not any(getattr(h, "baseFilename", None) == str(self.log_path)
                   for h in self.log.handlers):
            h = logging.FileHandler(self.log_path, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(h)
        self.log.setLevel(logging.INFO)

    # ------------------------------------------------------------------ escaneo
    def iter_files(self):
        for dirpath, dirnames, filenames in os.walk(self.repo):
            dirnames[:] = [d for d in dirnames if d not in self.exclude_dirs
                           and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(WATCH_EXT):
                    yield Path(dirpath) / fn

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.repo).as_posix()

    def snapshot(self, previous: dict | None = None) -> dict:
        """{ruta_relativa: [mtime_ns, tamaño, sha1]}. Solo rehashea si mtime/tamaño cambian."""
        previous = previous or {}
        snap = {}
        for p in self.iter_files():
            try:
                st = p.stat()
            except OSError:
                continue
            rel = self._rel(p)
            old = previous.get(rel)
            if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
                snap[rel] = old
            else:
                try:
                    snap[rel] = [st.st_mtime_ns, st.st_size, _sha1(p)]
                except OSError:
                    continue
        return snap

    @staticmethod
    def diff(old: dict, new: dict) -> dict:
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        modified = sorted(k for k in set(old) & set(new) if old[k][2] != new[k][2])
        return {"added": added, "modified": modified, "removed": removed}

    def load_snapshot(self) -> dict | None:
        if self.snapshot_path.exists():
            try:
                return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        return None

    def save_snapshot(self, snap: dict) -> None:
        self.snapshot_path.write_text(json.dumps(snap), encoding="utf-8")

    # ---------------------------------------------------------------- chequeos
    def check_compile(self, rel_paths: list[str]) -> list[dict]:
        """Compila (sin ejecutar) los .py indicados. Devuelve los errores de sintaxis."""
        errors = []
        for rel in rel_paths:
            if not rel.endswith(".py"):
                continue
            p = self.repo / rel
            try:
                src = p.read_bytes()
                compile(src, str(p), "exec", dont_inherit=True)
            except SyntaxError as e:
                errors.append({"file": rel, "line": e.lineno, "error": f"SyntaxError: {e.msg}"})
            except (OSError, ValueError) as e:
                errors.append({"file": rel, "line": None, "error": f"{type(e).__name__}: {e}"})
        return errors

    def collect_sandbox_files(self) -> dict[str, str]:
        files = {}
        for p in self.iter_files():
            if not p.name.endswith(SANDBOX_EXT):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                files[self._rel(p)] = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(files) >= self.max_files:
                break
        return files

    def run_project_tests(self):
        """Ejecuta los tests del repo en el sandbox Docker. None si no hay tests."""
        files = self.collect_sandbox_files()
        has_tests = any(Path(n).name.startswith("test_") or Path(n).name.endswith("_test.py")
                        for n in files)
        if not has_tests:
            return None
        if self.sandbox_runner is not None:
            return self.sandbox_runner(files)
        from core import sandbox
        return sandbox.run_tests(files, timeout=self.test_timeout)

    # ----------------------------------------------------------------- alertas
    def alert(self, report: dict) -> dict:
        problems = []
        for e in report["compile_errors"]:
            problems.append(f"{e['file']}:{e['line']} {e['error']}")
        t = report.get("tests")
        if t and not t["passed"]:
            problems.append(f"tests fallan ({t['tests_failed']}/{t['tests_run']}, "
                            f"exit={t['exit_code']})")
        entry = {"ts": time.time(), "project": self.project, "repo": str(self.repo),
                 "changes": report["changes"], "problems": problems,
                 "tests_output": (t or {}).get("output", "")[-2000:]}
        with open(self.alerts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.log.error("ROTO: %s", " | ".join(problems))
        entry["notified"] = False
        if self.notify:
            try:
                entry["notified"] = bool(self.notifier(f"ADES-AI Watchdog: {self.project}",
                                                       "; ".join(problems)[:240]))
            except Exception:  # noqa: BLE001
                entry["notified"] = False
        return entry

    # -------------------------------------------------------------------- ciclo
    def run_once(self) -> dict:
        """Una pasada: detecta cambios, compila, ejecuta tests y alerta si hay roturas."""
        prev = self.load_snapshot()
        snap = self.snapshot(prev)
        baseline = prev is None
        changes = (self.diff({}, snap) if baseline else self.diff(prev, snap))
        changed = changes["added"] + changes["modified"]
        report = {"ts": time.time(), "project": self.project, "repo": str(self.repo),
                  "baseline": baseline, "changes": changes, "compile_errors": [],
                  "tests": None, "broken": False, "alert": None}
        self.save_snapshot(snap)
        n_changes = len(changed) + len(changes["removed"])
        if n_changes == 0 or (baseline and not self.check_on_baseline):
            report["skipped"] = True
            self.log.info("sin cambios (%d archivos vigilados)", len(snap))
            return report
        self.log.info("cambios: +%d ~%d -%d", len(changes["added"]),
                      len(changes["modified"]), len(changes["removed"]))
        report["compile_errors"] = self.check_compile(changed)
        if self.run_tests_enabled:
            try:
                res = self.run_project_tests()
            except Exception as e:  # noqa: BLE001  (Docker caído, imagen ausente...)
                res = None
                report["tests_error"] = f"{type(e).__name__}: {e}"[:300]
                self.log.warning("no se pudieron ejecutar los tests: %s", report["tests_error"])
            if res is not None:
                report["tests"] = {"passed": res.passed, "exit_code": res.exit_code,
                                   "tests_run": res.tests_run, "tests_failed": res.tests_failed,
                                   "timed_out": res.timed_out, "output": res.output[-4000:]}
        t = report["tests"]
        report["broken"] = bool(report["compile_errors"]) or bool(t and not t["passed"])
        prev_status = self._load_status()
        if report["broken"]:
            report["alert"] = self.alert(report)
        else:
            self.log.info("OK (tests=%s)", "sin tests" if t is None else
                          f"{t['tests_run']} ok")
            if prev_status.get("broken"):
                self.log.info("RECUPERADO: el repo vuelve a estar sano")
        self._save_status({"broken": report["broken"], "ts": report["ts"]})
        return report

    def _load_status(self) -> dict:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_status(self, st: dict) -> None:
        self.status_path.write_text(json.dumps(st), encoding="utf-8")

    def run_forever(self, interval: float = 30.0, max_iterations: int | None = None,
                    sleep=time.sleep) -> int:
        """Bucle de vigilancia. Devuelve el número de iteraciones realizadas."""
        i = 0
        while max_iterations is None or i < max_iterations:
            try:
                self.run_once()
            except Exception as e:  # noqa: BLE001  el watchdog nunca debe morir
                self.log.exception("error en la pasada: %s", e)
            i += 1
            if max_iterations is not None and i >= max_iterations:
                break
            sleep(interval)
        return i


def run_once(project: str | None = None, repo=None, **kw) -> dict:
    return Watchdog(project, repo, **kw).run_once()


def run_forever(interval: float = 30.0, project: str | None = None, repo=None,
                max_iterations: int | None = None, **kw) -> int:
    return Watchdog(project, repo, **kw).run_forever(interval, max_iterations)


def task_name(project: str | None = None) -> str:
    return f"{TASK_PREFIX} {project or DEFAULT_PROJECT}"


def install_task(project: str | None = None, interval_minutes: int = 5,
                 dry_run: bool = True, python: str | None = None) -> dict:
    """Crea (o en dry_run solo devuelve) la tarea programada de Windows (schtasks).

    La tarea ejecuta `python -m automation.watchdog --project P --once` cada
    `interval_minutes` minutos desde la raíz de ADES-AI.
    """
    project = project or DEFAULT_PROJECT
    py = python or sys.executable
    tr = f'cmd /c cd /d "{ROOT}" && "{py}" -m automation.watchdog --project {project} --once'
    cmd = ["schtasks", "/Create", "/SC", "MINUTE", "/MO", str(int(interval_minutes)),
           "/TN", task_name(project), "/TR", tr, "/F"]
    result = {"command": cmd, "dry_run": dry_run, "created": False}
    if dry_run:
        return result
    if os.name != "nt":
        raise RuntimeError("install_task solo está soportado en Windows (schtasks)")
    p = subprocess.run(cmd, capture_output=True, text=True)
    result.update(created=p.returncode == 0, output=(p.stdout + p.stderr).strip())
    return result


def uninstall_task(project: str | None = None, dry_run: bool = True) -> dict:
    cmd = ["schtasks", "/Delete", "/TN", task_name(project), "/F"]
    if dry_run:
        return {"command": cmd, "dry_run": True, "deleted": False}
    p = subprocess.run(cmd, capture_output=True, text=True)
    return {"command": cmd, "dry_run": False, "deleted": p.returncode == 0,
            "output": (p.stdout + p.stderr).strip()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Watchdog 24/7 de ADES-AI (feature #3)")
    ap.add_argument("--project", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--no-toast", action="store_true")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--install-task", action="store_true",
                    help="muestra la tarea programada (añade --apply para crearla)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.install_task:
        r = install_task(a.project, dry_run=not a.apply)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if (r["dry_run"] or r["created"]) else 1
    wd = Watchdog(a.project, a.repo, notify=not a.no_toast, run_tests=not a.no_tests)
    if a.once:
        r = wd.run_once()
        print(json.dumps({k: v for k, v in r.items() if k != "tests"} |
                         {"tests_passed": (r["tests"] or {}).get("passed")},
                         ensure_ascii=False, indent=2))
        return 1 if r["broken"] else 0
    wd.run_forever(a.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
