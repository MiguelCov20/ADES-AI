"""Genera el video tutorial de ADES-AI v1.2 a partir de salidas REALES de los comandos.

Entrada: una carpeta con las salidas capturadas (`<nombre>.txt`) y capturas (`*.png`).
Salida:  docs/tutorial/tutorial_ades_v1.2.mp4 (1280x720, narración en español).

Cada escena = imágenes (diapositiva o terminal animada) + narración generada con la voz
de Windows (System.Speech, voz es-*). Las escenas se montan con ffmpeg (imageio-ffmpeg).

Uso:
    python docs/tutorial/generar_video.py <carpeta_salidas>
"""
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 30
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONTS = Path("C:/Windows/Fonts")
MONO = str(FONTS / "CascadiaMono.ttf")
SANS = str(FONTS / "segoeui.ttf")
SANS_B = str(FONTS / "segoeuib.ttf")
BG, PANEL, INK, QUIET = (18, 20, 26), (28, 31, 40), (232, 234, 240), (150, 156, 170)
ACCENT, GOOD, WARN = (79, 156, 249), (63, 185, 80), (230, 170, 60)

OUT_DIR = Path(__file__).resolve().parent
WORK = OUT_DIR / "_build"


def font(path, size):
    return ImageFont.truetype(path, size)


def clean(text: str) -> str:
    text = text.replace("\ufeff", "")
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def read_out(folder: Path, name: str) -> str:
    p = folder / f"{name}.txt"
    return clean(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else f"(sin salida: {name})"


# --------------------------------------------------------------------------- dibujo
def base(title: str | None = None, step: str | None = None) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if title:
        d.text((56, 34), title, font=font(SANS_B, 34), fill=INK)
    if step:
        d.text((W - 56, 44), step, font=font(SANS, 20), fill=QUIET, anchor="ra")
    d.text((56, H - 34), "ADES-AI v1.2 · tutorial", font=font(SANS, 16), fill=QUIET)
    return img


def slide(title, bullets, step=None, note=None) -> Image.Image:
    img = base(title, step)
    d = ImageDraw.Draw(img)
    y = 130
    for b in bullets:
        sub = b.startswith("  ")
        f = font(SANS, 24 if sub else 28)
        x = 104 if sub else 72
        d.text((x - 26, y), "–" if sub else "•", font=f, fill=ACCENT)
        for line in wrap(b.strip(), f, W - x - 80):
            d.text((x, y), line, font=f, fill=INK if not sub else QUIET)
            y += 40 if not sub else 34
        y += 10
    if note:
        d.text((72, H - 90), note, font=font(SANS, 20), fill=QUIET)
    return img


def wrap(text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def terminal(title, step, cmd, out_lines, typed_chars, shown_lines, caption=None) -> Image.Image:
    img = base(title, step)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 48, 100, W - 48, H - 64
    d.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=PANEL)
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse((x0 + 18 + i * 22, y0 + 14, x0 + 32 + i * 22, y0 + 28), fill=c)
    d.text((x0 + 90, y0 + 11), "PowerShell", font=font(SANS, 16), fill=QUIET)
    f = font(MONO, 17)
    lh = 23
    max_lines = (y1 - y0 - 60) // lh
    y = y0 + 44
    typed = cmd[:typed_chars]
    cursor = "█" if typed_chars < len(cmd) else ""
    for line in wrap_mono(f"PS> {typed}{cursor}", f, x1 - x0 - 40):
        d.text((x0 + 20, y), line, font=f, fill=GOOD if line.startswith("PS>") else INK)
        y += lh
    rendered = []
    for ln in out_lines[:shown_lines]:
        rendered += wrap_mono(ln, f, x1 - x0 - 40) or [""]
    budget = max_lines - (y - y0 - 44) // lh
    if len(rendered) > budget:
        rendered = rendered[-budget:]
    for ln in rendered:
        col = INK
        if ln.startswith("PS>"):
            col = GOOD
        elif re.search(r"\bOK\b|PASS|passed|true|\[ok\]|estado=ok", ln):
            col = GOOD
        elif re.search(r"FAIL|failed|ERROR|false", ln):
            col = WARN
        d.text((x0 + 20, y), ln, font=f, fill=col)
        y += lh
    if caption:
        d.text((W // 2, H - 44), caption, font=font(SANS, 18), fill=ACCENT, anchor="mm")
    return img


def wrap_mono(text, f, width):
    if not text:
        return [""]
    out, cur = [], ""
    for ch in text:
        if f.getlength(cur + ch) > width:
            out.append(cur)
            cur = "   " + ch
        else:
            cur += ch
    out.append(cur)
    return out


def image_slide(title, step, png: Path, caption) -> Image.Image:
    img = base(title, step)
    if png.exists():
        shot = Image.open(png).convert("RGB")
        shot.thumbnail((W - 120, H - 190))
        x = (W - shot.width) // 2
        img.paste(shot, (x, 104))
        ImageDraw.Draw(img).rectangle((x - 1, 103, x + shot.width, 104 + shot.height), outline=QUIET)
    d = ImageDraw.Draw(img)
    d.text((W // 2, H - 58), caption, font=font(SANS, 20), fill=INK, anchor="mm")
    return img


def flow_slide(title, step) -> Image.Image:
    """Diagrama de la fábrica: PM -> Arquitecto -> Developer <-> QA -> Reviewer -> DevOps."""
    img = base(title, step)
    d = ImageDraw.Draw(img)
    boxes = [("PM", "Gemini"), ("Arquitecto", "Gemini"), ("Developer", "gpt-oss local"),
             ("QA + sandbox", "gpt-oss local"), ("Reviewer", "DeepSeek"), ("DevOps", "DeepSeek")]
    bw, bh, gap, y = 170, 92, 26, 250
    x = (W - (len(boxes) * bw + (len(boxes) - 1) * gap)) // 2
    pos = []
    for i, (name, model) in enumerate(boxes):
        bx = x + i * (bw + gap)
        main = name.startswith(("Developer", "QA"))
        d.rounded_rectangle((bx, y, bx + bw, y + bh), radius=12,
                            fill=(30, 50, 80) if main else PANEL, outline=ACCENT if main else QUIET, width=2)
        d.text((bx + bw // 2, y + 34), name, font=font(SANS_B, 21), fill=INK, anchor="mm")
        d.text((bx + bw // 2, y + 64), model, font=font(SANS, 16), fill=QUIET, anchor="mm")
        pos.append(bx)
        if i:
            ax = bx - gap
            d.line((ax + 3, y + bh // 2, bx - 4, y + bh // 2), fill=QUIET, width=2)
            d.polygon([(bx - 4, y + bh // 2), (bx - 12, y + bh // 2 - 6), (bx - 12, y + bh // 2 + 6)], fill=QUIET)
    # bucle Dev <-> QA
    a, b = pos[2] + bw // 2, pos[3] + bw // 2
    d.arc((a, y + bh - 10, b, y + bh + 70), 0, 180, fill=WARN, width=3)
    d.text(((a + b) // 2, y + bh + 84), "si los tests fallan, el Developer corrige solo", font=font(SANS, 18),
           fill=WARN, anchor="mm")
    d.text((W // 2, 170), "Tú escribes un requerimiento; los agentes hacen el resto", font=font(SANS, 24),
           fill=INK, anchor="mm")
    d.text((W // 2, 520), "Memoria: Neo4j (mapa del código) · Qdrant + Redis (recuerdos y caché) · "
           "Langfuse (tokens y coste)", font=font(SANS, 19), fill=QUIET, anchor="mm")
    return img


def kpi_slide(rows, step) -> Image.Image:
    img = base("Los 5 KPIs, medidos hoy", step)
    d = ImageDraw.Draw(img)
    y = 120
    for name, value, ok in rows:
        d.rounded_rectangle((72, y, W - 72, y + 84), radius=12, fill=PANEL)
        d.text((100, y + 18), name, font=font(SANS_B, 23), fill=INK)
        d.text((100, y + 50), value, font=font(SANS, 19), fill=QUIET)
        label = ok if isinstance(ok, str) else ("CUMPLIDO" if ok else "NO CUMPLIDO")
        d.text((W - 100, y + 42), label, font=font(SANS_B, 22),
               fill=GOOD if ok is True else WARN, anchor="rm")
        y += 100
    return img


# --------------------------------------------------------------------------- audio y montaje
def tts(texts: list[str]) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    jobs = [{"text": t, "path": str(WORK / f"voz_{i:02d}.wav")} for i, t in enumerate(texts)]
    jf = WORK / "voz.json"
    jf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'es*'}|select -First 1;"
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)}; $s.Rate=0;"
          f"$j=Get-Content -Raw -Encoding UTF8 '{jf}'|ConvertFrom-Json;"
          "foreach($x in $j){$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050,"
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
          "$s.SetOutputToWaveFile($x.path,$f);$s.Speak($x.text)}; $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return [Path(j["path"]) for j in jobs]


def wav_seconds(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def render_scene(idx: int, frames: list[tuple[Image.Image, float]], voice: Path) -> Path:
    d = WORK / f"escena_{idx:02d}"
    d.mkdir(parents=True, exist_ok=True)
    total = sum(t for _, t in frames)
    need = wav_seconds(voice) + 0.8
    if total < need:  # estirar el último cuadro hasta cubrir la narración
        img, t = frames[-1]
        frames[-1] = (img, t + need - total)
    lst = []
    for i, (img, t) in enumerate(frames):
        p = d / f"f{i:04d}.png"
        img.save(p)
        lst.append(f"file '{p.as_posix()}'\nduration {t:.3f}")
    lst.append(f"file '{(d / f'f{len(frames) - 1:04d}.png').as_posix()}'")
    (d / "lista.txt").write_text("\n".join(lst), encoding="utf-8")
    out = d / "escena.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(d / "lista.txt"),
                    "-i", str(voice), "-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]",
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", str(out)], check=True)
    return out


def typing_frames(title, step, cmd, out_lines, caption=None, chunk=None):
    frames = []
    for n in range(0, len(cmd) + 1, 2):
        frames.append((terminal(title, step, cmd, out_lines, n, 0, caption), 0.045))
    frames.append((terminal(title, step, cmd, out_lines, len(cmd), 0, caption), 0.5))
    chunk = chunk or max(1, len(out_lines) // 12)
    for n in range(chunk, len(out_lines) + chunk, chunk):
        frames.append((terminal(title, step, cmd, out_lines, len(cmd), min(n, len(out_lines)), caption), 0.18))
    return frames


def lines_of(text: str, drop_prompt=True, limit=None):
    ls = [l.rstrip() for l in text.splitlines() if l.strip() or True]
    if drop_prompt and ls and ls[0].startswith("PS>"):
        ls = ls[1:]
    ls = [l for l in ls if not re.search(r"warn|Traceback|File \"|symlink|Developer Mode", l, re.I)]
    return ls[:limit] if limit else ls


def main(folder: Path) -> Path:
    scenes = json.loads((folder / "guion.json").read_text(encoding="utf-8"))
    built = []
    voices = tts([s["voz"] for s in scenes])
    for i, (s, v) in enumerate(zip(scenes, voices)):
        k, step = s["tipo"], f"{i + 1}/{len(scenes)}"
        if k == "slide":
            frames = [(slide(s["titulo"], s["puntos"], step, s.get("nota")), 1.0)]
        elif k == "flujo":
            frames = [(flow_slide(s["titulo"], step), 1.0)]
        elif k == "terminal":
            out = lines_of(read_out(folder, s["salida"]), limit=s.get("max_lineas"))
            frames = typing_frames(s["titulo"], step, s["comando"], out, s.get("leyenda"))
        elif k == "imagen":
            frames = [(image_slide(s["titulo"], step, folder / s["png"], s["leyenda"]), 1.0)]
        elif k == "kpis":
            frames = [(kpi_slide([tuple(r) for r in s["filas"]], step), 1.0)]
        else:
            raise ValueError(k)
        built.append(render_scene(i, frames, v))
        print(f"[ok] escena {i + 1}/{len(scenes)}: {s['titulo']}")
    lst = WORK / "escenas.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in built), encoding="utf-8")
    final = OUT_DIR / "tutorial_ades_v1.2.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    return final


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
