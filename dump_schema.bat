@echo off
REM ======================================================
REM  Autobot - 匯出資料庫結構（schema_mysql.sql）
REM  作者：湯億林
REM  功能：透過 SSH 連線遠端 DB，下載僅結構版本
REM ======================================================

cd /d %~dp0
echo [Autobot] 匯出資料庫結構開始...

REM 確保虛擬環境存在
IF EXIST .venv\Scripts\activate (
    echo [Autobot] 啟用虛擬環境...
    call .venv\Scripts\activate
) ELSE (
    echo [警告] 找不到虛擬環境 .venv\ ，請確認已建立。
)

REM 執行 Python 模組
python -m app.scripts.dump_schema

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ 匯出完成：schema_mysql.sql 已更新。
) ELSE (
    echo.
    echo ❌ 匯出失敗，請檢查錯誤訊息。
)

pause
