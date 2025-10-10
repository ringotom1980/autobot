<?php
// api/trades.php
header('Content-Type: application/json; charset=utf-8');

try {
    /** @var PDO $pdo */
    $pdo = require __DIR__ . '/pdo.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    // 讀目前 session_id（只顯示目前在跑的 session）
    $sid = null;
    $stmtSid = $pdo->query("SELECT current_session_id FROM settings WHERE id=1");
    $sid = $stmtSid ? $stmtSid->fetchColumn() : null;

    if ($sid === null || $sid === '') {
        // 後備：如果 settings 還沒寫，抓 trades_log 裡最新的 session_id
        $stmtSid2 = $pdo->query("SELECT session_id FROM trades_log ORDER BY id DESC LIMIT 1");
        $sid = $stmtSid2 ? $stmtSid2->fetchColumn() : null;
    }

    // 參數
    $symbol    = isset($_GET['symbol'])   ? trim($_GET['symbol'])   : '';
    $interval  = isset($_GET['interval']) ? trim($_GET['interval']) : '';
    $mode      = isset($_GET['mode'])     ? trim($_GET['mode'])     : 'recent';

    // 需求 #3：近5筆；顯示更多改為 10 筆/頁
    $limit     = isset($_GET['limit'])     ? max(1, intval($_GET['limit'])) : 5;
    $page      = isset($_GET['page'])      ? max(1, intval($_GET['page']))  : 1;
    $pageSize  = isset($_GET['page_size']) ? max(1, intval($_GET['page_size'])) : 10;

    // where 子句
    $where = [];
    $args = [];

    if ($sid !== null && $sid !== '') {
        $where[] = 'session_id = :sid';
        $args[':sid'] = $sid;
    }

    if ($symbol !== '') {
        $where[] = 'symbol = :s';
        $args[':s'] = $symbol;
    }
    if ($interval !== '') {
        $where[] = '`interval` = :i';
        $args[':i'] = $interval;
    }
    $whereSql = $where ? ('WHERE ' . implode(' AND ', $where)) : '';

    // 欄位（若你有 direction 欄，改成 direction；這裡用 qty 正負判斷）
    $cols = "
      entry_ts, exit_ts, entry_price, exit_price, template_id, pnl_after_cost,
      CASE WHEN qty >= 0 THEN 'LONG' ELSE 'SHORT' END AS side
    ";

    if ($mode === 'recent') {
        $sql = "SELECT $cols
                  FROM trades_log
                  $whereSql
                 ORDER BY COALESCE(exit_ts, entry_ts) DESC
                 LIMIT :lim";
        $stmt = $pdo->prepare($sql);
        foreach ($args as $k => $v) $stmt->bindValue($k, $v);
        $stmt->bindValue(':lim', $limit, PDO::PARAM_INT);
        $stmt->execute();
        $rows = $stmt->fetchAll();
        echo json_encode(['rows' => $rows], JSON_UNESCAPED_UNICODE);
        exit;
    }

    if ($mode === 'now') {
        // 基本條件
        $where = [];
        $args  = [];

        if ($sid !== null && $sid !== '') {
            $where[] = 'session_id = :sid';
            $args[':sid'] = $sid;
        }
        if ($symbol !== '') {
            $where[] = 'symbol = :s';
            $args[':s'] = $symbol;
        }
        if ($interval !== '') {
            $where[] = '`interval` = :i';
            $args[':i'] = $interval;
        }
        $whereSql = $where ? ('WHERE ' . implode(' AND ', $where)) : '';

        // 1) 最新價格（時間用 close_time）
        $stmtPx = $pdo->prepare("SELECT close_time, close FROM candles WHERE symbol=:s AND `interval`=:i ORDER BY close_time DESC LIMIT 1");
        $stmtPx->execute([':s' => $symbol, ':i' => $interval]);
        $rowPx = $stmtPx->fetch(PDO::FETCH_ASSOC);
        $lastTs   = $rowPx ? (int)$rowPx['close_time'] : null;
        $lastPx   = $rowPx ? (float)$rowPx['close']      : null;

        // 2) 最新決策（本 session）
        $sqlDec = "SELECT action, ts FROM decisions_log $whereSql ORDER BY ts DESC LIMIT 1";
        $stmtDec = $pdo->prepare($sqlDec);
        foreach ($args as $k => $v) $stmtDec->bindValue($k, $v);
        $stmtDec->execute();
        $rowDec = $stmtDec->fetch(PDO::FETCH_ASSOC);
        $action = $rowDec ? strtoupper($rowDec['action']) : 'HOLD';
        if ($rowDec && $rowDec['ts']) {
            $lastTs = max($lastTs ?? 0, (int)$rowDec['ts']);
        }

        // 3) 是否持倉（同 symbol / interval）
        $stmtPos = $pdo->prepare("SELECT direction, entry_price, qty, opened_at FROM positions WHERE symbol=:s AND `interval`=:i AND status='OPEN' ORDER BY opened_at DESC LIMIT 1");
        $stmtPos->execute([':s' => $symbol, ':i' => $interval]);
        $pos = $stmtPos->fetch(PDO::FETCH_ASSOC);

        $holding = $pos ? 1 : 0;
        $entry   = $pos ? (float)$pos['entry_price'] : null;
        $last    = $lastPx;

        // 4) 預估 PnL（不扣成本）：(last - entry) * qty_signed
        $est = null;
        if ($pos && $last !== null) {
            $dir = strtoupper($pos['direction']);
            $qty = (float)$pos['qty'];
            $qtySigned = ($dir === 'LONG') ? $qty : -$qty;
            $est = ($last - $entry) * $qtySigned;
        }

        echo json_encode([
            'ts'          => $lastTs,
            'action'      => $action,           // LONG / SHORT / HOLD
            'holding'     => $holding,          // 1/0
            'entry_price' => $entry,            // null when not holding
            'last_price'  => $last,             // may be null if無K線
            'est_pnl'     => $est               // null when not holding
        ], JSON_UNESCAPED_UNICODE);
        exit;
    }


    // all + pagination（10 筆/頁）
    $countSql = "SELECT COUNT(*) AS c FROM trades_log $whereSql";
    $stmtC = $pdo->prepare($countSql);
    foreach ($args as $k => $v) $stmtC->bindValue($k, $v);
    $stmtC->execute();
    $total = (int)$stmtC->fetchColumn();

    $offset = ($page - 1) * $pageSize;
    $sql = "SELECT $cols
              FROM trades_log
              $whereSql
             ORDER BY COALESCE(exit_ts, entry_ts) DESC
             LIMIT :lim OFFSET :off";
    $stmt = $pdo->prepare($sql);
    foreach ($args as $k => $v) $stmt->bindValue($k, $v);
    $stmt->bindValue(':lim', $pageSize, PDO::PARAM_INT);
    $stmt->bindValue(':off', $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();

    echo json_encode([
        'rows'  => $rows,
        'total' => $total,
        'page'  => $page,
        'page_size' => $pageSize
    ], JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()]);
}
