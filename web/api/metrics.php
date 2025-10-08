<?php
// web/api/metrics.php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

$pdo = require __DIR__ . '/pdo.php';
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

function fetch_one(PDO $pdo, string $sql, array $params = [])
{
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    return $stmt->fetch(PDO::FETCH_ASSOC) ?: null;
}
function fetch_scalar(PDO $pdo, string $sql, array $params = [])
{
    $row = fetch_one($pdo, $sql, $params);
    if (!$row) return null;
    return reset($row);
}
function fetch_val(PDO $pdo, string $sql, array $params = [], $default = 0)
{
    $v = fetch_scalar($pdo, $sql, $params);
    return is_null($v) ? $default : (0 + $v);
}
function table_exists(PDO $pdo, string $table): bool
{
    $stmt = $pdo->prepare("SHOW TABLES LIKE :t");
    $stmt->execute([':t' => $table]);
    return (bool)$stmt->fetchColumn();
}
function column_exists(PDO $pdo, string $table, string $column): bool
{
    $stmt = $pdo->prepare("SHOW COLUMNS FROM `$table` LIKE :c");
    try {
        $stmt->execute([':c' => $column]);
        return (bool)$stmt->fetchColumn();
    } catch (Throwable $e) {
        return false;
    }
}

try {
    // ---- 存在性檢查 ----
    $has_settings     = table_exists($pdo, 'settings');
    $has_sessions     = table_exists($pdo, 'run_sessions');
    $has_trades       = table_exists($pdo, 'trades_log');
    $has_decisions    = table_exists($pdo, 'decisions_log');
    $has_positions    = table_exists($pdo, 'positions'); // 用來推算 is_flat
    $has_job_progress = table_exists($pdo, 'job_progress');
    $has_evo_events  = table_exists($pdo, 'evolution_events');
    $has_templates   = table_exists($pdo, 'templates');



    $has_is_flat_col  = $has_decisions ? column_exists($pdo, 'decisions_log', 'is_flat') : false;

    // 1) 啟動狀態
    $is_enabled = $has_settings ? (int)fetch_val($pdo, "SELECT is_enabled FROM settings WHERE id=1 LIMIT 1", [], 0) : 0;
    // ★ 以 settings.current_session_id 優先
    $cur_sid = $has_settings ? fetch_scalar($pdo, "SELECT current_session_id FROM settings WHERE id=1 LIMIT 1") : null;


    // 2) Session 範圍（活躍優先）
    $session_id = null;
    $sess_start = null;
    $sess_end = null;
    if ($has_sessions) {
        $sess = fetch_one(
            $pdo,
            "SELECT session_id, started_at, stopped_at, is_active
       FROM run_sessions
       ORDER BY is_active DESC, started_at DESC
       LIMIT 1"
        );
        if ($sess) {
            $session_id = $sess['session_id'] ?? null;
            $sess_start = isset($sess['started_at']) ? (int)$sess['started_at'] : null;
            $sess_end = ((int)($sess['is_active'] ?? 0) === 1)
                ? (int)round(microtime(true) * 1000)
                : (isset($sess['stopped_at']) ? (int)$sess['stopped_at'] : (int)round(microtime(true) * 1000));
        }
    }

    // ★ 覆蓋 session 範圍：優先使用 settings.current_session_id（若存在）
    if (!empty($cur_sid)) {
        $s = fetch_one(
            $pdo,
            "SELECT session_id, started_at, stopped_at, is_active
           FROM run_sessions
          WHERE session_id = :sid
          LIMIT 1",
            [':sid' => $cur_sid]
        );
        if ($s) {
            $session_id = (int)$s['session_id'];
            $sess_start = isset($s['started_at']) ? (int)$s['started_at'] : null;
            $sess_end   = ((int)($s['is_active'] ?? 0) === 1)
                ? (int)round(microtime(true) * 1000)
                : (isset($s['stopped_at']) ? (int)$s['stopped_at'] : (int)round(microtime(true) * 1000));
        }
    }


    // 3) 三卡計數
    $long_cnt = 0;
    $short_cnt = 0;
    $hold_cnt = 0;
    if ($session_id && $sess_start && $sess_end) {
        if ($has_trades) {
            $long_cnt  = (int)fetch_val(
                $pdo,
                "SELECT COUNT(*) FROM trades_log
         WHERE exit_ts >= :a AND exit_ts <= :b AND qty > 0",
                [':a' => $sess_start, ':b' => $sess_end],
                0
            );
            // ★ 以 session_id 為主（覆蓋時間窗）
            $long_cnt = (int)fetch_val(
                $pdo,
                "SELECT COUNT(*) FROM trades_log WHERE session_id = :sid AND qty > 0",
                [':sid' => $session_id],
                0
            );

            $short_cnt = (int)fetch_val(
                $pdo,
                "SELECT COUNT(*) FROM trades_log
         WHERE exit_ts >= :a AND exit_ts <= :b AND qty < 0",
                [':a' => $sess_start, ':b' => $sess_end],
                0
            );
            // ★ 以 session_id 為主（覆蓋時間窗）
            $short_cnt = (int)fetch_val(
                $pdo,
                "SELECT COUNT(*) FROM trades_log WHERE session_id = :sid AND qty < 0",
                [':sid' => $session_id],
                0
            );
        }

        if ($has_decisions) {
            if ($has_is_flat_col) {
                // 你若之後在 decisions_log 補了 is_flat，就會走這條最便宜
                $hold_cnt = (int)fetch_val(
                    $pdo,
                    "SELECT COUNT(*) FROM decisions_log
           WHERE session_id = :sid AND ts >= :a AND ts <= :b
             AND action = 'HOLD' AND is_flat = 1",
                    [':sid' => $session_id, ':a' => $sess_start, ':b' => $sess_end],
                    0
                );
            } elseif ($has_positions) {
                // 沒有 is_flat 欄位 → 用 positions 推論「當下無持倉」
                $hold_cnt = (int)fetch_val(
                    $pdo,
                    "SELECT COUNT(*) FROM decisions_log d
           WHERE d.session_id = :sid AND d.ts >= :a AND d.ts <= :b
             AND d.action = 'HOLD'
             AND NOT EXISTS (
               SELECT 1 FROM positions p
               WHERE p.symbol = d.symbol
                 AND (p.`interval` = d.`interval` OR p.`interval` IS NULL)
                 AND p.opened_at <= d.ts
                 AND (p.closed_at IS NULL OR p.closed_at >= d.ts)
             )",
                    [':sid' => $session_id, ':a' => $sess_start, ':b' => $sess_end],
                    0
                );
            } else {
                // 既沒有 is_flat 也沒有 positions → 退而求其次：全部 HOLD 都算（可能偏高）
                $hold_cnt = (int)fetch_val(
                    $pdo,
                    "SELECT COUNT(*) FROM decisions_log
           WHERE session_id = :sid AND ts >= :a AND ts <= :b
             AND action = 'HOLD'",
                    [':sid' => $session_id, ':a' => $sess_start, ':b' => $sess_end],
                    0
                );
            }
        }
    }

    // 4) PnL 匯總（今日 / 7 日）
    $today_0 = (new DateTime('today'))->getTimestamp() * 1000;
    $now_ms  = (int)round(microtime(true) * 1000);
    $d7_ago  = $now_ms - 7 * 24 * 60 * 60 * 1000;

    $pnl_today = 0.0;
    $pnl_7d = 0.0;
    if ($has_trades) {
        $pnl_today = (float)fetch_val(
            $pdo,
            "SELECT SUM(pnl_after_cost) FROM trades_log WHERE exit_ts >= :t0",
            [':t0' => $today_0],
            0.0
        );
        $pnl_7d = (float)fetch_val(
            $pdo,
            "SELECT SUM(pnl_after_cost) FROM trades_log WHERE exit_ts >= :t7",
            [':t7' => $d7_ago],
            0.0
        );
        // ★ 本次 session 的 PnL（只看目前 session_id）
        $pnl_session = 0.0;
        if ($has_trades && !empty($session_id)) {
            $pnl_session = (float)fetch_val(
                $pdo,
                "SELECT SUM(pnl_after_cost) FROM trades_log WHERE session_id = :sid",
                [':sid' => $session_id],
                0.0
            );
        }
    }

    // 5) 任務進度（job_progress）— 只看當前 settings 的 symbols/intervals
    $progress = null;
    if (table_exists($pdo, 'job_progress')) {
        $cfg = fetch_one($pdo, "SELECT symbols_json, intervals_json FROM settings WHERE id=1");
        $symbols = $cfg && !empty($cfg['symbols_json']) ? json_decode($cfg['symbols_json'], true) : [];
        $intervals = $cfg && !empty($cfg['intervals_json']) ? json_decode($cfg['intervals_json'], true) : [];

        if (!empty($symbols) && !empty($intervals)) {
            $inSyms = "'" . implode("','", array_map('addslashes', $symbols)) . "'";
            $inInts = "'" . implode("','", array_map('addslashes', $intervals)) . "'";
            $row = fetch_one($pdo, "
      SELECT job_id, phase, step, total, pct
      FROM job_progress
      WHERE (symbol IN ($inSyms) AND `interval` IN ($inInts))
         OR job_id IN ('main:idle','main:loop','ssh_tunnel')
      ORDER BY updated_at DESC
      LIMIT 1
    ");
        } else {
            $row = fetch_one($pdo, "
      SELECT job_id, phase, step, total, pct
      FROM job_progress
      ORDER BY updated_at DESC
      LIMIT 1
    ");
        }

        if ($row) {
            $progress = [
                'job_id' => $row['job_id'],
                'phase'  => $row['phase'],
                'step'   => (int)$row['step'],
                'total'  => (int)$row['total'],
                'pct'    => (float)$row['pct'],
            ];
        }
    }

    // 6) Evolution metrics（近7天 / 池狀態 / 最近20筆事件）
    $evolution = null;
    if ($has_evo_events) {
        $evo7 = $pdo->query("
            SELECT FROM_UNIXTIME(ts/1000, '%Y-%m-%d') AS d,
                   SUM(action='MUTATE') AS n_mutate,
                   SUM(action='CROSS')  AS n_cross,
                   SUM(action='FREEZE') AS n_freeze
              FROM evolution_events
             WHERE ts >= (UNIX_TIMESTAMP(CURRENT_DATE - INTERVAL 6 DAY) * 1000)
             GROUP BY d
             ORDER BY d
        ")->fetchAll(PDO::FETCH_ASSOC);

        $pool = [];
        if ($has_templates) {
            $pool = $pdo->query("
                SELECT status, COUNT(*) AS c FROM templates GROUP BY status
            ")->fetchAll(PDO::FETCH_ASSOC);
        }

        $recent = $pdo->query("
            SELECT event_id,
                   FROM_UNIXTIME(ts/1000) AS ts_time,
                   action, source_template_ids, new_template_id, notes
              FROM evolution_events
             ORDER BY event_id DESC
             LIMIT 20
        ")->fetchAll(PDO::FETCH_ASSOC);

        $evolution = [
            'by_day_7d' => $evo7,
            'pool'      => $pool,
            'recent'    => $recent,
        ];
    }



    echo json_encode([
        'is_enabled'  => $is_enabled,
        'session_id'  => $session_id,
        'pnl_today'   => round($pnl_today, 8),
        'pnl_7d'      => round($pnl_7d, 8),
        'pnl_session' => round($pnl_session, 8),
        'progress'    => $progress,
        'stats'       => ['long' => $long_cnt, 'short' => $short_cnt, 'hold' => $hold_cnt],
        'evolution'   => $evolution,
    ], JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
}
