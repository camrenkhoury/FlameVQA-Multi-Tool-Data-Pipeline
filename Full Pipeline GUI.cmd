@echo off
setlocal EnableExtensions

set "RAW_SORTING_DIR=%~dp0Flame-Data-Pipeline-main\Raw File Sorting"
set "LAUNCHER=%RAW_SORTING_DIR%\Full Pipeline GUI.cmd"

if not exist "%LAUNCHER%" (
    echo Could not find the Full Pipeline GUI launcher:
    echo %LAUNCHER%
    pause
    exit /b 1
)

call "%LAUNCHER%"
exit /b %errorlevel%
