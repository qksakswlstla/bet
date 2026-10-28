@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation complete. Run start_windows.bat.
pause
exit /b 0
:fail
echo Installation failed. Check the error above and README.md.
pause
exit /b 1
