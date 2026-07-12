# Run a Terminal-Bench 2.0 slice with nano-harness through the ASU gateway.
# Usage (from repo root, in a normal PowerShell window):
#   .\scripts\tb2_slice.ps1                # 10 tasks, haiku
#   .\scripts\tb2_slice.ps1 -NTasks 1      # single-task smoke
#   .\scripts\tb2_slice.ps1 -Model openai/gpt5_4_thinking -NTasks 10
#   .\scripts\tb2_slice.ps1 -Resume nano-tb2-haiku-10   # continue an interrupted job
param(
    [string]$Model = "aws/claude4_5_haiku",
    [int]$NTasks = 10,
    [string]$JobName = "",
    [string]$Resume = ""
)

Set-Location $PSScriptRoot\..

# Load .env (ASU token/project id) into this process only.
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim())
    }
}
$env:OPENAI_API_KEY  = $env:ASU_AIML_TOKEN
$env:OPENAI_BASE_URL = "https://api-main.aiml.asu.edu/v1"

if ($Resume) {
    & .venv\Scripts\harbor.exe job resume results\terminal-bench\$Resume
    exit $LASTEXITCODE
}

if (-not $JobName) {
    $safe = $Model -replace '[/.]', '-'
    $JobName = "nano-tb2-$safe-$NTasks"
}

& .venv\Scripts\harbor.exe run `
    -d terminal-bench@2.0 `
    -a eval.tb_agent:NanoAgent `
    -m $Model `
    -l $NTasks `
    -o results\terminal-bench `
    --job-name $JobName `
    -n 2 `
    -y

Write-Host "`nDone. Results: results\terminal-bench\$JobName\result.json"
