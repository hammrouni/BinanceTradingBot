<?php
/**
 * BinanceTradingBot — Agent Service Entry Point
 *
 * REST API exposing AI trading advisor endpoints.
 * Consumes market data from the Python bot (port 8000) and returns
 * LLM-powered trading signals, risk assessments, and market analysis.
 */

ini_set('display_errors', '0');
ini_set('log_errors', '1');

register_shutdown_function(function () {
    $err = error_get_last();
    if ($err && in_array($err['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR], true)) {
        if (!headers_sent()) {
            header('Content-Type: application/json');
            http_response_code(500);
        }
        if (ob_get_level() > 0) {
            ob_end_clean();
        }
        echo json_encode([
            'error' => 'PHP fatal error: ' . $err['message'],
            'file'  => $err['file'],
            'line'  => $err['line'],
        ]);
    }
});

require_once __DIR__ . '/../vendor/autoload.php';

// Load .env (Docker env vars take precedence)
function loadEnvFile(string $path): void
{
    if (!file_exists($path)) {
        return;
    }
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if (empty($line) || str_starts_with($line, '#') || !str_contains($line, '=')) {
            continue;
        }
        [$key, $value] = explode('=', $line, 2);
        $key   = trim($key);
        $value = trim(explode('#', trim($value), 2)[0]);
        if (preg_match('/^["\'](.*)["\']$/', $value, $m)) {
            $value = $m[1];
        }
        if (!getenv($key)) {
            putenv("$key=$value");
            $_ENV[$key] = $value;
        }
    }
}

$envPath = file_exists(__DIR__ . '/../.env')
    ? __DIR__ . '/../.env'
    : (file_exists(__DIR__ . '/.env') ? __DIR__ . '/.env' : null);
if ($envPath) {
    loadEnvFile($envPath);
}

use App\Agents\TradingAdvisorAgent;

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$config = include __DIR__ . '/../config.php';
$uri    = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$method = $_SERVER['REQUEST_METHOD'];

// ── Health ─────────────────────────────────────────────────────────────────
if (in_array($uri, ['/', '/api/health', '/health'], true) && $method === 'GET') {
    http_response_code(200);
    echo json_encode([
        'service'   => 'BinanceTradingBot Agent Service',
        'status'    => 'healthy',
        'version'   => '1.0.0',
        'agents'    => ['TradingAdvisorAgent'],
        'llm_model' => $config['llm']['model'],
        'timestamp' => time(),
    ]);
    exit;
}

// ── Debug env (dev only) ───────────────────────────────────────────────────
if ($uri === '/api/debug-env' && $method === 'GET') {
    echo json_encode(['llm' => $config['llm']]);
    exit;
}

// ═══════════════════════════════════════════════════════════════════════════
// POST /api/agents/trading/analyze
//
// Full trading analysis: signal + confidence + reasoning + risk + TP/SL.
//
// Body:
//   symbol   string   e.g. "BTCUSDT"
//   rsi      float    current RSI-14 value
//   price    float    current market price
//   candles  array    [{open,high,low,close,volume,time}, ...] (last N 1-min candles)
//   position object   {side, entry_price, quantity, pnl_pct} or null
//   config   object   bot config snapshot {mode, rsi_buy, rsi_sell, tp_pct, sl_pct}
// ═══════════════════════════════════════════════════════════════════════════
if ($uri === '/api/agents/trading/analyze' && $method === 'POST') {
    set_time_limit(300);

    $input = json_decode(file_get_contents('php://input'), true) ?? [];

    $mode = strtoupper(($input['config']['mode'] ?? 'RSI'));
    if (empty($input['price'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing required field: price']);
        exit;
    }
    if ($mode !== 'BC' && empty($input['rsi'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing required field: rsi (required in RSI mode)']);
        exit;
    }

    try {
        $agent  = new TradingAdvisorAgent($config);
        $result = $agent->execute($input);
        echo json_encode($result);
    } catch (\Throwable $e) {
        http_response_code(500);
        echo json_encode(['error' => $e->getMessage()]);
    }
    exit;
}

// 404
http_response_code(404);
echo json_encode(['error' => 'Not found', 'path' => $uri]);
