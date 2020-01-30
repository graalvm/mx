@echo off
setlocal enableextensions

:: prefer the interpreter specified by MX_PYTHON
if defined MX_PYTHON (
  %MX_PYTHON% -u "%~dp0mx.py" %*
) else (
  python -u "%~dp0mx.py" %*
)
