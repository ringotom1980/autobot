<?php
// web/api/cron_cleanup.php
declare(strict_types=1);

// === 安全認證 ===
const CRON_TOKEN = 'ACPaTcdHx2c2RtNOs9BmFxpyRMEdg4HjXhFHmzSYv9Ie8';

$token = $_GET['token'] ?? ($_SERVER['CRON_TOKEN'] ?? '');
if ($token !== CRON_TOKEN) {
  http_response_code(403);
  header('Content-Type: text/plain; charset=utf-8');
  echo "forbidden\n";
  exit;
}

header('Content-Type: text/plain; charset=utf-8');

$pdo = require __DIR__ . '/pdo.php';
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

// === 支援多張表的設定 ===
$TABLES = [
  'decisions_log' => ['days' => 365],
  'risk_journal'  => ['days' => 180],
  // 未來要加新的清理表只要照這樣新增
  // 'trades_log'   => ['days' => 400],
];

// 可指定要跑哪張表（?table=decisions_log），預設全部都跑
$target = $_GET['table'] ?? 'ALL';

// === 共用參數 ===
$batch     = (int)($_GET['batch'] ?? 5000);
$maxRounds = (int)($_GET['rounds'] ?? 120);
$dryRun    = isset($_GET['dry']) && $_GET['dry'] == '1';

foreach ($TABLES as $table => $conf) {
  if ($target !== 'ALL' && $target !== $table) continue;
  
  $days = (int)($conf['days'] ?? 365);
  $cutoffStmt = $pdo->query("SELECT UNIX_TIMESTAMP(DATE_SUB(NOW(), INTERVAL {$days} DAY))*1000 AS c");
  $cutoffRow  = $cutoffStmt->fetch(PDO::FETCH_ASSOC);
  $cutoffMs   = (int)($cutoffRow['c'] ?? 0);

  if ($dryRun) {
    $cntStmt = $pdo->prepare("SELECT COUNT(*) FROM {$table} WHERE ts < :c");
    $cntStmt->execute([':c' => $cutoffMs]);
    $cnt = (int)$cntStmt->fetchColumn();
    echo "[DRY] {$table}: cutoff_ms={$cutoffMs} to_delete={$cnt}\n";
    continue;
  }

  $total = 0;
  $round = 0;
  do {
    $stmt = $pdo->prepare("DELETE FROM {$table} WHERE ts < :c LIMIT {$batch}");
    $stmt->execute([':c' => $cutoffMs]);
    $affected = (int)$stmt->rowCount();
    $total += $affected;
    $round++;
    if ($affected === $batch) usleep(100000);
  } while ($affected === $batch && $round < $maxRounds);

  echo "[cleanup] {$table}: cutoff_ms={$cutoffMs} deleted={$total} rounds={$round}\n";
}
