@echo off
cd /d "%~dp0"

if exist "dist\VibePlay.exe" (
    start "" "dist\VibePlay.exe"
) else (
    python sports_replay_v4.py
)
