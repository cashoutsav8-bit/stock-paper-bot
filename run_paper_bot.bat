@echo off
REM Runs the stock paper bot ON THIS COMPUTER (backup / testing). The main copy runs on GitHub.
cd /d "%~dp0"
set "PY=%USERPROFILE%\anaconda3\python.exe"
if not exist "%PY%" set "PY=python"
set "PAPERBOT_DATA=%~dp0docs"
echo Running stock paper strategies (PAPER ONLY, no real orders). This takes 1-2 minutes...
echo ===== %date% %time% =====>> run_log.txt
"%PY%" bot\stock_bot.py >> run_log.txt 2>&1
powershell -NoProfile -Command "Get-Content run_log.txt -Tail 15"
start "" "%~dp0docs\compare.html"
pause
