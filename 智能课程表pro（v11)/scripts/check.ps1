param(
  [string]$PythonExe = "",
  [string]$NpmCmd = "npm"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) {
  $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    $PythonExe = $venvPython
  } else {
    $PythonExe = "python"
  }
}

Push-Location $projectRoot
try {
  & $PythonExe -m ruff check server tests migrations
  if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }

  & $PythonExe -m pytest
  if ($LASTEXITCODE -ne 0) { throw "Backend tests failed" }

  Push-Location (Join-Path $projectRoot "frontend")
  try {
    & $NpmCmd run test
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }

    & $NpmCmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
  } finally {
    Pop-Location
  }
} finally {
  Pop-Location
}

Write-Host "All checks passed."
