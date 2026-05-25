@echo off
title Basketball Stats Server
start "Basketball Stats Server" powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0server.ps1"
