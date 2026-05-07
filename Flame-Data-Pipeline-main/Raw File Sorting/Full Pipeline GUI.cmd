@echo off
setlocal EnableExtensions
title FLAME Full Pipeline GUI

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

set "VENV_DIR=%APP_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "ACTIVATE_SCRIPT=%VENV_DIR%\Scripts\activate.bat"
set "DEPS_MARKER=%VENV_DIR%\.flame_pipeline_deps_installed"

if not exist "%PYTHON_EXE%" (
    echo Creating Python 3.11 virtual environment...
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo Failed to create the Python 3.11 virtual environment.
        echo Install Python 3.11 with:
        echo winget install Python.Python.3.11
        echo.
        pause
        exit /b 1
    )
)

call "%ACTIVATE_SCRIPT%"
if errorlevel 1 (
    echo Failed to activate the virtual environment at:
    echo %VENV_DIR%
    pause
    exit /b 1
)

if not exist "%DEPS_MARKER%" (
    echo Installing FLAME Full Pipeline dependencies. This may take a few minutes on the first run...
    python -m pip install "pip<25"
    if errorlevel 1 goto deps_failed

    python -m pip install -r "%APP_DIR%requirements.txt" -r "%APP_DIR%..\Image GPS Tracing\requirements.txt"
    if errorlevel 1 goto deps_failed

    python -m pip install numpy==1.26.4 opencv-python==4.9.0.80 pillow==10.2.0 pyasn1==0.5.1 rsa==4.9 PySimpleGUI==4.60.5.1
    if errorlevel 1 goto deps_failed

    echo installed>"%DEPS_MARKER%"
)

echo Starting FLAME Full Pipeline GUI...
python "%APP_DIR%Full Pipeline GUI.py"
if errorlevel 1 (
    echo.
    echo FLAME Full Pipeline GUI exited with an error.
    pause
    exit /b 1
)

exit /b 0

:deps_failed
echo.
echo Dependency installation failed. Check the message above for the package that failed.
pause
exit /b 1
