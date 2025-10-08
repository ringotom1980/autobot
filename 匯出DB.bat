@echo off
REM ================================================
REM  Autobot 匯出 SQL 結構
REM  作者：湯億林
REM  功能：執行 app\scripts\dump_schema.py
REM ================================================

REM 設定命令列為 UTF-8，解決中文亂碼
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM 切換到專案根目錄
cd /d %~dp0

echo [Autobot] 啟用虛擬環境...
IF EXIST .venv\Scripts\activate (
  call .venv\Scripts\activate
) ELSE (
  echo ⚠ 找不到 .venv\Scripts\activate，可能未建立虛擬環境。
)

echo [Autobot] 匯出資料庫結構中...
python app\scripts\dump_schema.py

IF %ERRORLEVEL% EQU 0 (
  echo.
  echo ✅ 匯出完成：schema_mysql.sql 已更新。
) ELSE (
  echo.
  echo ❌ 匯出失敗，請檢查上方錯誤訊息。
)

echo.
pause
