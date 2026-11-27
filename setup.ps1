# Einmaliges Setup: virtuelle Umgebung anlegen, Abhaengigkeiten installieren, Excel importieren.
# Aufruf aus dem Projektordner:  .\setup.ps1   (oder Doppelklick auf setup.bat)
# Erneut ausfuehrbar: vorhandene .venv wird weiterverwendet, die DB wird neu aufgebaut.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$excel = Join-Path $PSScriptRoot "data\Musterliste_apoBank.xlsx"

function Invoke-Step($text, [scriptblock]$block) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "Fehlgeschlagen: $text (Exit-Code $LASTEXITCODE)" }
}

# 1. Excel vorhanden?
if (-not (Test-Path $excel)) {
    throw "Excel-Datei fehlt: $excel`nBitte Musterliste_apoBank.xlsx in den Ordner data\ legen."
}

# 2. Virtuelle Umgebung
if (Test-Path $venvPython) {
    Write-Host "==> .venv existiert bereits, wird weiterverwendet" -ForegroundColor Cyan
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw "Python wurde nicht gefunden. Bitte Python installieren und zum PATH hinzufuegen." }
    Invoke-Step "Virtuelle Umgebung anlegen (.venv)" { python -m venv .venv }
}

# 3. Abhaengigkeiten (unvollstaendige .venv ohne pip reparieren)
$ErrorActionPreference = "Continue"
& $venvPython -m pip --version *> $null
$pipFehlt = $LASTEXITCODE -ne 0
$ErrorActionPreference = "Stop"
if ($pipFehlt) {
    Invoke-Step "pip in .venv nachinstallieren" { & $venvPython -m ensurepip --upgrade }
}
Invoke-Step "pip aktualisieren" { & $venvPython -m pip install --upgrade pip --quiet }
Invoke-Step "Abhaengigkeiten installieren (requirements.txt)" { & $venvPython -m pip install -r requirements.txt --quiet }

# 4. Excel -> SQLite + Obsidian-Vault
Invoke-Step "Excel importieren (DB + Vault)" { & $venvPython -m backend.import_excel --reset --excel $excel }

# 5. Konfiguration: .env (Einstellungen) und .env.local (geheime Schluessel, nie committen)
if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Copy-Item ".env.example" ".env"
    Write-Host "Hinweis: .env aus .env.example angelegt." -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $PSScriptRoot ".env.local"))) {
    Set-Content -Path ".env.local" -Encoding utf8 -Value "# Geheime Schluessel - wird nicht committet`nOPENAI_API_KEY="
    Write-Host "Hinweis: .env.local angelegt - OPENAI_API_KEY dort eintragen." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup fertig." -ForegroundColor Green
Write-Host "Backend starten:  .venv\Scripts\python -m uvicorn backend.main:app --reload"
Write-Host "Frontend starten: cd frontend; npm install; npm run dev"
