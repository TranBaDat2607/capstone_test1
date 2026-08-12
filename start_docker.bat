@echo off
echo ========================================================
echo   GREENWASHING KG - DOCKER NEO4J QUICKSTART
echo ========================================================
echo.

echo [1/3] Starting Docker containers...
docker compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to run docker compose. Please check Docker Desktop.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/3] Waiting for Neo4j container to become ready...
:wait_loop
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui "RETURN 1" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    ping 127.0.0.1 -n 4 >nul
    echo   Waiting for Neo4j...
    goto wait_loop
)

echo [OK] Neo4j is ready!

echo.
echo [3/3] Initializing Neo4j user and database (init.cypher)...
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher

echo.
echo ========================================================
echo   NEO4J DOCKER SETUP COMPLETE!
echo   - Neo4j Browser UI: http://localhost:8474
echo   - Bolt URI: bolt://localhost:8687
echo   - DB Name: greenwashingkg
echo   - User: greenwashing / Pass: nammovuivui
echo ========================================================
echo.
echo To load graph data into Neo4j, run:
echo   .\.venv\Scripts\python.exe src/run.py neo4j_load --clear
echo.
pause
