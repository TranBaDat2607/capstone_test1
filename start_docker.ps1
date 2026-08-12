
# Windows PowerShell Start Script for Neo4j Docker
$ErrorActionPreference = "Stop"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  GREENWASHING KG - DOCKER NEO4J QUICKSTART (PowerShell)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Starting Docker container..." -ForegroundColor Yellow
docker compose up -d

Write-Host ""
Write-Host "[2/3] Waiting for Neo4j container to become ready..." -ForegroundColor Yellow

$healthy = $false
while (-not $healthy) {
    $result = docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui "RETURN 1" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $healthy = $true
    } else {
        Start-Sleep -Seconds 3
        Write-Host "  Waiting for Neo4j container..." -ForegroundColor Gray
    }
}

Write-Host "[OK] Neo4j is ready!" -ForegroundColor Green
Write-Host ""

Write-Host "[3/3] Initializing user and database (init.cypher)..." -ForegroundColor Yellow
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  NEO4J DOCKER SETUP COMPLETE!" -ForegroundColor Green
Write-Host "  - Neo4j Browser UI: http://localhost:8474" -ForegroundColor White
Write-Host "  - Bolt URI: bolt://localhost:8687" -ForegroundColor White
Write-Host "  - DB Name: greenwashingkg" -ForegroundColor White
Write-Host "  - User: greenwashing / Pass: nammovuivui" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To load graph data into Neo4j, run:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\python.exe src/run.py neo4j_load --clear" -ForegroundColor White
