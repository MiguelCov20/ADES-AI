# Crea variantes de los modelos locales con num_ctx fijo (ADES-AI, KPI 5).
# Motivo: el servidor Ollama de esta máquina usa contexto por defecto de 65536 y los
# clientes que pasan por el gateway Bifrost no pueden enviar `num_ctx`, lo que
# dispara la VRAM (llama3.2:3b llegó a 10 GB). Con num_ctx en el Modelfile, todos
# los clientes (Bifrost, OpenCode, Cline) quedan acotados. No duplica pesos en disco.
param([int]$Ctx = 16384)
$models = @("gpt-oss:20b", "llama3.2:3b", "qwen3.8:27b-iq3")
foreach ($m in $models) {
    $name = ($m -split ":")[0]; $tag = ($m -split ":")[1]
    $variant = "${name}:${tag}-ctx$([int]($Ctx/1024))k"
    $mf = New-TemporaryFile
    "FROM $m`nPARAMETER num_ctx $Ctx" | Set-Content -Encoding ascii $mf
    ollama create $variant -f $mf
    Remove-Item $mf
    Write-Host "[OK] $variant"
}
