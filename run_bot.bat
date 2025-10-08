@echo off
REM === [Autobot 專案虛擬環境啟動腳本] ===
cd /d F:\autobot

REM 啟用 Python 虛擬環境
call .venv\Scripts\activate

echo.
python --version
echo.

REM 停留在虛擬環境命令列
cmd
