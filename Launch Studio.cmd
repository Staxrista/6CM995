@echo off
setlocal
cd /d "%~dp0"
if defined STUDIO_PYTHON goto validate_python
if exist "%~dp0.venv\Scripts\python.exe" (
  set "STUDIO_PYTHON=%~dp0.venv\Scripts\python.exe"
  goto validate_python
)
if exist "%~dp0.local\python-path.txt" set /p "STUDIO_PYTHON=" < "%~dp0.local\python-path.txt"
if defined STUDIO_PYTHON goto validate_python
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "STUDIO_PYTHON=%%P"
if defined STUDIO_PYTHON goto validate_python
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "STUDIO_PYTHON=%%P"
if defined STUDIO_PYTHON goto validate_python
echo Python was not found. Install Python 3.10 or later and see README.md.
pause
exit /b 1

:validate_python
if not exist "%STUDIO_PYTHON%" (
  echo The configured Python executable was not found. See README.md.
  pause
  exit /b 1
)
"%STUDIO_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or later is required. See README.md.
  pause
  exit /b 1
)
"%STUDIO_PYTHON%" -c "import sys; sys.path.insert(0, '.deps/desktop'); from PySide6 import QtWidgets" >nul 2>nul
if errorlevel 1 (
  echo Desktop dependencies are unavailable for this interpreter.
  echo Run the following command from the project directory:
  echo "%STUDIO_PYTHON%" -m pip install --target .deps/desktop -r requirements-desktop.txt
  pause
  exit /b 1
)
if /i "%~1"=="--smoke-test" goto run_check
if /i "%~1"=="--research-smoke-test" goto run_check
for %%P in ("%STUDIO_PYTHON%") do set "STUDIO_PYTHONW=%%~dpPpythonw.exe"
if not exist "%STUDIO_PYTHONW%" set "STUDIO_PYTHONW=%STUDIO_PYTHON%"
start "" "%STUDIO_PYTHONW%" "%~dp0studio_app.py" %*
exit /b 0

:run_check
"%STUDIO_PYTHON%" "%~dp0studio_app.py" %*
exit /b %ERRORLEVEL%
