# app\scripts\prime_db.py

import sys
from app.data.collector import backfill_to, upsert_candles  # 也保留 upsert_candles 以便單批抓
from app.data.features import compute_and_upsert_features
from app.db import exec

SYMBOL   = "BTCUSDT"
INTERVAL = "1m"

def count_all(sql: str, **params) -> int:
    return int(exec(sql, **params).scalar() or 0)

def parse_args():
    """
    用法：
      python -m app.scripts.prime_db
      python -m app.scripts.prime_db <target_total> <batch_size>
    例如：
      python -m app.scripts.prime_db 2000 1000  → 目標抓到 2000 根，每批最多 1000 根
    """
    target_total = 1000
    batch_size = 1000
    if len(sys.argv) >= 2 and sys.argv[1].isdigit():
        target_total = int(sys.argv[1])
    if len(sys.argv) >= 3 and sys.argv[2].isdigit():
        batch_size = int(sys.argv[2])
    return target_total, batch_size

def main():
    target_total, batch_size = parse_args()

    print("== 檢查目前資料量 ==")
    print("settings rows :", count_all("SELECT COUNT(*) FROM settings"))
    print("templates act :", count_all("SELECT COUNT(*) FROM templates WHERE status='ACTIVE'"))
    before_c = count_all("SELECT COUNT(*) FROM candles WHERE symbol=:s AND `interval`=:i", s=SYMBOL, i=INTERVAL)
    before_f = count_all("SELECT COUNT(*) FROM features WHERE symbol=:s AND `interval`=:i", s=SYMBOL, i=INTERVAL)
    print("candles(1m)  :", before_c)
    print("features(1m) :", before_f)

    print(f"\n== ① 回補 K 線（目標 {target_total} 根，每批最多 {batch_size}）==")
    wrote = backfill_to(SYMBOL, INTERVAL, target_total=target_total, batch_size=batch_size)
    after_c = count_all("SELECT COUNT(*) FROM candles WHERE symbol=:s AND `interval`=:i", s=SYMBOL, i=INTERVAL)
    print(f"  本次新增寫入: {wrote}")
    print(f"  candles(1m) 現在有: {after_c}")

    print("\n== ② 計算技術指標（features）==")
    lookback = max(600, after_c)  # 盡量多給一些，避免 NaN 暖機被丟太多
    wrote_f = compute_and_upsert_features(SYMBOL, INTERVAL, lookback=lookback)
    after_f = count_all("SELECT COUNT(*) FROM features WHERE symbol=:s AND `interval`=:i", s=SYMBOL, i=INTERVAL)
    print(f"  本次寫入 features：{wrote_f}")
    print(f"  features(1m) 現在有：{after_f}")

    print("\n完成。之後跑 app.main 應不會再顯示模組未就緒。")

if __name__ == "__main__":
    main()
