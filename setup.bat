@echo off
rem Startet setup.ps1 ohne die PowerShell-Ausfuehrungsrichtlinie aendern zu muessen.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
