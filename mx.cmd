@echo off
setlocal enableextensions

:: prefer the interpreter specified by MX_PYTHON
if defined MX_PYTHON (
  set "python_exe=%MX_PYTHON%"
) else if defined MX_PYTHON_VERSION (
  set "python_exe=python%MX_PYTHON_VERSION%"
) else (
  set "python_exe=python"
)

:: local variables can be used after endlocal if on the same line
endlocal & "%python_exe%" -u "%~dp0mx_enter.py" %*
