# Instala llama.cpp (llama-server) para Windows + AMD — alternativa a vLLM (KPI 5).
# Descarga la release OFICIAL de ggml-org (ROCm/HIP y Vulkan) en .ades\runtime\llamacpp\<build>.
# Los pesos se reutilizan de Ollama (sin descargas extra). En Linux usa vLLM: environment\vllm\.
param([string]$Build = "b12292")
$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "..\.ades\runtime\llamacpp\$Build"
New-Item -ItemType Directory -Force $dest | Out-Null
foreach ($v in @("rocm-10.0", "vulkan")) {
    $name = "llama-$Build-bin-win-$v-x64.zip"
    $url = "https://github.com/ggml-org/llama.cpp/releases/download/$Build/$name"
    $zip = Join-Path $dest $name
    Write-Host "Descargando $url"
    Invoke-WebRequest -Uri $url -OutFile $zip
    $folder = Join-Path $dest ($v -split "-")[0]
    Expand-Archive -Force $zip $folder
    Remove-Item $zip
    Write-Host "[OK] $folder\llama-server.exe"
}
# El build ROCm de Windows no incluye hipBLAS/rocBLAS (ggml-hip.dll importa hipblas.dll).
# Opción A (sin instalar nada): copiar las del runtime ROCm 7.1 que ya trae Ollama.
# Opción B: instalar el AMD HIP SDK para Windows (define HIP_PATH; se usa automáticamente).
$ollamaRocm = Join-Path $env:LOCALAPPDATA "Programs\Ollama\lib\ollama\rocm_v7_1"
$libs = Join-Path $dest "rocm-libs"
if (Test-Path $ollamaRocm) {
    New-Item -ItemType Directory -Force $libs | Out-Null
    Copy-Item (Join-Path $ollamaRocm "libhipblas.dll") (Join-Path $libs "hipblas.dll") -Force
    Copy-Item (Join-Path $ollamaRocm "libhipblaslt.dll"), (Join-Path $ollamaRocm "rocblas.dll") $libs -Force
    Copy-Item (Join-Path $ollamaRocm "rocblas") $libs -Recurse -Force
    Write-Host "[OK] hipBLAS/rocBLAS copiadas de Ollama a $libs"
} elseif (-not $env:HIP_PATH) {
    Write-Warning "Sin hipBLAS: instala el AMD HIP SDK o usa ADES_LLAMACPP_BACKEND=vulkan"
}
Write-Host "Listo. Activa con ADES_LOCAL_BACKEND=llamacpp en .env (backend: ADES_LLAMACPP_BACKEND=rocm|vulkan)."
