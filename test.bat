@echo off
REM === 切換到專案目錄（請依你的實際路徑修改） ===
cd /d F:\autobot

REM === 啟動虛擬環境 ===
call .venv\Scripts\activate.bat

REM === 執行主程式 ===
python -m app.main

REM === 避免視窗自動關閉 ===
pause
