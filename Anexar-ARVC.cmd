@echo off
setlocal
cd /d "%~dp0"
py "%~dp0arvc_interface.py"
if errorlevel 1 pause
