<?php
// web/api/health.php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
$pdo = require __DIR__ . '/pdo.php';
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

function fetchAll(PDO $pdo, string $sql, array $p=[]){ $st=$pdo->prepare($sql); $st->execute($p); return $st->fetchAll(PDO::FETCH_ASSOC); }
function fetchOne(PDO $pdo, string $sql, array $p=[]){ $st=$pdo->prepare($sql); $st->execute($p); return $st->fetch(PDO::FETCH_ASSOC) ?: null; }

try {
  $cfg = fetchOne($pdo, "SELECT symbols_json, intervals_json FROM settings WHERE id=1");
  $symbols = $cfg && !empty($cfg['symbols_json']) ? json_decode($cfg['symbols_json'], true) : [];
  $intervals = $cfg && !empty($cfg['intervals_json']) ? json_decode($cfg['intervals_json'], true) : [];

  $jobs = [];
  if (!empty($symbols) && !empty($intervals)) {
    $inSyms = "'" . implode("','", array_map('addslashes', $symbols)) . "'";
    $inInts = "'" . implode("','", array_map('addslashes', $intervals)) . "'";
    $rows = fetchAll($pdo, "
      SELECT job_id, phase, symbol, `interval`, pct, UNIX_TIMESTAMP(updated_at)*1000 AS upd_ms
      FROM job_progress
      WHERE (symbol IN ($inSyms) AND `interval` IN ($inInts))
         OR job_id IN ('main:idle','main:loop','ssh_tunnel')
      ORDER BY updated_at DESC
    ");
  } else {
    $rows = fetchAll($pdo, "
      SELECT job_id, phase, symbol, `interval`, pct, UNIX_TIMESTAMP(updated_at)*1000 AS upd_ms
      FROM job_progress
      ORDER BY updated_at DESC
    ");
  }

  $now = (int) round(microtime(true)*1000);
  $seen = [];
  foreach ($rows as $r) {
    $jid = $r['job_id'];
    if (isset($seen[$jid])) continue; // 只取最新一筆
    $seen[$jid] = true;

    // 最近 15 分鐘內的錯誤統計（用 risk_journal）
    $err = fetchOne($pdo, "
      SELECT MAX(ts) AS last_err, COUNT(*) AS cnt
      FROM risk_journal
      WHERE rule = :rule AND level IN ('WARN','CRIT')
        AND ts >= UNIX_TIMESTAMP()*1000 - 15*60*1000
    ", [':rule'=>"JOB:$jid"]);
    $err_cnt = (int)($err['cnt'] ?? 0);

    $stale = ($now - (int)$r['upd_ms']) > 300*1000; // >5分鐘沒更新 → STALE
    $ok = ($r['phase'] === 'OK') && !$stale && ($err_cnt < 3);

    $jobs[] = [
      'job' => $jid,
      'ok' => $ok,
      'phase' => $r['phase'],
      'symbol' => $r['symbol'],
      'interval' => $r['interval'],
      'pct' => (float)$r['pct'],
      'last_ok_at' => (int)$r['upd_ms'],
      'err_count_window' => $err_cnt,
      'message' => $ok ? 'OK' : ($stale ? 'STALE' : $r['phase']),
    ];
  }

  echo json_encode(['jobs'=>$jobs], JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
  http_response_code(500);
  echo json_encode(['error'=>$e->getMessage()], JSON_UNESCAPED_UNICODE);
}
