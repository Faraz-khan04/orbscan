@echo off
cd /d "%~dp0"
start "" /b pythonw -m orbscan collect
echo orbscan collector started in the background. Log: orbscan.log  Stop: stop.bat
