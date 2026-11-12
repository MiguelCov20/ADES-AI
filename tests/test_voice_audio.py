"""Entrada de audio de la feature #28 (micrófono de la webcam + faster-whisper)."""
import os
import subprocess
import sys
import wave

import numpy as np
import pytest

from automation import voice


def test_segment_speech_recorta_la_voz():
    rng = np.random.default_rng(0)
    blk = 800
    sil = rng.normal(0, 0.003, 16000).astype("float32")
    tono = (0.2 * np.sin(np.linspace(0, 2 * np.pi * 440 * 1.5, 24000))).astype("float32")
    full = np.concatenate([sil, tono, sil, sil])
    seg = voice.segment_speech([full[i:i + blk] for i in range(0, len(full), blk)], 0.003, blk)
    assert seg is not None and 1.4 <= len(seg) / 16000 <= 3.0


def test_segment_speech_silencio_devuelve_none():
    sil = np.random.default_rng(1).normal(0, 0.003, 32000).astype("float32")
    assert voice.segment_speech([sil[i:i + 800] for i in range(0, len(sil), 800)], 0.003, 800) is None


def test_find_microphone_prefiere_webcam(monkeypatch):
    import sounddevice as sd
    devs = [{"name": "Asignador", "max_input_channels": 2},
            {"name": "Altavoces", "max_input_channels": 0},
            {"name": "Micrófono (GENERAL WEBCAM)", "max_input_channels": 1}]
    monkeypatch.setattr(sd, "query_devices", lambda: devs)
    monkeypatch.delenv("ADES_MIC_DEVICE", raising=False)
    assert voice.find_microphone() == 2
    monkeypatch.setenv("ADES_MIC_DEVICE", "Asignador")
    assert voice.find_microphone() == 0


def test_backend_microfono():
    assert voice.backend() == "whisper_mic"


def _tts_wav(path: str, text: str) -> bool:
    if sys.platform != "win32":
        return False
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'es*'}|select -First 1;"
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
          "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
          f"$s.SetOutputToWaveFile('{path}',$f);$s.Speak('{text}');$s.Dispose()")
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps]).returncode == 0


@pytest.mark.live
def test_transcribe_orden_real_y_despacho(tmp_path):
    wav = str(tmp_path / "orden.wav")
    if not _tts_wav(wav, "Crea un proyecto de tienda online"):
        pytest.skip("sin TTS de Windows")
    txt = voice.transcribe(wav)
    assert "tienda" in txt.lower()
    cmd = voice.handle(txt, use_llm=False)
    assert cmd["invocacion"][:3] == ["ades", "project", "create"]
    # El mismo audio pasado como array (lo que entrega el micrófono)
    w = wave.open(wav)
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype("float32") / 32768
    assert "tienda" in voice.transcribe(audio).lower()


@pytest.mark.live
def test_microfono_real_abre_y_detecta_silencio():
    if voice.find_microphone() is None:
        pytest.skip("sin micrófono")
    r = voice.record_command(wait_seconds=1.5, max_seconds=1.5)
    assert r is None or len(r) > 0  # en silencio -> None; si hay ruido fuerte, audio
