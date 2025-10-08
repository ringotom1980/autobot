<?php
// web/api/exchange_info.php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

// ---- 設定 ----
$BINANCE_URL = 'https://fapi.binance.com/fapi/v1/exchangeInfo';
$CACHE_DIR   = __DIR__ . '/_cache';
$CACHE_FILE  = $CACHE_DIR . '/exinfo.json';
$CACHE_TTL_S = 300; // 5 分鐘
$FALLBACK_INTERVALS = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d"];

// 建快取資料夾
if (!is_dir($CACHE_DIR)) {
  @mkdir($CACHE_DIR, 0755, true);
}

// 讀快取（若未過期）
$now = time();
if (is_file($CACHE_FILE) && ($now - filemtime($CACHE_FILE) <= $CACHE_TTL_S)) {
  $j = json_decode((string)@file_get_contents($CACHE_FILE), true);
  if (is_array($j) && !empty($j['symbols'])) {
    echo json_encode(['ok'=>1, 'symbols'=>$j['symbols'], 'intervals'=>$j['intervals'] ?? $FALLBACK_INTERVALS], JSON_UNESCAPED_UNICODE);
    exit;
  }
}

// 嘗試抓 Binance（2 秒逾時，避免 502）
$symbols = [];
$intervals = $FALLBACK_INTERVALS;
$err = null;

try {
  // 優先用 cURL（多數主機可用）；失敗再退回 file_get_contents
  if (function_exists('curl_init')) {
    $ch = curl_init();
    curl_setopt_array($ch, [
      CURLOPT_URL => $BINANCE_URL,
      CURLOPT_RETURNTRANSFER => true,
      CURLOPT_CONNECTTIMEOUT => 2,
      CURLOPT_TIMEOUT => 2,
      CURLOPT_USERAGENT => 'autobot-exinfo/1.0',
      CURLOPT_HTTPHEADER => ['Accept: application/json'],
    ]);
    $resp = curl_exec($ch);
    if ($resp === false) {
      $err = 'curl: ' . curl_error($ch);
    } else {
      $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
      if ($code >= 200 && $code < 300) {
        $data = json_decode($resp, true);
        if (isset($data['symbols']) && is_array($data['symbols'])) {
          // 只取有 USDT 的交易對，狀態為 TRADING
          foreach ($data['symbols'] as $s) {
            if (!empty($s['symbol']) && str_ends_with($s['symbol'], 'USDT') && ($s['status'] ?? '') === 'TRADING') {
              $symbols[] = $s['symbol'];
            }
          }
          // 期貨的 interval 固定，但若日後需要可從 /fapi/v1/exchangeInfo 解析 filters
          sort($symbols);
        } else {
          $err = 'bad-json';
        }
      } else {
        $err = 'http-'.$code;
      }
    }
    curl_close($ch);
  } else {
    // 部分主機禁 curl：用簡單法，並設定短逾時
    $ctx = stream_context_create([
      'http' => ['method'=>'GET','timeout'=>2,'header'=>"Accept: application/json\r\n", 'user_agent'=>'autobot-exinfo/1.0']
    ]);
    $resp = @file_get_contents($BINANCE_URL, false, $ctx);
    if ($resp === false) {
      $err = 'fgc-fail';
    } else {
      $data = json_decode($resp, true);
      if (isset($data['symbols']) && is_array($data['symbols'])) {
        foreach ($data['symbols'] as $s) {
          if (!empty($s['symbol']) && str_ends_with($s['symbol'], 'USDT') && ($s['status'] ?? '') === 'TRADING') {
            $symbols[] = $s['symbol'];
          }
        }
        sort($symbols);
      } else {
        $err = 'bad-json';
      }
    }
  }
} catch (Throwable $e) {
  $err = 'ex:'.$e->getMessage();
}

// 若抓不到 → 用舊快取；再不行 → 最小退回
if (!$symbols) {
  if (is_file($CACHE_FILE)) {
    $j = json_decode((string)@file_get_contents($CACHE_FILE), true);
    if (is_array($j) && !empty($j['symbols'])) {
      echo json_encode(['ok'=>1, 'symbols'=>$j['symbols'], 'intervals'=>$j['intervals'] ?? $FALLBACK_INTERVALS, 'cache'=>1], JSON_UNESCAPED_UNICODE);
      exit;
    }
  }
  // 最小退回，避免前端壞掉
  echo json_encode(['ok'=>1, 'symbols'=>['BTCUSDT','ETHUSDT'], 'intervals'=>$FALLBACK_INTERVALS, 'fallback'=>1, 'err'=>$err], JSON_UNESCAPED_UNICODE);
  exit;
}

// 成功 → 寫快取
@file_put_contents($CACHE_FILE, json_encode(['symbols'=>$symbols, 'intervals'=>$intervals], JSON_UNESCAPED_UNICODE));

// 回傳
echo json_encode(['ok'=>1, 'symbols'=>$symbols, 'intervals'=>$intervals], JSON_UNESCAPED_UNICODE);
