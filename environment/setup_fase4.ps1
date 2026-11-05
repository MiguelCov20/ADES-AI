# ============================================================
#  ADES-AI - setup_fase4.ps1 (Fase 4 - Skills y subagentes)
#  Clona los tools externos en .opencode/vendor/ (gitignored):
#    - Obra Superpowers (plugin de skills)
#    - oh-my-opencode / OmO (skills compatibles con OpenCode)
#
#  Uso:
#    powershell -ExecutionPolicy Bypass -File environment/setup_fase4.ps1
#
#  Idempotente: salta los repos que ya existen. Ejecutalo de nuevo
#  si .opencode/vendor/ se borra (p. ej. al cambiar de rama o limpiar).
# ============================================================

$ErrorActionPreference = "Stop"

$vendor      = ".opencode/vendor"
$superpowers = "https://github.com/obra/superpowers.git"
$omo         = "https://github.com/code-yeongyu/oh-my-openagent.git"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  ADES-AI - setup Fase 4 (tools externos)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[!] No se encontro git. Instala git e intenta de nuevo." -ForegroundColor Red
    exit 1
}

if (Test-Path "$vendor\superpowers") {
    Write-Host "[OK] superpowers ya existe: $vendor\superpowers" -ForegroundColor Green
} else {
    Write-Host ">>> Clonando superpowers ..." -ForegroundColor Cyan
    git clone --depth 1 $superpowers "$vendor\superpowers"
    Write-Host "[OK] superpowers clonado." -ForegroundColor Green
}

if (Test-Path "$vendor\oh-my-opencode") {
    Write-Host "[OK] oh-my-opencode ya existe: $vendor\oh-my-opencode" -ForegroundColor Green
} else {
    Write-Host ">>> Clonando oh-my-opencode ..." -ForegroundColor Cyan
    git clone --depth 1 $omo "$vendor\oh-my-opencode"
    Write-Host "[OK] oh-my-opencode clonado." -ForegroundColor Green
}

Write-Host ""
Write-Host "Listo. opencode.json ya referencia estas rutas:" -ForegroundColor Green
Write-Host "  - plugins: .opencode/vendor/superpowers" -ForegroundColor Green
Write-Host "  - skills:  .opencode/vendor/oh-my-opencode/.opencode/skills" -ForegroundColor Green
