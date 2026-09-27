@echo off
REM Downloads free public research data (SEC insider filings, SEC financial statements, Yahoo prices)
REM to C:\Users\<you>\research_data. Takes about 20-40 minutes. Nothing is traded; nothing is uploaded.
cd /d "%USERPROFILE%"
if not exist research_data mkdir research_data
cd research_data
set "PY=%USERPROFILE%\anaconda3\python.exe"
if not exist "%PY%" set "PY=python"
set "OUT=%USERPROFILE%\research_data"
REM The SEC asks every automated download to include a contact address:
set "SEC_CONTACT=cashoutsav8-bit@users.noreply.github.com"
echo Getting the latest download script...
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/cashoutsav8-bit/stock-paper-bot/main/research/fetch_data.py -OutFile fetch_data.py"
"%PY%" -m pip install -q pyarrow pandas numpy
echo Downloading data. Leave this window open (20-40 minutes)...
"%PY%" fetch_data.py universe extra insider fundamentals prices
echo.
echo Done. Files are in %OUT%
pause
