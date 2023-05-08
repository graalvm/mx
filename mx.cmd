@echo off
setlocal enableextensions

:: note: do not use parentheses around commands because that will break passing arguments that contain parentheses (see https://ss64.com/nt/syntax-brackets.html)

:: prefer the interpreter specified by MX_PYTHON
if defined MX_PYTHON %MX_PYTHON% -u "%~dp0mx.py" %* & goto :eof
if defined MX_PYTHON_VERSION python%MX_PYTHON_VERSION% -u "%~dp0mx.py" %* & goto :eof
python -u "%~dp0mx_enter.py" %*
