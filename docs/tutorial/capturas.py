"""Capturas del panel web de ADES (y de Langfuse) para el tutorial.

Arranca `dashboard.app` en segundo plano, lo fotografía con Playwright (Chromium headless)
y entra en Langfuse local con el usuario inicial de `.env` (LANGFUSE_INIT_USER_*), que solo
existe en esta instalación local (localhost:3000).

Uso:
    python docs/tutorial/capturas.py <carpeta_salida>
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core import config  # noqa: E402,F401  (carga .env)
from playwright.sync_api import sync_playwright  # noqa: E402


def wait(url: str, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=3)
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError(url)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    dash = subprocess.Popen([sys.executable, "-m", "dashboard.app"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait("http://127.0.0.1:8765/api/metrics")
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 1400, "height": 900}, color_scheme="dark")
            page.goto("http://127.0.0.1:8765")
            page.wait_for_timeout(4000)  # el panel se refresca cada 3 s
            page.screenshot(path=str(out / "panel.png"))
            print("[ok] panel.png")

            email, pwd = os.getenv("LANGFUSE_INIT_USER_EMAIL"), os.getenv("LANGFUSE_INIT_USER_PASSWORD")
            if email and pwd:
                page.goto("http://localhost:3000/auth/sign-in")
                page.wait_for_timeout(2500)
                page.fill("input[name=email]", email)
                page.fill("input[name=password]", pwd)
                page.keyboard.press("Enter")
                page.wait_for_timeout(5000)
                project = os.getenv("LANGFUSE_INIT_PROJECT_ID", "ades-ai")
                page.goto(f"http://localhost:3000/project/{project}/observations")
                page.wait_for_timeout(6000)
                page.screenshot(path=str(out / "langfuse.png"))
                print("[ok] langfuse.png")
            b.close()
    finally:
        dash.terminate()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
