"""Control por voz del ecosistema (feature #28).

Extiende los comandos de voz del Tool Registry a todo ADES-AI:

  - `parse(texto) -> {"accion": ..., "args": {...}, "fuente": "reglas"|"llm"|"ninguna"}`
    Reglas (regex sobre español normalizado) + fallback a clasificar con
    `llama3.2:3b` vía `core.llm_gateway.chat`.
  - `dispatch(cmd) -> list[str]`: la invocación equivalente del CLI `ades`
    (no ejecuta nada; quien llama decide si la lanza).
  - `listen()`: audio -> texto si está instalado `speech_recognition` o
    `faster_whisper`; si no, lanza `VoiceUnavailable` indicando qué instalar.
  - `voice_loop()`: micrófono si hay, si no lee comandos de texto de stdin.
"""
import json
import os
import re
import sys
import unicodedata

import core.config  # noqa: F401  (carga .env: HF_HOME -> modelos de whisper en F:/IA)

ACCIONES = {
    "integrar": "Integrar una herramienta del registry (args: herramienta, proyecto)",
    "activar": "Activar una herramienta (args: herramienta)",
    "desactivar": "Desactivar una herramienta (args: herramienta)",
    "agregar_herramienta": "Agregar una URL al catálogo (args: url, tipo)",
    "buscar_herramienta": "Buscar herramientas para una tarea (args: consulta)",
    "listar_herramientas": "Listar herramientas (sin args)",
    "crear_proyecto": "Crear un proyecto nuevo (args: descripcion, nombre)",
    "listar_proyectos": "Listar proyectos (sin args)",
    "crear_agente": "Crear un agente con el Reclutador (args: rol)",
    "tokens": "Consultar gasto de tokens (args: proyecto opcional)",
    "estado": "Estado del ecosistema (sin args)",
    "iniciar": "Arrancar el ecosistema (sin args)",
    "vigilar": "Ejecutar el watchdog (args: proyecto opcional)",
    "desconocida": "No se entendió el comando",
}

_URL = re.compile(r"https?://\S+")
# Argumentos válidos por acción (lo que devuelva el LLM fuera de esto se descarta).
ARGS = {
    "integrar": ("herramienta", "proyecto"), "activar": ("herramienta",),
    "desactivar": ("herramienta",), "agregar_herramienta": ("url", "tipo"),
    "buscar_herramienta": ("consulta",), "crear_proyecto": ("descripcion", "nombre"),
    "crear_agente": ("rol",), "tokens": ("proyecto",), "vigilar": ("proyecto",),
}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")


class VoiceUnavailable(RuntimeError):
    """No hay backend de reconocimiento de voz instalado."""


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[¿?¡!.,;:\"]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", normalize(s)).strip("-")
    return s[:40] or "proyecto"


def _clean_name(s: str) -> str:
    s = s.strip()
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^(la|el|los|las|un|una|herramienta|al|a)\s+", "", s)
    return s.strip(" '\"`")


def _rules(text: str) -> dict | None:
    raw = text.strip()
    t = normalize(raw)
    if not t:
        return None
    m = _URL.search(raw)
    if m and re.search(r"\b(agrega|anade|añade|registra|mete)\b", t):
        tipo = "mcp" if " mcp" in f" {t}" else None
        args = {"url": m.group(0).rstrip(".,;")}
        if tipo:
            args["tipo"] = tipo
        return {"accion": "agregar_herramienta", "args": args}
    if re.search(r"\bcuant[oa]s? tokens\b|\bgasto\b|\bcuanto (llevo|he gastado|gasto)\b|"
                 r"\bconsumo de tokens\b", t):
        m2 = re.search(r"\b(?:en|del proyecto|de)\s+([a-z0-9][\w-]*)\s*$", t)
        args = {"proyecto": m2.group(1)} if m2 and m2.group(1) not in ("tokens", "llevo") else {}
        return {"accion": "tokens", "args": args}
    if re.search(r"\b(estado|status)\b.*\b(ecosistema|ades|sistema)\b|^estado$|^status$|"
                 r"\bcomo esta el ecosistema\b", t):
        return {"accion": "estado", "args": {}}
    if re.search(r"\b(arranca|inicia|levanta|enciende)\b.*\becosistema\b", t):
        return {"accion": "iniciar", "args": {}}
    m = re.search(r"\b(?:crea|crear|genera|haz|monta|nuevo)\b (?:me )?(?:un |una )?"
                  r"(?:nuevo )?agente (?:de |para |que )?(.+)", t)
    if m:
        return {"accion": "crear_agente", "args": {"rol": m.group(1).strip()}}
    m = re.search(r"\b(?:crea|crear|genera|haz|monta|empieza|inicia|nuevo)\b (?:me )?"
                  r"(?:un |una )?(?:nuevo )?proyecto(?: de| para| llamado| sobre)? (.+)", t)
    if m:
        desc = m.group(1).strip()
        return {"accion": "crear_proyecto", "args": {"descripcion": desc, "nombre": _slug(desc)}}
    if re.search(r"\b(lista|listar|muestra|ensename|cuales son)\b.*\bproyectos\b", t):
        return {"accion": "listar_proyectos", "args": {}}
    if re.search(r"\b(lista|listar|muestra|ensename)\b.*\bherramientas\b", t):
        return {"accion": "listar_herramientas", "args": {}}
    m = re.search(r"\b(?:que herramientas hay para|busca(?:me)? (?:una |herramientas? )?"
                  r"(?:herramientas? )?para|herramientas para)\b (.+)", t)
    if m:
        return {"accion": "buscar_herramienta", "args": {"consulta": m.group(1).strip()}}
    m = re.search(r"\b(desactiva|deshabilita|apaga)\b (.+)", t)
    if m:
        return {"accion": "desactivar", "args": {"herramienta": _clean_name(m.group(2))}}
    m = re.search(r"\b(activa|habilita|enciende)\b (.+)", t)
    if m:
        return {"accion": "activar", "args": {"herramienta": _clean_name(m.group(2))}}
    m = re.search(r"\b(?:integra|integrar|instala|conecta)\b (.+?)(?: (?:en|a|al|con) (.+))?$", t)
    if m:
        args = {"herramienta": _clean_name(m.group(1))}
        if m.group(2):
            args["proyecto"] = _slug(m.group(2))
        return {"accion": "integrar", "args": args}
    m = re.search(r"\b(?:vigila|watchdog|revisa si se rompio)\b(?: (?:el )?(?:proyecto )?(.+))?", t)
    if m:
        return {"accion": "vigilar", "args": {"proyecto": _slug(m.group(1))} if m.group(1) else {}}
    return None


_SYSTEM = (
    "Eres el clasificador de comandos de voz de ADES-AI. Convierte la orden del usuario "
    "(en español) en JSON con la forma {\"accion\": \"...\", \"args\": {...}}. Acciones "
    "permitidas:\n" + "\n".join(f"- {k}: {v}" for k, v in ACCIONES.items()) +
    "\nResponde SOLO con el JSON, sin texto adicional. Si no encaja, usa \"desconocida\"."
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def classify_llm(text: str, model: str = "llama3.2:3b") -> dict:
    """Clasifica con el LLM local (vía la pasarela). Valida la acción devuelta."""
    from core.llm_gateway import chat
    res = chat("voice", _SYSTEM, text, provider="ollama", model=model, use_cache=False,
               temperature=0.0, json_mode=True)
    data = _extract_json(res.text) or {}
    accion = str(data.get("accion", "desconocida")).strip().lower()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    if accion not in ACCIONES:
        accion, args = "desconocida", {}
    clean = {}
    for k in ARGS.get(accion, ()):
        v = str(args.get(k) or "").strip()
        if not v:
            continue
        if k in ("proyecto", "herramienta", "nombre") and not _ID.match(v.lower()):
            continue  # el LLM a veces mete frases enteras: no es un identificador
        if k == "url" and not _URL.match(v):
            continue
        clean[k] = v.lower() if k in ("proyecto", "herramienta", "nombre") else v
    return {"accion": accion, "args": clean}


def parse(texto: str, use_llm: bool = True) -> dict:
    """Texto en lenguaje natural -> {"accion", "args", "fuente", "texto"}."""
    r = _rules(texto)
    if r is not None:
        return {**r, "fuente": "reglas", "texto": texto}
    if use_llm and texto.strip():
        try:
            r = classify_llm(texto)
            return {**r, "fuente": "llm", "texto": texto}
        except Exception as e:  # noqa: BLE001  Ollama caído
            return {"accion": "desconocida", "args": {}, "fuente": "ninguna", "texto": texto,
                    "error": f"{type(e).__name__}: {e}"[:200]}
    return {"accion": "desconocida", "args": {}, "fuente": "ninguna", "texto": texto}


def dispatch(cmd: dict) -> list[str]:
    """Invocación del CLI `ades` equivalente (lista de args). No ejecuta nada.

    Lanza ValueError si la acción no es conocida o le faltan argumentos.
    """
    a, args = cmd.get("accion"), cmd.get("args", {}) or {}

    def need(k):
        v = str(args.get(k, "")).strip()
        if not v:
            raise ValueError(f"La acción '{a}' necesita el argumento '{k}'")
        return v

    # Mapeo al CLI real `ades_cli.py`: comandos propios (integrate, project, tokens,
    # status, start) y passthrough (tools -> registry.cli, agent -> agents.reclutador,
    # watchdog -> automation.watchdog).
    if a == "integrar":
        # registry.cli no admite proyecto destino: las herramientas se integran en ADES-AI.
        return ["ades", "integrate", need("herramienta")]
    if a == "activar":
        return ["ades", "tools", "activate", need("herramienta")]
    if a == "desactivar":
        return ["ades", "tools", "deactivate", need("herramienta")]
    if a == "agregar_herramienta":
        out = ["ades", "tools", "add", need("url")]
        if args.get("tipo"):
            out += ["--tipo", args["tipo"]]
        return out
    if a == "buscar_herramienta":
        return ["ades", "tools", "search", need("consulta")]
    if a == "listar_herramientas":
        return ["ades", "tools", "list"]
    if a == "crear_proyecto":
        return ["ades", "project", "create", args.get("nombre") or _slug(need("descripcion"))]
    if a == "listar_proyectos":
        return ["ades", "project", "list"]
    if a == "crear_agente":
        rol = need("rol")
        return ["ades", "agent", "create", f"agente-{_slug(rol)}", rol]
    if a == "tokens":
        return ["ades", "tokens"] + (["--project", args["proyecto"]] if args.get("proyecto") else [])
    if a == "estado":
        return ["ades", "status"]
    if a == "iniciar":
        return ["ades", "start"]
    if a == "vigilar":
        return ["ades", "watchdog", "--once"] + (
            ["--project", args["proyecto"]] if args.get("proyecto") else [])
    raise ValueError(f"Acción no soportada: {a!r}")


# --- Entrada de audio (micrófono) ------------------------------------------------
# Backend principal: sounddevice (captura) + faster-whisper (transcripción LOCAL en CPU,
# int8, $0 y sin red tras la primera descarga del modelo). Probado con el micrófono
# integrado de la webcam ("GENERAL WEBCAM"). Alternativa: speech_recognition + pyaudio.

SAMPLE_RATE = 16000
WHISPER_MODEL = os.getenv("ADES_WHISPER_MODEL", "small")
_whisper = None


def backend() -> str | None:
    """Backend disponible: 'whisper_mic' (sounddevice+faster-whisper), 'speech_recognition',
    'faster_whisper' (solo archivos) o None."""
    import importlib.util
    has = {n: importlib.util.find_spec(n) is not None
           for n in ("sounddevice", "faster_whisper", "speech_recognition")}
    if has["sounddevice"] and has["faster_whisper"]:
        return "whisper_mic"
    if has["speech_recognition"]:
        return "speech_recognition"
    if has["faster_whisper"]:
        return "faster_whisper"
    return None


INSTALL_HINT = ("No hay reconocimiento de voz instalado. Instala:\n"
                "  pip install faster-whisper sounddevice   (micrófono, transcripción local)\n"
                "Mientras tanto usa voice_loop() escribiendo los comandos por teclado.")


def find_microphone(prefer: str | None = None) -> int | None:
    """Índice del micrófono. Orden: ADES_MIC_DEVICE (índice o nombre) > webcam > por defecto."""
    import sounddevice as sd
    prefer = prefer or os.getenv("ADES_MIC_DEVICE", "")
    devices = list(enumerate(sd.query_devices()))
    inputs = [(i, d) for i, d in devices if d["max_input_channels"] > 0]
    if prefer.isdigit():
        return int(prefer)
    if prefer:
        for i, d in inputs:
            if prefer.lower() in d["name"].lower():
                return i
    for i, d in inputs:  # micrófono de la cámara conectada
        if "webcam" in d["name"].lower() or "camera" in d["name"].lower():
            return i
    default = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else None
    return default if default is not None and default >= 0 else (inputs[0][0] if inputs else None)


def _rms(block) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


def segment_speech(frames, noise_rms: float, block: int, silence_s: float = 0.9,
                   factor: float = 3.0, min_threshold: float = 0.012):
    """Detección de voz por energía (lógica pura, testeable).

    `frames`: iterable de bloques float32. Devuelve el audio desde que la energía supera
    el umbral (ruido × factor) hasta `silence_s` de silencio, o None si nunca hubo voz.
    """
    import numpy as np
    thr = max(noise_rms * factor, min_threshold)
    silence_blocks = int(silence_s * SAMPLE_RATE / block)
    voiced, quiet, started = [], 0, False
    pre = []  # medio segundo previo para no cortar la primera sílaba
    for f in frames:
        loud = _rms(f) > thr
        if not started:
            pre = (pre + [f])[-max(1, int(0.5 * SAMPLE_RATE / block)):]
            if loud:
                started, voiced = True, list(pre)
            continue
        voiced.append(f)
        quiet = 0 if loud else quiet + 1
        if quiet >= silence_blocks:
            break
    return np.concatenate(voiced) if started else None


def record_command(device: int | None = None, max_seconds: float = 10.0,
                   wait_seconds: float = 8.0, silence_s: float = 0.9) -> "object | None":
    """Graba una orden del micrófono: calibra el ruido 0.5 s, espera a que hables y corta
    tras `silence_s` de silencio. Devuelve audio float32 a 16 kHz o None si no hubo voz."""
    import queue

    import numpy as np
    import sounddevice as sd
    device = find_microphone() if device is None else device
    if device is None:
        raise VoiceUnavailable("No se encontró ningún micrófono.")
    block = int(0.05 * SAMPLE_RATE)
    q: "queue.Queue" = queue.Queue()

    def cb(indata, frames, t, status):  # noqa: ARG001
        q.put(indata[:, 0].copy())

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                blocksize=block, device=device, callback=cb)
    except Exception as e:  # noqa: BLE001
        raise VoiceUnavailable(f"No se pudo abrir el micrófono {device}: {e}") from e
    with stream:
        noise = [q.get(timeout=5) for _ in range(int(0.5 * SAMPLE_RATE / block))]
        noise_rms = _rms(np.concatenate(noise))
        limit = int((wait_seconds + max_seconds) * SAMPLE_RATE / block)

        def frames():
            for _ in range(limit):
                yield q.get(timeout=5)
        return segment_speech(frames(), noise_rms, block, silence_s=silence_s)


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio, language: str = "es") -> str:
    """Transcribe audio (ruta de archivo o array float32 a 16 kHz) con faster-whisper."""
    segments, _ = _get_whisper().transcribe(audio, language=language, vad_filter=True,
                                            beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


def listen(audio_file: str | None = None, language: str = "es-ES", timeout: float = 8.0,
           device: int | None = None) -> str:
    """Captura (micrófono) o transcribe (`audio_file`) una orden de voz y devuelve el texto."""
    b = backend()
    if b is None:
        raise VoiceUnavailable(INSTALL_HINT)
    lang = language.split("-")[0]
    if b in ("whisper_mic", "faster_whisper"):
        if audio_file:
            return transcribe(audio_file, lang)
        if b == "faster_whisper":
            raise VoiceUnavailable("Para micrófono instala también: pip install sounddevice")
        audio = record_command(device=device, wait_seconds=timeout)
        return transcribe(audio, lang) if audio is not None else ""
    import speech_recognition as sr
    r = sr.Recognizer()
    if audio_file:
        with sr.AudioFile(audio_file) as src:
            audio = r.record(src)
    else:
        with sr.Microphone() as src:
            r.adjust_for_ambient_noise(src, duration=0.5)
            audio = r.listen(src, timeout=timeout)
    return r.recognize_google(audio, language=language)


def handle(texto: str, use_llm: bool = True) -> dict:
    cmd = parse(texto, use_llm=use_llm)
    try:
        cmd["invocacion"] = dispatch(cmd)
    except ValueError as e:
        cmd["invocacion"] = None
        cmd["error"] = str(e)
    return cmd


def voice_loop(input_fn=None, output=print, use_mic: bool | None = None,
               use_llm: bool = True, max_commands: int | None = None) -> list[dict]:
    """Bucle de órdenes. Usa el micrófono si hay backend; si no, lee texto de stdin.

    Termina con "salir"/"adios", EOF o tras `max_commands`. Devuelve los comandos.
    """
    if use_mic is None:
        use_mic = input_fn is None and backend() in ("whisper_mic", "speech_recognition")
    if input_fn is None:
        if use_mic:
            input_fn = listen
        else:
            def input_fn():
                line = sys.stdin.readline()
                if not line:
                    raise EOFError
                return line
            output("ADES-AI voz (modo texto). Escribe una orden o 'salir'.")
    done = []
    while max_commands is None or len(done) < max_commands:
        try:
            texto = input_fn()
        except (EOFError, KeyboardInterrupt):
            break
        except VoiceUnavailable as e:
            output(str(e))
            break
        if normalize(texto) in ("salir", "adios", "exit", "quit"):
            break
        if not texto.strip():
            continue
        cmd = handle(texto, use_llm=use_llm)
        done.append(cmd)
        if cmd["invocacion"]:
            output(f"[{cmd['accion']}] -> {' '.join(cmd['invocacion'])}")
        else:
            output(f"[{cmd['accion']}] {cmd.get('error', 'no entendí la orden')}")
    return done


def main(argv: list[str] | None = None) -> int:
    """`ades voice [texto...]`: traduce una orden; sin texto abre el bucle interactivo."""
    argv = list(sys.argv[1:] if argv is None else argv)
    no_llm = "--no-llm" in argv
    if "--mic-test" in argv:  # graba una orden y muestra la transcripción
        print(f"Micrófono: {find_microphone()} · habla ahora...")
        texto = listen()
        print(json.dumps({"texto": texto, **(handle(texto, use_llm=not no_llm) if texto else {})},
                         ensure_ascii=False))
        return 0
    if "--texto" in argv:
        argv.remove("--texto")
        voice_loop(use_llm=not no_llm, use_mic=False)
        return 0
    argv = [a for a in argv if a != "--no-llm"]
    if argv:
        print(json.dumps(handle(" ".join(argv), use_llm=not no_llm), ensure_ascii=False))
        return 0
    voice_loop(use_llm=not no_llm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
