# app/policy/templates_repo.py
from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple
import json
import time
from ..db import exec  # 若你原本是 q，請改：from ..db import q as exec

# ---------- Templates 基本 CRUD ----------

def seed_templates(seed_rows: List[Dict]) -> int:
    """
    批次寫入模板種子。seed_rows 例：
    {
      "version": 1,
      "side": "LONG",            # 或 "SHORT"
      "rsi_bin": "L|M|H|X" or None,
      "macd_bin": "P|N" or None,
      "kd_bin": "P|N" or None,
      "vol_bin": "L|M|H|X" or None,
      "extra": None or dict/json-string
    }
    """
    count = 0
    sql = """
    INSERT INTO templates(version, side, rsi_bin, macd_bin, kd_bin, vol_bin, extra, status)
    VALUES(:version, :side, :rsi_bin, :macd_bin, :kd_bin, :vol_bin, :extra, 'ACTIVE')
    """
    for r in seed_rows:
        extra = r.get("extra")
        if isinstance(extra, (dict, list)):
            r = {**r, "extra": json.dumps(extra, ensure_ascii=False)}
        exec(sql, **r)
        count += 1
    return count


def insert_template(version: int, side: str,
                    rsi_bin: Optional[str], macd_bin: Optional[str],
                    kd_bin: Optional[str], vol_bin: Optional[str],
                    extra: Optional[Any] = None,
                    status: str = "ACTIVE") -> int:
    if isinstance(extra, (dict, list)):
        extra = json.dumps(extra, ensure_ascii=False)
    res = exec(
        """
        INSERT INTO templates(version, side, rsi_bin, macd_bin, kd_bin, vol_bin, extra, status)
        VALUES(:v, :s, :rsi, :macd, :kd, :vol, :e, :st)
        """,
        v=version, s=side, rsi=rsi_bin, macd=macd_bin, kd=kd_bin, vol=vol_bin, e=extra, st=status
    )
    return int(res.lastrowid)


def get_active_templates() -> List[Dict]:
    rows = exec("SELECT * FROM templates WHERE status='ACTIVE' ORDER BY template_id").mappings().all()
    return [dict(r) for r in rows]


def get_all_templates() -> List[Dict]:
    rows = exec("SELECT * FROM templates ORDER BY template_id").mappings().all()
    return [dict(r) for r in rows]


def get_template(template_id: int) -> Optional[Dict]:
    r = exec("SELECT * FROM templates WHERE template_id=:t", t=template_id).mappings().first()
    return dict(r) if r else None


def freeze_template(template_id: int) -> None:
    exec("UPDATE templates SET status='FROZEN' WHERE template_id=:t", t=template_id)
    exec("UPDATE template_stats SET is_frozen=1 WHERE template_id=:t", t=template_id)


def unfreeze_template(template_id: int) -> None:
    exec("UPDATE templates SET status='ACTIVE' WHERE template_id=:t", t=template_id)
    exec("UPDATE template_stats SET is_frozen=0 WHERE template_id=:t", t=template_id)


def clone_template(template_id: int, patch: Optional[Dict[str, Any]] = None, note: str = "") -> int:
    """
    從既有 template 複製出新列；version 自動 +1，可用 patch 覆蓋欄位。
    回傳新 template_id
    """
    src = get_template(template_id)
    if not src:
        raise ValueError(f"template_id {template_id} 不存在")

    fields = {
        "version": int(src["version"]) + 1,
        "side": src["side"],
        "rsi_bin": src.get("rsi_bin"),
        "macd_bin": src.get("macd_bin"),
        "kd_bin": src.get("kd_bin"),
        "vol_bin": src.get("vol_bin"),
        "extra": src.get("extra"),
    }
    if patch:
        fields.update(patch)

    # 註記親代/說明
    try:
        extra = json.loads(fields["extra"]) if fields.get("extra") else {}
    except Exception:
        extra = {}
    extra.update({
        "parent_id": template_id,
        "cloned_at": int(time.time() * 1000),
        "note": note or extra.get("note", "")
    })
    fields["extra"] = extra
    new_id = insert_template(
        version=fields["version"], side=fields["side"],
        rsi_bin=fields["rsi_bin"], macd_bin=fields["macd_bin"],
        kd_bin=fields["kd_bin"], vol_bin=fields["vol_bin"],
        extra=fields["extra"], status="ACTIVE"
    )
    return new_id


# ---------- template_stats 線上更新（與你原本一致） ----------

def upsert_template_stats(template_id: int, regime: int, reward: float) -> None:
    """
    線上更新模板績效統計（簡化 Welford M2 累積）。
    注意：reward_var 儲存的是 M2（平方偏差和），要算方差需 / n。
    """
    row = exec(
        "SELECT n_trades, reward_sum, reward_mean, reward_var "
        "FROM template_stats WHERE template_id=:t AND regime=:r",
        t=template_id, r=regime
    ).mappings().first()

    if row is None:
        exec(
            """
            INSERT INTO template_stats(template_id, regime, n_trades, reward_sum, reward_mean, reward_var, last_used_at)
            VALUES(:t, :r, 1, :rw, :rw, 0, UNIX_TIMESTAMP()*1000)
            """,
            t=template_id, r=regime, rw=reward
        )
        return

    n_prev = int(row["n_trades"] or 0)
    s_prev = float(row["reward_sum"] or 0.0)
    mean_prev = float(row["reward_mean"] or 0.0)
    m2_prev = float(row["reward_var"] or 0.0)  # M2

    n_new = n_prev + 1
    s_new = s_prev + reward
    mean_new = s_new / n_new
    # Welford 的 M2 增量計算
    m2_new = m2_prev + (reward - mean_prev) * (reward - mean_new)

    exec(
        """
        UPDATE template_stats
        SET n_trades=:n, reward_sum=:s, reward_mean=:m, reward_var=:v, last_used_at=UNIX_TIMESTAMP()*1000
        WHERE template_id=:t AND regime=:r
        """,
        n=n_new, s=s_new, m=mean_new, v=m2_new, t=template_id, r=regime
    )


def touch_template_last_used(template_id: int, regime: int) -> None:
    exec(
        "UPDATE template_stats SET last_used_at=UNIX_TIMESTAMP()*1000 WHERE template_id=:t AND regime=:r",
        t=template_id, r=regime
    )


# ---------- Stats 查詢/彙總工具 ----------

def get_stats_rows(template_id: int) -> List[Dict[str, Any]]:
    rows = exec(
        "SELECT * FROM template_stats WHERE template_id=:t",
        t=template_id
    ).mappings().all()
    return [dict(r) for r in rows]


def get_all_stats_rows(active_only: bool = True) -> List[Dict[str, Any]]:
    sql = """
    SELECT ts.*
    FROM template_stats ts
    JOIN templates t ON t.template_id = ts.template_id
    WHERE (:active=0 OR t.status='ACTIVE')
    """
    rows = exec(sql, active=int(active_only)).mappings().all()
    return [dict(r) for r in rows]


def summarize_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    對單一 template 的多 regime 列做彙總。
    reward_var 欄位存的是 M2（平方偏差和），彙總可直接相加。
    """
    n = sum(int(r.get("n_trades") or 0) for r in rows)
    s = sum(float(r.get("reward_sum") or 0.0) for r in rows)
    m2 = sum(float(r.get("reward_var") or 0.0) for r in rows)
    mean = (s / n) if n > 0 else 0.0
    var = (m2 / n) if n > 0 else 0.0
    last_used_at = max((int(r.get("last_used_at") or 0) for r in rows), default=0)
    frozen = max((int(r.get("is_frozen") or 0) for r in rows), default=0)
    return dict(n_trades=n, reward_sum=s, reward_mean=mean, reward_var=var,
                last_used_at=last_used_at, is_frozen=frozen)


def get_all_templates_summary(active_only: bool = True) -> Dict[int, Dict[str, Any]]:
    """
    回傳 {template_id: summary_stats}
    """
    rows = get_all_stats_rows(active_only=active_only)
    bucket: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        bucket.setdefault(int(r["template_id"]), []).append(r)
    out: Dict[int, Dict[str, Any]] = {}
    for tid, lst in bucket.items():
        out[tid] = summarize_stats(lst)
    return out


def count_active_templates() -> int:
    row = exec("SELECT COUNT(*) AS c FROM templates WHERE status='ACTIVE'").mappings().first()
    return int(row["c"] if row else 0)


def template_fingerprint(tpl: Dict[str, Any]) -> str:
    """
    用於避免重覆插入相同條件的模板。
    """
    return "|".join([
        tpl["side"],
        str(tpl.get("rsi_bin") or ""),
        str(tpl.get("macd_bin") or ""),
        str(tpl.get("kd_bin") or ""),
        str(tpl.get("vol_bin") or ""),
    ])


def all_fingerprints() -> set:
    fps = set()
    for t in get_all_templates():
        fps.add(template_fingerprint(t))
    return fps

# ---------- Evolution event 記錄 ----------

def insert_evolution_event(action: str,
                           source_template_ids: Optional[List[int]] = None,
                           new_template_id: Optional[int] = None,
                           notes: Optional[str] = None) -> None:
    """
    寫入 evolution_events（ts 使用 DB 的 UNIX_TIMESTAMP()*1000）
    action: 'MUTATE' | 'CROSS' | 'RANDOM' | 'FREEZE' | 'UNFREEZE'
    """
    src = ",".join(str(x) for x in (source_template_ids or [])) or None
    exec(
        """
        INSERT INTO evolution_events(ts, action, source_template_ids, new_template_id, notes)
        VALUES (UNIX_TIMESTAMP()*1000, :a, :src, :nid, :nt)
        """,
        a=action, src=src, nid=new_template_id, nt=notes
    )


# ---------- Evolution event 記錄 ----------

def insert_evolution_event(action: str,
                           source_template_ids: Optional[List[int]] = None,
                           new_template_id: Optional[int] = None,
                           notes: Optional[str] = None) -> None:
    """
    寫入 evolution_events（ts 使用 DB 的 UNIX_TIMESTAMP()*1000）
    action: 'MUTATE' | 'CROSS' | 'RANDOM' | 'FREEZE' | 'UNFREEZE'
    """
    src = ",".join(str(x) for x in (source_template_ids or [])) or None
    exec(
        """
        INSERT INTO evolution_events(ts, action, source_template_ids, new_template_id, notes)
        VALUES (UNIX_TIMESTAMP()*1000, :a, :src, :nid, :nt)
        """,
        a=action, src=src, nid=new_template_id, nt=notes
    )

def get_evolution_events_7d() -> List[Dict[str, Any]]:
    rows = exec(
        """
        SELECT FROM_UNIXTIME(ts/1000, '%Y-%m-%d') AS d,
               SUM(action='MUTATE') AS n_mutate,
               SUM(action='CROSS')  AS n_cross,
               SUM(action='FREEZE') AS n_freeze
        FROM evolution_events
        WHERE ts >= (UNIX_TIMESTAMP(CURRENT_DATE - INTERVAL 6 DAY) * 1000)
        GROUP BY d
        ORDER BY d
        """
    ).mappings().all()
    return [dict(r) for r in rows]

def get_templates_pool_status() -> List[Dict[str, Any]]:
    rows = exec("SELECT status, COUNT(*) AS c FROM templates GROUP BY status").mappings().all()
    return [dict(r) for r in rows]

def get_recent_evolution_events(limit: int = 50) -> List[Dict[str, Any]]:
    rows = exec(
        "SELECT * FROM evolution_events ORDER BY event_id DESC LIMIT :lim",
        lim=int(limit)
    ).mappings().all()
    return [dict(r) for r in rows]
