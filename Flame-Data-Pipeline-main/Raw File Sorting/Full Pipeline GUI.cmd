@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FLAME Full Pipeline GUI

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

set "VENV_DIR=%APP_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "DEPS_MARKER=%VENV_DIR%\.flame_pipeline_deps_installed"

call :validate_existing_venv

if not exist "%PYTHON_EXE%" (
    call :find_python_runtime
    if not defined PYTHON_CMD (
        call :install_python_runtime
        if not errorlevel 1 (
            py -3.11 --version >nul 2>nul
            if not errorlevel 1 set "PYTHON_CMD=py -3.11"
        )
    )

    if not defined PYTHON_CMD (
        echo.
        echo Failed to find or install a compatible Python runtime.
        echo Install Python 3.11 or 3.12, then run this launcher again.
        echo Recommended command:
        echo winget install Python.Python.3.11
        echo.
        pause
        exit /b 1
    )

    call :python_version_text
    echo Creating virtual environment with !PYTHON_VERSION_TEXT!...
    call !PYTHON_CMD! -m venv "%VENV_DIR%"
    if errorlevel 1 goto venv_failed
)

if not exist "%PYTHON_EXE%" goto venv_missing

call :deps_available
if errorlevel 1 (
    set "NEED_DEPS_INSTALL=1"
) else if not exist "%DEPS_MARKER%" (
    set "NEED_DEPS_INSTALL=1"
) else (
    set "NEED_DEPS_INSTALL=0"
)

if "%NEED_DEPS_INSTALL%"=="1" (
    call :install_dependencies
    if errorlevel 1 goto deps_failed
)

if "%FLAME_LAUNCHER_SETUP_ONLY%"=="1" (
    echo Setup complete. FLAME_LAUNCHER_SETUP_ONLY=1, so the GUI was not started.
    exit /b 0
)

echo Starting FLAME Full Pipeline GUI...
"%PYTHON_EXE%" "%APP_DIR%Full Pipeline GUI.py"
if errorlevel 1 (
    echo.
    echo FLAME Full Pipeline GUI exited with an error.
    pause
    exit /b 1
)

exit /b 0

:validate_existing_venv
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv uses an unsupported Python version. Rebuilding .venv...
        rmdir /s /q "%VENV_DIR%" >nul 2>nul
    )
)
exit /b 0

:find_python_runtime
set "PYTHON_CMD="
for %%V in (3.11 3.12) do (
    if not defined PYTHON_CMD (
        py -%%V --version >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=py -%%V"
    )
)
if defined PYTHON_CMD exit /b 0

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
exit /b 0

:install_python_runtime
echo.
echo No compatible Python 3.11 or 3.12 runtime was found.
echo Attempting to install Python 3.11 with winget...
where winget >nul 2>nul
if errorlevel 1 (
    echo winget is not available on this computer.
    exit /b 1
)

winget install --id Python.Python.3.11 -e --source winget --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Python 3.11 install with user scope failed. Retrying without --scope user...
    winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
)
exit /b %errorlevel%

:python_version_text
set "PYTHON_VERSION_TEXT=selected Python"
for /f "delims=" %%P in ('!PYTHON_CMD! --version 2^>^&1') do (
    set "PYTHON_VERSION_TEXT=%%P"
)
exit /b 0

:deps_available
"%PYTHON_EXE%" -c "import cv2, exif, matplotlib, numpy, pandas, PIL, psutil, PySimpleGUI" >nul 2>nul
exit /b %errorlevel%

:install_dependencies
echo Installing FLAME Full Pipeline dependencies. This may take a few minutes on the first run...
"%PYTHON_EXE%" -m ensurepip --upgrade
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -m pip install --upgrade "pip<25" setuptools
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -m pip install -r "%APP_DIR%requirements.txt" -r "%APP_DIR%..\Image GPS Tracing\requirements.txt"
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -m pip install numpy==1.26.4 opencv-python==4.9.0.80 pillow==10.2.0 pyasn1==0.5.1 rsa==4.9 PySimpleGUI==4.60.5.1
if errorlevel 1 exit /b 1

call :deps_available
if errorlevel 1 exit /b 1

echo installed>"%DEPS_MARKER%"
exit /b 0

:venv_failed
echo.
echo Failed to create the virtual environment.
echo The launcher tried to use Python 3.11 or 3.12.
echo.
pause
exit /b 1

:venv_missing
echo.
echo The virtual environment was not created correctly:
echo %VENV_DIR%
echo.
pause
exit /b 1

:deps_failed
echo.
echo Dependency installation failed. Check the message above for the package that failed.
pause
exit /b 1
