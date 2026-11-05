@echo off
echo ========================================================
echo Iniciando Ecosistema IA - Software Factory...
echo ========================================================

:: Verifica si Docker esta corriendo
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker no esta en ejecucion. Por favor, abre Docker Desktop primero.
    pause
    exit /b
)

:: Levanta todos los servicios en segundo plano
echo Levantando bases de datos de memoria (GraphRAG y Vectorial) y cache...
docker compose up -d

echo ========================================================
echo Ecosistema iniciado correctamente.
echo - Neo4j (GraphRAG) disponible en: http://localhost:7474
echo - Qdrant (Vectorial) disponible en: http://localhost:6333
echo - Redis (Cache semantico) disponible en: http://localhost:6379
echo ========================================================
pause