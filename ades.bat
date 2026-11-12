@echo off
REM CLI unificado de ADES-AI (feature #26). Uso: ades ^<comando^>
pushd "%~dp0"
python -m ades_cli %*
set ERR=%ERRORLEVEL%
popd
exit /b %ERR%
