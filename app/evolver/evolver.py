# app/evolver/evolver.py
from __future__ import annotations
import logging
import time
import random
from typing import Dict, Any, List, Optional, Tuple

from ..policy import templates_repo as repo
from ..policy import templates_eval as te

log = logging.getLogger("autobot.evolver")

# -------------------- 可調參數 --------------------
TARGET_ACTIVE = 24          # 目標活躍模板數
TOP_PARENTS = 6             # 每輪擇優父代數量
MUTANTS_PER_PARENT = 2      # 每個父代產生多少變異
FREEZE_MIN_N = 20           # 凍結的最小交易數
LCB_Z = 1.0                 # LCB 檢查強度
RISK_PENALTY = 0.05         # 風險懲罰強度（乘上 sqrt(var)）
UCB_C = 2.0                 # UCB1 參數
STALE_MS = None             # 也可設 7天: 7*24*3600*1000
MIN_OBS_N = 10              # 最低觀察期：新模板至少要有 n 筆交易才允許凍結或清池
# -------------------------------------------------

# 允許集合
RSI_SET = ["L", "M", "H"]          # 保留三段
MACD_SET = ["P", "N"]
KD_SET = ["P", "N"]
VOL_SET = ["L", "M", "H", "X"]     # 四段


def _parse_set(s: Optional[str]) -> List[str]:
    if not s or str(s).strip() in ("", "*"):
        return []
    return [x.strip() for x in str(s).split("|") if x.strip()]


def _stringify_set(xs: List[str]) -> Optional[str]:
    if not xs:
        return None
    return "|".join(sorted(set(xs)))


def _mutate_set(current: Optional[str], universe: List[str]) -> Optional[str]:
    """
    針對欄位值做輕量變異：
    - 目前為空 → 隨機挑 1~2 個值
    - 目前有集合 → 50% 機率縮窄（去掉1個），50% 機率擴張（加1個）。
    """
    cur = _parse_set(current)
    uni = list(universe)

    if not cur:
        k = random.choice([1, 2])
        return _stringify_set(random.sample(uni, k=k))

    if random.random() < 0.5 and len(cur) > 1:
        # 縮窄：刪除一個
        cur.pop(random.randrange(len(cur)))
        return _stringify_set(cur)
    else:
        # 擴張：加一個不在其中的值
        candidates = [x for x in uni if x not in cur]
        if not candidates:
            return _stringify_set(cur)
        cur.append(random.choice(candidates))
        return _stringify_set(cur)


def _mutate_child(parent: Dict[str, Any]) -> Dict[str, Any]:
    """
    由父代產生一個子代（輕量多點突變）。
    """
    child = {
        "side": parent["side"],
        "rsi_bin": parent.get("rsi_bin"),
        "macd_bin": parent.get("macd_bin"),
        "kd_bin": parent.get("kd_bin"),
        "vol_bin": parent.get("vol_bin"),
    }
    # 對每個欄位以一定機率做變異
    if random.random() < 0.8:
        child["rsi_bin"] = _mutate_set(child["rsi_bin"], RSI_SET)
    if random.random() < 0.8:
        child["macd_bin"] = _mutate_set(child["macd_bin"], MACD_SET)
    if random.random() < 0.8:
        child["kd_bin"] = _mutate_set(child["kd_bin"], KD_SET)
    if random.random() < 0.8:
        child["vol_bin"] = _mutate_set(child["vol_bin"], VOL_SET)
    return child

import json

def _parse_extra_flag(t: Dict[str, Any], key: str) -> bool:
    try:
        ex = t.get("extra")
        if isinstance(ex, str):
            ex = json.loads(ex)
        if not isinstance(ex, dict):
            return False
        return bool(ex.get(key, False))
    except Exception:
        return False

def _is_locked(t: Dict[str, Any]) -> bool:
    # 永不凍結 / 清池
    return _parse_extra_flag(t, "locked")

def _is_blacklisted(t: Dict[str, Any]) -> bool:
    # 不作為父代（不參與交配/突變來源）
    return _parse_extra_flag(t, "blacklist")


def _score_and_rank(active_templates: List[Dict[str, Any]],
                    summaries: Dict[int, Dict[str, Any]]) -> List[Tuple[float, Dict[str, Any]]]:
    # total_plays 用於 UCB 探索項
    total_plays = sum(int(summ.get("n_trades") or 0)
                      for summ in summaries.values()) or 1
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for t in active_templates:
        tid = int(t["template_id"])
        summ = summaries.get(tid, {}) or {}
        score = te.bandit_score(
            summ, total_plays, method="ucb1", c=UCB_C, risk_penalty=RISK_PENALTY)
        scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _freeze_bad_ones(active_templates: List[Dict[str, Any]],
                     summaries: Dict[int, Dict[str, Any]]) -> int:
    now_ms = int(time.time() * 1000)
    frozen = 0
    for t in active_templates:
        # 保護：locked 不凍；未達觀察期不凍
        if _is_locked(t):
            continue
        if int((summaries.get(int(t["template_id"]), {}) or {}).get("n_trades") or 0) < MIN_OBS_N:
            continue

        tid = int(t["template_id"])
        summ = summaries.get(tid, {})
        if te.should_freeze(summ, min_n=FREEZE_MIN_N, lcb_z=LCB_Z,
                            stale_ms=STALE_MS, now_ms=now_ms):
            repo.freeze_template(tid)
            frozen += 1
            log.info(f"[evolver] FREEZE template_id={tid} n={summ.get('n_trades')} "
                     f"mean={summ.get('reward_mean'):.6f} var={summ.get('reward_var'):.6f}")
            repo.insert_evolution_event(
                action="FREEZE",
                source_template_ids=[tid],
                new_template_id=None,
                notes=f"auto-freeze by evolver; n={summ.get('n_trades')} mean={summ.get('reward_mean')} var={summ.get('reward_var')}"
            )

    return frozen


def _spawn_children(parents: List[Dict[str, Any]], how_many: int) -> int:
    """
    依序從父代生成子代（避免 fingerprint 重覆），直到補齊 how_many 或用完嘗試。
    """
    if how_many <= 0 or not parents:
        return 0

    existed = repo.all_fingerprints()
    created = 0
    attempts = 0
    max_attempts = how_many * 10  # 避免無限嘗試

    for p in parents:
        for _ in range(MUTANTS_PER_PARENT):
            if created >= how_many or attempts >= max_attempts:
                break
            attempts += 1

            child = _mutate_child(p)
            fp = "|".join([p["side"],
                           str(child.get("rsi_bin") or ""),
                           str(child.get("macd_bin") or ""),
                           str(child.get("kd_bin") or ""),
                           str(child.get("vol_bin") or "")])
            if fp in existed:
                continue

            note = f"mutant from {p['template_id']}"
            new_id = repo.insert_template(
                version=int(p["version"]) + 1,
                side=child["side"],
                rsi_bin=child.get("rsi_bin"),
                macd_bin=child.get("macd_bin"),
                kd_bin=child.get("kd_bin"),
                vol_bin=child.get("vol_bin"),
                extra={"note": note, "parent_id": int(
                    p["template_id"]), "gen_at": int(time.time()*1000)},
                status="ACTIVE"
            )
            existed.add(fp)
            created += 1
            log.info(
                f"[evolver] SPAWN template_id={new_id} from parent={p['template_id']} fp={fp}")
            repo.insert_evolution_event(
                action="MUTATE",
                source_template_ids=[int(p["template_id"])],
                new_template_id=int(new_id),
                notes=f"fingerprint={fp}"
            )

        if created >= how_many or attempts >= max_attempts:
            break

    return created

def _choose_union_or_pick(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """
    CROSS 用：兩個父代欄位（可能是 'L|M' 這種集合或 None）如何合成子代欄位。
    70% 機率取聯集（exploration），30% 機率二擇一（exploitation）。
    """
    if (not a or a.strip() in ("", "*")) and (not b or b.strip() in ("", "*")):
        return None
    if random.random() < 0.7:
        set_a = set(_parse_set(a))
        set_b = set(_parse_set(b))
        uni = sorted(set_a.union(set_b))
        return _stringify_set(uni)
    else:
        pick = a if random.random() < 0.5 else b
        xs = _parse_set(pick)
        if not xs:
            return None
        # 有集合時隨機丟一個子元素（加點隨機性）
        if len(xs) > 1 and random.random() < 0.5:
            xs = [random.choice(xs)]
        return _stringify_set(xs)


def _crossover(pa: Dict[str, Any], pb: Dict[str, Any]) -> Dict[str, Any]:
    """
    從兩個父代產生 1 個交叉子代：side 隨機二擇一；每個欄位用 _choose_union_or_pick 合成。
    """
    return {
        "side": pa["side"] if random.random() < 0.5 else pb["side"],
        "rsi_bin": _choose_union_or_pick(pa.get("rsi_bin"), pb.get("rsi_bin")),
        "macd_bin": _choose_union_or_pick(pa.get("macd_bin"), pb.get("macd_bin")),
        "kd_bin": _choose_union_or_pick(pa.get("kd_bin"), pb.get("kd_bin")),
        "vol_bin": _choose_union_or_pick(pa.get("vol_bin"), pb.get("vol_bin")),
    }


def _spawn_crossed(parents: List[Dict[str, Any]], how_many: int) -> int:
    """
    交叉生成：對所有 (i<j) 父代配對，依序產生子代直到補齊 how_many。
    避免 fingerprint 重覆。
    """
    if how_many <= 0 or len(parents) < 2:
        return 0

    existed = repo.all_fingerprints()
    created = 0
    attempts = 0
    max_attempts = how_many * 10

    n = len(parents)
    for i in range(n):
        for j in range(i + 1, n):
            if created >= how_many or attempts >= max_attempts:
                break
            attempts += 1

            pa, pb = parents[i], parents[j]
            child = _crossover(pa, pb)
            fp = "|".join([
                child["side"],
                str(child.get("rsi_bin") or ""),
                str(child.get("macd_bin") or ""),
                str(child.get("kd_bin") or ""),
                str(child.get("vol_bin") or "")
            ])
            if fp in existed:
                continue

            note = f"cross from {pa['template_id']} & {pb['template_id']}"
            new_id = repo.insert_template(
                version=max(int(pa["version"]), int(pb["version"])) + 1,
                side=child["side"],
                rsi_bin=child.get("rsi_bin"),
                macd_bin=child.get("macd_bin"),
                kd_bin=child.get("kd_bin"),
                vol_bin=child.get("vol_bin"),
                extra={"note": note, "parent_ids": [int(pa["template_id"]), int(pb["template_id"])], "gen_at": int(time.time()*1000)},
                status="ACTIVE"
            )
            existed.add(fp)
            created += 1
            log.info(f"[evolver] CROSS template_id={new_id} from parents={pa['template_id']},{pb['template_id']} fp={fp}")
            repo.insert_evolution_event(
                action="CROSS",
                source_template_ids=[int(pa["template_id"]), int(pb["template_id"])],
                new_template_id=int(new_id),
                notes=f"fingerprint={fp}"
            )

        if created >= how_many or attempts >= max_attempts:
            break

    return created


def _weekly_cleanup(actives: List[Dict[str, Any]], summaries: Dict[int, Dict[str, Any]], keep_n: int) -> int:
    """
    清池：若 ACTIVE 超量，依 bandit_score 由低到高凍結，直到只留下 keep_n。
    回傳凍結數。
    """
    active_count = len(actives)
    if active_count <= keep_n:
        return 0
    ranked = _score_and_rank(actives, summaries)  # 高分在前
    need_freeze = active_count - keep_n
    # 由低分開始凍
    victims = []
    for score, tpl in ranked[::-1]:
        if len(victims) >= need_freeze:
            break
        if _is_locked(tpl):
            continue
        s = summaries.get(int(tpl["template_id"]), {}) or {}
        if int(s.get("n_trades") or 0) < MIN_OBS_N:
            continue
        victims.append(tpl)

    frozen = 0
    for t in victims:
        tid = int(t["template_id"])
        repo.freeze_template(tid)
        frozen += 1
        summ = summaries.get(tid, {}) or {}
        repo.insert_evolution_event(
            action="FREEZE",
            source_template_ids=[tid],
            new_template_id=None,
            notes=f"weekly-cleanup; n={summ.get('n_trades')} mean={summ.get('reward_mean')} var={summ.get('reward_var')}"
        )
        log.info(f"[evolver] CLEANUP freeze template_id={tid}")
    return frozen

def run_weekly() -> Dict[str, Any]:
    """
    每週演化流程（交叉 + 清池）：
    1) 讀取 active 與 summaries，依 bandit 排名選父代
    2) 交叉生成子代，補齊到 TARGET_ACTIVE
    3) 若仍超量或策略過密，做清池（保留 TARGET_ACTIVE）
    """
    actives = repo.get_active_templates()
    summaries = repo.get_all_templates_summary(active_only=True)

    # 擇優父代（與每日一致）
    ranked = _score_and_rank(actives, summaries)
    parents = [t for _, t in ranked if not _is_blacklisted(t)][:TOP_PARENTS]

    active_count = len(actives)
    need = max(0, TARGET_ACTIVE - active_count)

    # 先試交叉補量；不足再用突變補量
    n_cross = _spawn_crossed(parents, how_many=need)
    actives = repo.get_active_templates()
    active_count = len(actives)
    still_need = max(0, TARGET_ACTIVE - active_count)
    n_mut = 0
    if still_need > 0:
        n_mut = _spawn_children(parents, how_many=still_need)

    # 若超量，清池（凍結低分者）
    actives = repo.get_active_templates()
    frozen_clean = _weekly_cleanup(actives, summaries, keep_n=TARGET_ACTIVE)

    result = {
        "crossed": n_cross,
        "mutated": n_mut,
        "frozen_cleanup": frozen_clean,
        "active_after": repo.count_active_templates()
    }
    log.info(f"[evolver.weekly] result={result}")
    return result



def run_once() -> Dict[str, Any]:
    """
    單輪演化流程：
    1) 讀取 active templates 與其績效彙總
    2) 凍結劣質模板
    3) 依 bandit 排名選父代
    4) 生成子代補齊活躍模板數量
    """
    actives = repo.get_active_templates()
    summaries = repo.get_all_templates_summary(active_only=True)
    # 記錄凍結前的活躍清單 & 數量（用於回報與後備父代）
    active_before = len(actives)
    actives_pre = list(actives)

    # 1) 凍結
    n_frozen = _freeze_bad_ones(actives, summaries)

    # 重新取一次活躍清單（因為可能剛凍結了）
    actives = repo.get_active_templates()
    active_count = len(actives)

    # 2) 排名，選父代
    ranked = _score_and_rank(actives, summaries)
    parents = [t for _, t in ranked if not _is_blacklisted(t)][:TOP_PARENTS]

    # 若凍結後沒有任何活躍父代，改用「凍結前的活躍清單」當後備父代（允許從已凍結者衍生新子代）
    if not parents and actives_pre:
        ranked_fallback = _score_and_rank(actives_pre, summaries)
        parents = [t for _, t in ranked_fallback if not _is_blacklisted(t)][:TOP_PARENTS]

    # 若仍沒有父代（例如整池都被凍結或原本就沒有模板），自動補兩個 baseline 種子
    if not parents:
        try:
            repo.seed_templates([
                {"version": 1, "side": "LONG",  "rsi_bin": None, "macd_bin": None,
                    "kd_bin": None, "vol_bin": None, "extra": {"note": "auto-baseline long"}},
                {"version": 1, "side": "SHORT", "rsi_bin": None, "macd_bin": None,
                    "kd_bin": None, "vol_bin": None, "extra": {"note": "auto-baseline short"}},
            ])
            actives = repo.get_active_templates()
            ranked = _score_and_rank(actives, summaries)
            parents = [t for _, t in ranked if not _is_blacklisted(t)][:TOP_PARENTS]
        except Exception as _e:
            log.exception("[evolver] baseline seeding failed: %s", _e)

    # 3) 補齊
    need = max(0, TARGET_ACTIVE - active_count)
    n_spawn = _spawn_children(parents, how_many=need)

    result = {
        "active_before": active_before,
        "froze": n_frozen,
        "spawned": n_spawn,
        "active_after": repo.count_active_templates()
    }

    log.info(f"[evolver] result={result}")
    return result


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")
    if "--weekly" in sys.argv:
        run_weekly() # pyright: ignore[reportUndefinedVariable]
    else:
        run_once()

    
