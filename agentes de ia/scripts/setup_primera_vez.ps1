# Setup inicial NASA (Windows PowerShell).
#   cd <raiz-nasa>
#   powershell -ExecutionPolicy Bypass -File scripts\setup_primera_vez.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

Write-Host "== Raiz proyecto: $Root =="

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creando venv..."
    python -m venv venv
}
& .\venv\Scripts\python.exe -m pip install -U pip setuptools wheel
& .\venv\Scripts\pip.exe install -r requirements.txt

Write-Host "== Generando CSV ontology_neo4j =="
& .\venv\Scripts\python.exe scripts\build_ontology_neo4j_csvs.py

$dockerExe = $null
$cmd = Get-Command docker -ErrorAction SilentlyContinue
if ($cmd) { $dockerExe = $cmd.Source }
elseif (Test-Path "C:\Program Files\Docker\Docker\resources\bin\docker.exe") {
    $dockerExe = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
}

if ($dockerExe) {
    Write-Host "== Docker: $dockerExe =="
    & $dockerExe rm -f neo4j-marketplace 2>$null
    $neoArgs = @(
        "run", "-d", "--name", "neo4j-marketplace",
        "-p", "7474:7474", "-p", "7687:7687",
        "-e", "NEO4J_AUTH=neo4j/marketplace2026",
        "-e", 'NEO4J_PLUGINS=["n10s","apoc"]',
        "-e", "NEO4J_dbms_security_procedures_unrestricted=n10s.*,apoc.*",
        "-e", "NEO4J_dbms_security_procedures_allowlist=n10s.*,apoc.*",
        "neo4j:5"
    )
    & $dockerExe @neoArgs
    Write-Host "Esperando arranque Neo4j (45s)..."
    Start-Sleep -Seconds 45
} else {
    Write-Host "AVISO: docker no encontrado; salta contenedor Neo4j."
}

$py = Join-Path $Root "venv\Scripts\python.exe"
& $py ontology\aplicar_esquema.py
& $py ontology\cargar_datos.py
& $py -m ontology_semantic.bridge init
& $py -m ontology_semantic.bridge importar ontology_semantic\marketplace.ttl
& $py -m optimization.owl.cargar_catalogo
& $py -m pytest tests -q --tb=line

Write-Host "== Listo =="
