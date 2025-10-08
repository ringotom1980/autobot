<?php
// web/api/pdo.php
declare(strict_types=1);

/**
 * 優先用環境變數；沒有就使用你目前實際的 DB 參數。
 * 若 Hostinger/cPanel 沒有設環境變數，這份預設即可工作。
 */
$DB_HOST    = getenv('DB_HOST')    ?: '127.0.0.1';
$DB_PORT    = getenv('DB_PORT')    ?: '3306';
$DB_NAME    = getenv('DB_NAME')    ?: 'u327657097_autobot_db'; // ← 你的實際 DB 名稱
$DB_USER    = getenv('DB_USER')    ?: 'u327657097_autobot_admin'; // 建議建立一個可讀寫的專用帳號
$DB_PASS    = getenv('DB_PASS')    ?: '1qaz@WSX3edc//';                       // 記得填上密碼
$DB_CHARSET = getenv('DB_CHARSET') ?: 'utf8mb4';

$dsn = sprintf('mysql:host=%s;port=%s;dbname=%s;charset=%s', $DB_HOST, $DB_PORT, $DB_NAME, $DB_CHARSET);

try {
    $pdo = new PDO($dsn, $DB_USER, $DB_PASS, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        // PDO::ATTR_EMULATE_PREPARES => false, // 如有需要可打開
    ]);
    return $pdo;
} catch (Throwable $e) {
    // 不要 echo 內容，讓上層 API 捕捉並回傳 JSON
    error_log('[pdo.php] DB connect failed: '.$e->getMessage());
    throw $e;
}
