param(
  [Alias("Host")]
  [ValidateSet("codex", "cursor", "shared")]
  [string]$InstallHost = "shared",
  [string]$CodexHome = "",
  [switch]$DryRun,
  [switch]$Rollback,
  [switch]$Force,
  [switch]$Help,
  [switch]$Json
)

$ErrorActionPreference = "Stop"

if ($Help) {
  Write-Output @"
Usage: install_global.ps1 [-InstallHost shared|codex|cursor] [-DryRun] [-Force] [-Rollback] [-Json]

Default target: ~/.agents/skills/reverse-engineer-ai-video-tutorial
-Force is required to replace an existing install.
"@
  exit 0
}

$skillRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$python = Get-Command py -ErrorAction SilentlyContinue
$pythonArgs = @()
if ($python) {
  $pythonArgs = @("-3")
} else {
  $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
  throw "Python 3.11+ required. Install Python, then rerun installer."
}

if ($CodexHome) {
  $skillsRoot = Join-Path $CodexHome "skills"
}
$installer = Join-Path $skillRoot "scripts\install_skill.py"
if ($CodexHome) {
  $arguments = @($installer, "--source", $skillRoot, "--skills-root", $skillsRoot)
} else {
  $arguments = @($installer, "--source", $skillRoot, "--host", $InstallHost)
}
if ($DryRun) { $arguments += "--dry-run" }
if ($Rollback) { $arguments += "--rollback" }
if ($Force) { $arguments += "--force" }
if ($Json) { $arguments += "--json" }

& $python.Source @($pythonArgs + $arguments)
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
