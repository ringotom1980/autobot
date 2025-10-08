# Autobot MVP


## 快速開始
1. `python -m venv .venv && . .venv/Scripts/activate` (Windows) / `. .venv/bin/activate` (Unix)
2. `pip install -r requirements.txt`
3. 建庫：`mysql -u root -p < schema_mysql.sql`
4. 複製 `.env.example` 為 `.env`，填 DB 與 Binance Key（本機）
5. `python -m app.main` ；觀察 log（每分鐘輪詢，下載 K 線、計算特徵、給出 {LONG|SHORT|HOLD}）
6. 部署 `web/` 到虛擬主機，設定環境變數以連到同一個 DB


> MVP 預設 **不會真的下單**，只會建倉記錄；待你確認後，在 `executor.py` 補真實下單與狀態機。