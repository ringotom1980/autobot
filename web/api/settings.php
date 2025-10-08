<?php
// web/api/settings.php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

$pdo = require __DIR__ . '/pdo.php';
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

function table_exists(PDO $pdo, string $table): bool
{
    $stmt = $pdo->prepare("SHOW TABLES LIKE :t");
    $stmt->execute([':t' => $table]);
    return (bool)$stmt->fetchColumn();
}

$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET') {
    $stmt = $pdo->query("SELECT * FROM settings WHERE id=1");
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    echo json_encode($row ?: [], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($method === 'POST') {
    $raw = file_get_contents('php://input');
    $j = json_decode($raw, true);
    if (!is_array($j)) $j = [];

    // --- 解析輸入 ---
    $symbols_json     = array_key_exists('symbols_json', $j)      ? json_encode($j['symbols_json'])      : null;
    $intervals_json   = array_key_exists('intervals_json', $j)    ? json_encode($j['intervals_json'])    : null;
    $leverage_json    = array_key_exists('leverage_json', $j)     ? json_encode($j['leverage_json'])     : null;
    $invest_usdt_json = array_key_exists('invest_usdt_json', $j)  ? json_encode($j['invest_usdt_json'])  : null;
    $is_enabled       = array_key_exists('is_enabled', $j)        ? (int)$j['is_enabled']                : null;
    $adv_enabled    = array_key_exists('adv_enabled', $j)    ? (int)$j['adv_enabled']    : null;


    $max_risk_pct       = array_key_exists('max_risk_pct', $j)       ? (float)$j['max_risk_pct']       : null;
    $max_daily_dd_pct   = array_key_exists('max_daily_dd_pct', $j)   ? (float)$j['max_daily_dd_pct']   : null;
    $max_consec_losses  = array_key_exists('max_consec_losses', $j)  ? (int)$j['max_consec_losses']    : null;
    $entry_threshold    = array_key_exists('entry_threshold', $j)    ? (float)$j['entry_threshold']    : null;
    $reverse_gap        = array_key_exists('reverse_gap', $j)        ? (float)$j['reverse_gap']        : null;
    $cooldown_bars      = array_key_exists('cooldown_bars', $j)      ? (int)$j['cooldown_bars']        : null;
    $min_hold_bars      = array_key_exists('min_hold_bars', $j)      ? (int)$j['min_hold_bars']        : null;

    $trade_mode      = array_key_exists('trade_mode', $j)      ? (in_array($j['trade_mode'], ['SIM', 'LIVE']) ? $j['trade_mode'] : 'SIM') : null;
    $live_armed      = array_key_exists('live_armed', $j)      ? (int)$j['live_armed'] : null;
    $fee_rate        = array_key_exists('fee_rate', $j)        ? (float)$j['fee_rate']   : null;
    $slip_rate       = array_key_exists('slip_rate', $j)       ? (float)$j['slip_rate']  : null;

    $exists = (int)$pdo->query("SELECT COUNT(*) FROM settings WHERE id=1")->fetchColumn() > 0;

    try {
        $pdo->beginTransaction();

        if ($exists) {
            // 讀舊 is_enabled（判斷是否 0→1）
            $prev_enabled = (int)$pdo->query("SELECT is_enabled FROM settings WHERE id=1")->fetchColumn();

            // 動態 UPDATE
            $sets = [];
            $params = [];
            if (!is_null($symbols_json)) {
                $sets[] = "symbols_json = :a";
                $params[':a'] = $symbols_json;
            }
            if (!is_null($intervals_json)) {
                $sets[] = "intervals_json = :b";
                $params[':b'] = $intervals_json;
            }
            if (!is_null($leverage_json)) {
                $sets[] = "leverage_json = :c";
                $params[':c'] = $leverage_json;
            }
            if (!is_null($invest_usdt_json)) {
                $sets[] = "invest_usdt_json = :d";
                $params[':d'] = $invest_usdt_json;
            }
            if (!is_null($is_enabled)) {
                $sets[] = "is_enabled = :e";
                $params[':e'] = $is_enabled;
            }

            if (!is_null($adv_enabled)) {
                $sets[] = "adv_enabled = :adv";
                $params[':adv'] = $adv_enabled;
            }


            if (!is_null($max_risk_pct)) {
                $sets[] = "max_risk_pct = :f1";
                $params[':f1'] = $max_risk_pct;
            }
            if (!is_null($max_daily_dd_pct)) {
                $sets[] = "max_daily_dd_pct = :f2";
                $params[':f2'] = $max_daily_dd_pct;
            }
            if (!is_null($max_consec_losses)) {
                $sets[] = "max_consec_losses = :f3";
                $params[':f3'] = $max_consec_losses;
            }
            if (!is_null($entry_threshold)) {
                $sets[] = "entry_threshold = :f4";
                $params[':f4'] = $entry_threshold;
            }
            if (!is_null($reverse_gap)) {
                $sets[] = "reverse_gap = :f5";
                $params[':f5'] = $reverse_gap;
            }
            if (!is_null($cooldown_bars)) {
                $sets[] = "cooldown_bars = :f6";
                $params[':f6'] = $cooldown_bars;
            }
            if (!is_null($min_hold_bars)) {
                $sets[] = "min_hold_bars = :f7";
                $params[':f7'] = $min_hold_bars;
            }

            if (!is_null($trade_mode)) {
                $sets[] = "trade_mode = :tm";
                $params[':tm'] = $trade_mode;
            }
            if (!is_null($live_armed)) {
                $sets[] = "live_armed = :la";
                $params[':la'] = $live_armed;
            }
            if (!is_null($fee_rate)) {
                $sets[] = "fee_rate = :fr";
                $params[':fr'] = $fee_rate;
            }
            if (!is_null($slip_rate)) {
                $sets[] = "slip_rate = :sr";
                $params[':sr'] = $slip_rate;
            }

            if (!empty($sets)) {
                $sql = "UPDATE settings SET " . implode(", ", $sets) . " WHERE id=1";
                $stmt = $pdo->prepare($sql);
                $stmt->execute($params);
            }

            // is_enabled 切換處理
            if (!is_null($is_enabled)) {
                if ($is_enabled === 1) {
                    // 只有 0→1 才清空 job_progress & 新開 session
                    if ($prev_enabled !== 1 && table_exists($pdo, 'job_progress')) {
                        $pdo->exec("TRUNCATE TABLE job_progress");
                        $pdo->prepare("
                            INSERT INTO job_progress(job_id, phase, symbol, `interval`, step, total, pct)
                            VALUES('main:loop','READY','', '', 1, 1, 100)
                            ON DUPLICATE KEY UPDATE phase=VALUES(phase), pct=VALUES(pct), updated_at=CURRENT_TIMESTAMP
                        ")->execute();
                    }
                    // 開啟 session（若沒有 active）
                    $tm = $trade_mode ?? $pdo->query("SELECT trade_mode FROM settings WHERE id=1")->fetchColumn();
                    if ($tm !== 'LIVE' && $tm !== 'SIM') $tm = 'SIM';
                    $active = (int)$pdo->query("SELECT COUNT(*) FROM run_sessions WHERE is_active=1")->fetchColumn();
                    if ($active === 0) {
                        $stmt = $pdo->prepare("INSERT INTO run_sessions(started_at, is_active, trade_mode) VALUES(UNIX_TIMESTAMP()*1000, 1, :tm)");
                        $stmt->execute([':tm' => $tm]);
                        // ★★★ 同步設定目前 session
                        $sid = (int)$pdo->query("SELECT LAST_INSERT_ID()")->fetchColumn();
                        $up  = $pdo->prepare("UPDATE settings SET current_session_id = :sid WHERE id=1");
                        $up->execute([':sid' => $sid]);
                    } else {
                        // ★★★ 已有 active：把 current_session_id 指向它（避免不同步）
                        $sid = (int)$pdo->query("SELECT session_id FROM run_sessions WHERE is_active=1 ORDER BY started_at DESC LIMIT 1")->fetchColumn();
                        $up  = $pdo->prepare("UPDATE settings SET current_session_id = :sid WHERE id=1");
                        $up->execute([':sid' => $sid]);
                    }
                } else {
                    // 關閉：結束所有 active session
                    $pdo->exec("UPDATE run_sessions SET stopped_at=UNIX_TIMESTAMP()*1000, is_active=0 WHERE is_active=1");
                    // ★★★ 清掉 current_session_id，避免前端/後端認知不一致
                    $pdo->exec("UPDATE settings SET current_session_id=NULL WHERE id=1");
                }
            }

            $pdo->commit();
            echo json_encode(['ok' => 1], JSON_UNESCAPED_UNICODE);
            exit;
        } else {
            // 初次插入
            $stmt = $pdo->prepare("
                INSERT INTO settings(
                  id, symbols_json, intervals_json, leverage_json, invest_usdt_json, is_enabled,
                  max_risk_pct, max_daily_dd_pct, max_consec_losses, entry_threshold, reverse_gap, cooldown_bars, min_hold_bars, adv_enabled,
                  trade_mode, live_armed, fee_rate, slip_rate
                ) VALUES (
                  1, :a, :b, :c, :d, :e,
                  :f1, :f2, :f3, :f4, :f5, :f6, :f7, :adv,
                  :tm, :la, :fr, :sr
                )
            ");
            $stmt->execute([
                ':a' => $symbols_json     ?? json_encode(["BTCUSDT"]),
                ':b' => $intervals_json   ?? json_encode(["1m"]),
                ':c' => $leverage_json    ?? json_encode(new stdClass()),
                ':d' => $invest_usdt_json ?? json_encode(new stdClass()),
                ':e' => $is_enabled       ?? 1,
                ':f1' => $max_risk_pct       ?? 0.01,
                ':f2' => $max_daily_dd_pct   ?? 0.03,
                ':f3' => $max_consec_losses  ?? 4,
                ':f4' => $entry_threshold    ?? 0.3,
                ':f5' => $reverse_gap        ?? 0.2,
                ':f6' => $cooldown_bars      ?? 2,
                ':f7' => $min_hold_bars      ?? 2,
                ':adv' => $adv_enabled       ?? 0,
                ':tm' => $trade_mode         ?? 'SIM',
                ':la' => $live_armed         ?? 0,
                ':fr' => $fee_rate           ?? 0.0004,
                ':sr' => $slip_rate          ?? 0.0005,
            ]);

            // 初次且 is_enabled=1：清一次 job_progress 並開 session
            if ((int)($is_enabled ?? 1) === 1 && table_exists($pdo, 'job_progress')) {
                $pdo->exec("TRUNCATE TABLE job_progress");
                $pdo->prepare("
                    INSERT INTO job_progress(job_id, phase, symbol, `interval`, step, total, pct)
                    VALUES('main:loop','READY','', '', 1, 1, 100)
                    ON DUPLICATE KEY UPDATE phase=VALUES(phase), pct=VALUES(pct), updated_at=CURRENT_TIMESTAMP
                ")->execute();

                $tm = $trade_mode ?? 'SIM';
                $stmt = $pdo->prepare("INSERT INTO run_sessions(started_at, is_active, trade_mode) VALUES(UNIX_TIMESTAMP()*1000, 1, :tm)");
                $stmt->execute([':tm' => $tm]);
            }

            $pdo->commit();
            echo json_encode(['ok' => 1, 'inserted' => true], JSON_UNESCAPED_UNICODE);
            exit;
        }
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        http_response_code(500);
        echo json_encode(['error' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
        exit;
    }
}

http_response_code(405);
echo json_encode(['error' => 'Method Not Allowed'], JSON_UNESCAPED_UNICODE);
