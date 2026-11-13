# Linha de base da Etapa 4 no PowerShell: chama o mesmo script do bash (vem com o Git for Windows).
#   .\carga\linha-de-base.ps1                     3 repetições, 30 s por degrau (~35 min)
#   .\carga\linha-de-base.ps1 -Reps 1 -Duracao 10 rodada rápida para conferir o fluxo
param([int]$Reps = 3, [int]$Duracao = 30)
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:REPS = $Reps
$env:DURACAO = $Duracao
bash carga/linha-de-base.sh
exit $LASTEXITCODE
