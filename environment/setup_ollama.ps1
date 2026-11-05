# ============================================================
#  ADES-AI - setup_ollama.ps1 (Fase 1 - Cerebro local)
#  Instala Ollama (si falta) y prepara los modelos locales.
#
#  Uso:
#    powershell -ExecutionPolicy Bypass -File environment/setup_ollama.ps1
#
#  GPU objetivo: 16 GB VRAM.
#    - AMD Radeon RX 9070 XT  -> Ollama la detecta via ROCm.
#    - NVIDIA (CUDA)          -> Ollama la detecta via CUDA.
#
#  Nota: qwen3.8 se importa desde un GGUF local (no se puede "pull"
#  del registro con versiones antiguas de Ollama). Ajusta $qwenGguf.
# ============================================================

$ErrorActionPreference = "Stop"

# 1. Modelos que se descargan del registro de Ollama
$pullModels = @(
    "nomic-embed-text",   # embeddings (Qdrant / GraphRAG) - 274 MB
    "llama3.2:3b",        # router / compresor rapido      - ~2 GB
    "gpt-oss:20b"         # codificacion principal (MoE)   - 13 GB
)

# 2. Qwen3.8-27B: GGUF local (IQ3-MIX) -> importar con "ollama create"
$qwenGguf = "C:\Users\Miguel Dev\Desktop\IA\llama-b10901-bin-win-vulkan-x64\models\Qwen3.8-27B\Qwen3.8-27B-IQ3-MIX.gguf"
$qwenName = "qwen3.8:27b-iq3"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  ADES-AI - setup Ollama (Fase 1, Cerebro local)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 3. Verificar que Ollama este instalado
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host ""
    Write-Host "[!] Ollama no esta instalado." -ForegroundColor Yellow
    Write-Host "    1) Descargalo de https://ollama.com/download e instala."
    Write-Host "    2) (Alternativa) winget install Ollama.Ollama"
    Write-Host "    3) Vuelve a ejecutar este script."
    exit 1
}
Write-Host "[OK] Ollama detectado: $(ollama --version)" -ForegroundColor Green

# 4. Descargar modelos del registro
foreach ($m in $pullModels) {
    Write-Host ""
    Write-Host ">>> Descargando $m ..." -ForegroundColor Cyan
    ollama pull $m
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] Fallo la descarga de $m" -ForegroundColor Red
    } else {
        Write-Host "[OK] $m listo." -ForegroundColor Green
    }
}

# 5. Importar qwen3.8 desde el GGUF local
Write-Host ""
if (Test-Path $qwenGguf) {
    Write-Host ">>> Importando $qwenName desde GGUF local ..." -ForegroundColor Cyan
    $modelfile = Join-Path $env:TEMP "Modelfile.ades.qwen3.8"
    "FROM `"$qwenGguf`"" | Out-File -FilePath $modelfile -Encoding ascii
    ollama create $qwenName -f $modelfile
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $qwenName listo." -ForegroundColor Green
    } else {
        Write-Host "[!] Fallo la importacion de $qwenName" -ForegroundColor Red
    }
    Remove-Item -Force $modelfile -ErrorAction SilentlyContinue
} else {
    Write-Host "[!] No se encontro $qwenGguf" -ForegroundColor Yellow
    Write-Host "    Coloca el GGUF de Qwen3.8-27B (IQ3) en esa ruta, o" -ForegroundColor Yellow
    Write-Host "    intenta: ollama pull qwen3.8:27b  (requiere Ollama actualizado)" -ForegroundColor Yellow
}

# 6. Resumen final
Write-Host ""
Write-Host "=== Modelos instalados ===" -ForegroundColor Cyan
ollama list

Write-Host ""
Write-Host "=== Estado de carga en GPU (vacio si no hay modelo cargado) ===" -ForegroundColor Cyan
ollama ps

Write-Host ""
Write-Host "Listo. Prueba rapida:  ollama run gpt-oss:20b" -ForegroundColor Green
Write-Host "Benchmark:            python environment/benchmark_local.py" -ForegroundColor Green
