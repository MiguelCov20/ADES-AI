#!/usr/bin/env python3
"""Escaneo de secretos para ADES-AI (Fase 0, feature #23).

Detecta claves/secretos en el código antes de que se hagan commit.
Nunca imprime el valor del secreto, solo la ubicación y el tipo.

Uso:
    python environment/scan_secrets.py              # escanea archivos staged en git
    python environment/scan_secrets.py <archivo...> # escanea archivos específicos

Código de salida: 0 si no hay secretos, 1 si los hay.
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "Google API key (AIza...)": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "Google OAuth access token (ya29...)": re.compile(r"ya29\.[0-9A-Za-z\-_]+"),
    "OpenCode API key (oc_sk...)": re.compile(r"oc_sk_[0-9A-Za-z_\-]+"),
    "OpenAI-style key (sk-...)": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "GitHub token (ghp_...)": re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    "AWS Access Key (AKIA...)": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Private key PEM": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def get_staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    return [f for f in out.stdout.splitlines() if f]


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return hits
    for line_no, line in enumerate(text.splitlines(), 1):
        for name, rx in PATTERNS.items():
            if rx.search(line):
                hits.append((str(path), line_no, name))
    return hits


def main() -> int:
    files = sys.argv[1:] or get_staged_files()
    if not files:
        print("No hay archivos para escanear.")
        return 0

    all_hits = []
    for f in files:
        all_hits.extend(scan_file(Path(f)))

    if all_hits:
        print("[!] POSIBLES SECRETOS DETECTADOS (no hagas commit):")
        for path, line_no, name in all_hits:
            print(f"  - {path}:{line_no} -> {name}")
        return 1

    print("[OK] Sin secretos detectados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
