<?php
/**
 * Trading Advisor Agent
 *
 * Analyses live market data, recent trade history, and bot config to produce:
 *   - A trading signal (BUY / SELL / HOLD) via chain-of-thought reasoning
 *   - Config change recommendations (RSI thresholds, TP, SL, or BC prices)
 *   - An actionable advisory with reasoning grounded in real history
 *
 * Input (shared):
 *   - symbol        string   e.g. "BTCUSDT"
 *   - price         float    current market price                          [required]
 *   - candles       array    last N OHLC candles [{open,high,low,close,time}]
 *   - position      array    open position or null  {side, entry_price, quantity, pnl_pct}
 *   - trade_history array    last N closed trades   [{direction, entry_price, pnl_usd, reason, executed_at}]
 *
 * Input (RSI mode) — config.mode = "RSI":
 *   - rsi           float    current RSI-14 value                         [required]
 *   - config        array    {mode, rsi_buy, rsi_sell, tp_pct, sl_pct}
 *
 * Input (BC mode) — config.mode = "BC":
 *   - rsi           float    current RSI-14 value                         [optional, not used for signals]
 *   - config        array    {mode, bc_buy_price, bc_sell_price, tp_pct, sl_pct}
 *
 * Output:
 *   - signal              string      "BUY" | "SELL" | "HOLD"
 *   - confidence          int         0-100
 *   - structural_analysis string      chart structure findings (CoT step 1)
 *   - historical_evaluation string    trade history audit (CoT step 2)
 *   - reasoning           string      logical synthesis leading to the signal (CoT step 3)
 *   - risk_notes          array       specific risks to flag
 *   - suggested_tp        float|null  absolute price (structural resistance)
 *   - suggested_sl        float|null  absolute price (structural support)
 *   - config_advice       object      {should_change, changes:[{field, current, suggested, reason}]}
 *   - action_advice       string      plain-English next step for the trader
 */

namespace App\Agents;

class TradingAdvisorAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are an objective, emotionless quantitative trading architect operating on Binance spot markets.
You receive structured market data, trade history, and bot configuration.
You produce a structured JSON recommendation covering signal, risk, and config calibration.

The bot supports three modes (exactly one is active):

RSI MODE:
- Trades trigger when RSI crosses rsi_buy (oversold) or rsi_sell (overbought) thresholds.
- Analyse whether RSI thresholds are well-calibrated given the recent win/loss pattern.
- Detect RSI divergence: bullish (price makes lower low, RSI makes higher low) or bearish (price makes higher high, RSI makes lower high).
- Require candlestick structural confirmation before recommending BUY or SELL.
- Config advice fields: rsi_buy, rsi_sell, tp_pct, sl_pct.

RSI ULTRA MODE (High-speed HLC3 EMA Crossover):
- This is a faster strategy using HLC3-based RSI (Raw) and an EMA signal line.
- Signals trigger when Raw crosses Signal within specific Midpoint-defined zones.
- Highly sensitive to EMA period settings. Recommend tightening periods in low-volatility or widening in high-volatility.
- Analysis must focus on the relationship between Raw and Signal lines.
- Config advice fields: rsi_ultra_period, rsi_ultra_signal_period, rsi_ultra_zone_mid, tp_pct, sl_pct.

BC MODE (Boundary Channel — fixed target price):
- The bot buys when market price drops to bc_buy_price and sells when it reaches bc_sell_price.
- Momentum indicators (RSI, MACD, etc.) are fundamentally irrelevant in this mode. Never reference them for signal or config decisions.
- Distinguish true breakouts (candle body closes decisively beyond boundary) from fakeouts (price pierces boundary but leaves a long rejection wick).
- If a strong uptrend is detected (sequence of higher highs), avoid recommending SELL at the upper BC boundary — fixed targets fail in strong directional trends.
- If history shows sequential losses from whipsaw price action, suggest widening bc_buy_price and bc_sell_price in config_advice.
- Config advice fields: bc_buy_price, bc_sell_price, tp_pct, sl_pct.

Output constraints:
- Return ONLY valid JSON. No markdown code blocks, no prose, no conversational filler.
- Do not invent data that was not provided.
- suggested_tp and suggested_sl must be absolute prices derived from structural support/resistance in the candle data — never static percentages.
- The JSON keys must appear in the exact order specified in each prompt.
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.3;
    }

    public function execute(array $input): array
    {
        $symbol       = $input['symbol']        ?? 'UNKNOWN';
        $rsi          = $input['rsi']           ?? null;
        $price        = $input['price']         ?? null;
        $candles      = $input['candles']       ?? [];
        $position     = $input['position']      ?? null;
        $botConfig    = $input['config']        ?? [];
        $tradeHistory = $input['trade_history'] ?? [];

        if ($price === null) {
            return ['error' => 'Missing required field: price'];
        }

        $mode = strtoupper($botConfig['mode'] ?? 'RSI');

        $candleTable  = $this->summarizeCandles($candles);
        $positionDesc = $this->describePosition($position);
        $configDesc   = $this->describeConfig($botConfig);
        $historyTable = $this->describeHistory($tradeHistory);
        $priceTrend   = $this->describePriceTrend($candles);

        if ($mode === 'BC') {
            $prompt = $this->buildBcPrompt(
                $symbol, $price, $priceTrend, $positionDesc,
                $configDesc, $historyTable, $candleTable, $botConfig
            );
        } elseif ($mode === 'RSI_ULTRA') {
            $rsiRaw = $input['rsi_ultra_raw'] ?? null;
            $rsiSig = $input['rsi_ultra_signal'] ?? null;
            if ($rsiRaw === null) {
                return ['error' => 'Missing required field: rsi_ultra_raw (required in RSI_ULTRA mode)'];
            }
            $prompt = $this->buildRsiUltraPrompt(
                $symbol, $price, $rsiRaw, $rsiSig, $priceTrend, $positionDesc,
                $configDesc, $historyTable, $candleTable, $botConfig
            );
        } else {
            if ($rsi === null) {
                return ['error' => 'Missing required field: rsi (required in RSI mode)'];
            }
            $prompt = $this->buildRsiPrompt(
                $symbol, $price, $rsi, $priceTrend, $positionDesc,
                $configDesc, $historyTable, $candleTable
            );
        }

        $result = $this->callLLMForJSON($prompt, [
            'temperature' => 0.25,
            'timeout'     => $this->defaultTimeout,
            'max_tokens'  => $this->defaultMaxTokens,
        ]);

        if (isset($result['error'])) {
            return [
                'error'     => $result['error'],
                'agent'     => 'TradingAdvisorAgent',
                'symbol'    => $symbol,
                'timestamp' => time(),
            ];
        }

        $data = $result['data'];

        // logical_synthesis is the final CoT step — surfaced as "reasoning" for the UI
        $reasoning = $data['logical_synthesis'] ?? $data['reasoning'] ?? '';

        return [
            'agent'                => 'TradingAdvisorAgent',
            'symbol'               => $symbol,
            'signal'               => $data['signal']               ?? 'HOLD',
            'confidence'           => $data['confidence']            ?? 0,
            'structural_analysis'  => $data['structural_analysis']   ?? '',
            'historical_evaluation'=> $data['historical_evaluation'] ?? '',
            'reasoning'            => $reasoning,
            'risk_notes'           => $data['risk_notes']            ?? [],
            'suggested_tp'         => $data['suggested_tp']          ?? null,
            'suggested_sl'         => $data['suggested_sl']          ?? null,
            'config_advice'        => $data['config_advice']         ?? ['should_change' => false, 'changes' => []],
            'action_advice'        => $data['action_advice']         ?? '',
            'timestamp'            => time(),
        ];
    }

    // ── Prompt builders ──────────────────────────────────────────────────────

    private function buildRsiPrompt(
        string $symbol, float $price, float $rsi, string $priceTrend,
        string $positionDesc, string $configDesc,
        string $historyTable, string $candleTable
    ): string {
        return <<<PROMPT
You are an objective quantitative trading architect. Analyse the following data without emotional bias and produce a chain-of-thought JSON recommendation. The bot is in RSI MODE.

SYMBOL: {$symbol}
CURRENT PRICE: \${$price}
RSI (14): {$rsi}
PRICE TREND: {$priceTrend}
OPEN POSITION: {$positionDesc}
BOT CONFIG: {$configDesc}

TRADE HISTORY:
{$historyTable}

OHLC CANDLES (T-N = oldest, T-0 = most recent):
{$candleTable}

ANALYSIS INSTRUCTIONS:
1. STRUCTURAL ANALYSIS — Examine the OHLC table:
   - Identify key support levels (recent swing lows) and resistance levels (recent swing highs).
   - Detect RSI divergence: bullish if price prints a lower low while RSI prints a higher low; bearish if price prints a higher high while RSI prints a lower high.
   - Look for candlestick reversal confirmation: directional bars (strong body, small wicks), inside bars signalling compression, or engulfing patterns.
   - Do NOT signal BUY or SELL on RSI threshold alone — require structural confirmation.

2. HISTORICAL EVALUATION — Audit the trade history table:
   - Calculate win rate and total PnL from the summary row.
   - If win rate is below 40% or total PnL is negative, determine whether rsi_buy or rsi_sell caused premature entries (e.g. RSI hit threshold but price continued in the same direction).
   - Recommend tightening or widening thresholds only if history provides direct evidence.

3. LOGICAL SYNTHESIS — Combine steps 1 and 2 into a final decision (2-3 sentences). Reference specific RSI value, candle structure, and history figures.

Return ONLY this JSON object in this exact key order — no markdown, no code fences:
{
  "structural_analysis": "<step 1 findings: support/resistance levels, divergence detected or not, confirmation candle pattern>",
  "historical_evaluation": "<step 2 findings: win rate, PnL audit, evidence for or against threshold changes>",
  "logical_synthesis": "<step 3: 2-3 sentences combining structural and historical findings to justify the signal>",
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <0-100>,
  "risk_notes": ["<specific risk grounded in the data>"],
  "suggested_tp": <absolute price at nearest structural resistance, or null>,
  "suggested_sl": <absolute price at nearest structural support, or null>,
  "config_advice": {
    "should_change": <true|false>,
    "changes": [
      {
        "field": "<rsi_buy|rsi_sell|tp_pct|sl_pct>",
        "current": <current value>,
        "suggested": <suggested value>,
        "reason": "<cite specific trades or candle evidence>"
      }
    ]
  },
  "action_advice": "<one direct, actionable sentence for the trader>"
}

Hard rules:
- config_advice.changes must be an empty array if no changes are warranted.
- suggested_tp and suggested_sl are absolute prices derived from candle structure — never percentages.
- Do not hallucinate data not present in the inputs.
- Confidence below 50 implies HOLD unless structural evidence is unambiguous.
PROMPT;
    }

    private function buildBcPrompt(
        string $symbol, float $price, string $priceTrend,
        string $positionDesc, string $configDesc,
        string $historyTable, string $candleTable, array $cfg
    ): string {
        $bcBuy  = $cfg['bc_buy_price']  ?? 'not set';
        $bcSell = $cfg['bc_sell_price'] ?? 'not set';

        $priceVsLevels = 'unknown';
        if (is_numeric($bcBuy) && is_numeric($bcSell)) {
            if ($price <= $bcBuy) {
                $priceVsLevels = sprintf('AT or BELOW buy boundary ($%s) — potential buy zone', self::fmtPrice($bcBuy));
            } elseif ($price >= $bcSell) {
                $priceVsLevels = sprintf('AT or ABOVE sell boundary ($%s) — potential sell zone', self::fmtPrice($bcSell));
            } else {
                $pctToBuy  = (($price - $bcBuy)  / $bcBuy)  * 100;
                $pctToSell = (($bcSell - $price) / $price)  * 100;
                $priceVsLevels = sprintf(
                    'between boundaries (%.2f%% above buy @ $%s, %.2f%% below sell @ $%s)',
                    $pctToBuy, self::fmtPrice($bcBuy), $pctToSell, self::fmtPrice($bcSell)
                );
            }
        }

        return <<<PROMPT
You are an objective quantitative trading architect. Analyse the following data without emotional bias and produce a chain-of-thought JSON recommendation. The bot is in BC MODE (Boundary Channel — fixed target price mode).

SYMBOL: {$symbol}
CURRENT PRICE: \${$price}
BC BUY BOUNDARY:  \${$bcBuy}
BC SELL BOUNDARY: \${$bcSell}
PRICE vs BOUNDARIES: {$priceVsLevels}
PRICE TREND: {$priceTrend}
OPEN POSITION: {$positionDesc}
BOT CONFIG: {$configDesc}

TRADE HISTORY:
{$historyTable}

OHLC CANDLES (T-N = oldest, T-0 = most recent):
{$candleTable}

CRITICAL CONSTRAINT: This is BC mode. Momentum indicators (RSI, MACD, Stochastic) are fundamentally
irrelevant here. They must never influence the signal or config_advice. Any reference to RSI in your
output is a critical error.

ANALYSIS INSTRUCTIONS:
1. STRUCTURAL ANALYSIS — Examine the OHLC table:
   - Determine whether price is approaching, touching, or has crossed a BC boundary.
   - Distinguish true breakout from fakeout: a true breakout requires the candle BODY to close decisively
     beyond the boundary. A fakeout is identified by a long rejection wick with a close inside the range.
   - Market regime check: if the price trend shows a strong sequence of higher highs, do NOT recommend
     SELL at the upper boundary — fixed targets fail in strong directional trends.
   - Identify structural support and resistance from candle swing points for TP/SL anchoring.

2. HISTORICAL EVALUATION — Audit the trade history table:
   - Calculate win rate and total PnL from the summary row.
   - Identify if losses cluster around whipsaw price action near the boundaries (price touches bc_buy_price
     or bc_sell_price repeatedly with small reversals).
   - If sequential losses indicate whipsaws, recommend widening the boundaries in config_advice.
   - If wins are consistently achieved at the boundaries, the configuration is well-calibrated.

3. LOGICAL SYNTHESIS — Combine steps 1 and 2 into a final decision (2-3 sentences). Reference specific
   prices, boundary distances, candle structure, and history figures. Never mention RSI.

Return ONLY this JSON object in this exact key order — no markdown, no code fences:
{
  "structural_analysis": "<step 1 findings: boundary proximity, true breakout vs fakeout assessment, market regime, structural support/resistance>",
  "historical_evaluation": "<step 2 findings: win rate, PnL audit, whipsaw evidence, boundary calibration assessment>",
  "logical_synthesis": "<step 3: 2-3 sentences combining structural and historical findings to justify the signal — no RSI references>",
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <0-100>,
  "risk_notes": ["<specific risk grounded in the data>"],
  "suggested_tp": <absolute price at nearest structural resistance, or null>,
  "suggested_sl": <absolute price at nearest structural support, or null>,
  "config_advice": {
    "should_change": <true|false>,
    "changes": [
      {
        "field": "<bc_buy_price|bc_sell_price|tp_pct|sl_pct>",
        "current": <current value>,
        "suggested": <suggested value>,
        "reason": "<cite specific trade losses or candle evidence — no RSI>"
      }
    ]
  },
  "action_advice": "<one direct, actionable sentence for the trader — no RSI references>"
}

Hard rules:
- config_advice.changes must be an empty array if no changes are warranted.
- suggested_tp and suggested_sl are absolute prices derived from candle structure — never percentages.
- Never output rsi_buy or rsi_sell as config_advice fields in BC mode.
- Do not hallucinate data not present in the inputs.
- Confidence below 50 implies HOLD unless structural evidence is unambiguous.
PROMPT;
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    private function describePosition(?array $position): string
    {
        if (empty($position)) return 'None';
        return sprintf(
            '%s | entry=$%s | qty=%.6f | PnL=%.2f%%',
            $position['side']        ?? 'LONG',
            self::fmtPrice($position['entry_price'] ?? 0),
            $position['quantity']    ?? 0,
            $position['pnl_pct']     ?? 0
        );
    }

    private function describeConfig(array $cfg): string
    {
        $mode = strtoupper($cfg['mode'] ?? 'RSI');
        $pct  = fn($v) => is_numeric($v) ? sprintf('%.2f%%', $v) : 'off';
        $exits = sprintf('tp=%s | sl=%s', $pct($cfg['tp_pct'] ?? null), $pct($cfg['sl_pct'] ?? null));

        if ($mode === 'BC') {
            return sprintf(
                'mode=BC | bc_buy_price=%s | bc_sell_price=%s | %s',
                isset($cfg['bc_buy_price'])  ? '$' . self::fmtPrice($cfg['bc_buy_price'])  : 'not set',
                isset($cfg['bc_sell_price']) ? '$' . self::fmtPrice($cfg['bc_sell_price']) : 'not set',
                $exits
            );
        }

        if ($mode === 'RSI_ULTRA') {
            return sprintf(
                'mode=RSI_ULTRA | period=%d | signal_period=%d | zone_mid=%.1f | %s',
                $cfg['rsi_ultra_period'] ?? 14,
                $cfg['rsi_ultra_signal_period'] ?? 9,
                $cfg['rsi_ultra_zone_mid'] ?? 50,
                $exits
            );
        }

        return sprintf(
            'mode=RSI | rsi_buy=%.1f | rsi_sell=%.1f | %s',
            $cfg['rsi_buy']  ?? 30,
            $cfg['rsi_sell'] ?? 70,
            $exits
        );
    }

    private function buildRsiUltraPrompt(
        string $symbol, float $price, float $rsiRaw, ?float $rsiSig, string $priceTrend,
        string $positionDesc, string $configDesc,
        string $historyTable, string $candleTable, array $cfg
    ): string {
        $sigStr = $rsiSig !== null ? (string)$rsiSig : 'calculating...';
        $zoneMid = $cfg['rsi_ultra_zone_mid'] ?? 50;
        return <<<PROMPT
You are an objective quantitative trading architect. Analyse the following data without emotional bias and produce a chain-of-thought JSON recommendation. The bot is in RSI ULTRA MODE (High-speed HLC3 EMA Crossover).

SYMBOL: {$symbol}
CURRENT PRICE: \${$price}
ULTRA RAW RSI: {$rsiRaw}
ULTRA SIGNAL: {$sigStr}
ZONE MIDPOINT: {$zoneMid}
PRICE TREND: {$priceTrend}
OPEN POSITION: {$positionDesc}
BOT CONFIG: {$configDesc}

TRADE HISTORY:
{$historyTable}

OHLC CANDLES (T-N = oldest, T-0 = most recent):
{$candleTable}

ANALYSIS INSTRUCTIONS:
1. RELATIONSHIP ANALYSIS — Examine the relationship between Raw and Signal.
   - Buy signals trigger when Raw crosses above Signal while Raw is below the zone midpoint.
   - Sell signals trigger when Raw crosses below Signal while Raw is above the zone midpoint.
   - Evaluate if Raw is "hugging" the signal line (too much noise) or making clean crosses.
   - Identify structural support/resistance from OHLC candles.

2. HISTORICAL EVALUATION:
   - Audit win rate and PnL.
   - If history shows losses from late entries, recommend tightening the EMA signal period.
   - If noise (whipsaws) is high, recommend widening the signal period or adjusting the zone midpoint.

3. LOGICAL SYNTHESIS — 2-3 sentences justifying the signal based on the Raw/Signal proximity and market structure.

Return ONLY this JSON object in this exact key order:
{
  "structural_analysis": "<step 1 findings>",
  "historical_evaluation": "<step 2 findings>",
  "logical_synthesis": "<step 3 findings>",
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <0-100>,
  "risk_notes": ["<specific risk>"],
  "suggested_tp": <absolute price at nearest structural resistance, or null>,
  "suggested_sl": <absolute price at nearest structural support, or null>,
  "config_advice": {
    "should_change": <true|false>,
    "changes": [
      {
        "field": "<rsi_ultra_period|rsi_ultra_signal_period|rsi_ultra_zone_mid|tp_pct|sl_pct>",
        "current": <current value>,
        "suggested": <suggested value>,
        "reason": "<reason>"
      }
    ]
  },
  "action_advice": "<one direct, actionable sentence for the trader>"
}

Hard rules:
- Return ONLY the JSON object — no markdown, no code fences.
- config_advice.changes must be an empty array if no changes are warranted.
- On 1-minute candles crossovers are frequent: a fast setting that trades often pays 0.2% fees per round trip, so only suggest shorter periods if the history shows the wins cover the fees.
- Do not hallucinate data not present in the inputs.
- Confidence below 50 implies HOLD unless structural evidence is unambiguous.
PROMPT;
    }

    /**
     * Renders trade history as a Markdown table with a mathematical summary row.
     * Newest trades first (up to 15).
     */
    private function describeHistory(array $trades): string
    {
        if (empty($trades)) return 'No trade history available.';

        $rows    = [];
        $wins    = 0;
        $losses  = 0;
        $totalPnl = 0.0;
        $slice   = array_slice($trades, 0, 15);

        foreach ($slice as $t) {
            $pnl    = isset($t['pnl_usd']) ? (float)$t['pnl_usd'] : null;
            $dir    = strtoupper($t['direction'] ?? '?');
            $ep     = isset($t['entry_price']) ? '$' . self::fmtPrice($t['entry_price']) : 'n/a';
            $reason = $t['reason']     ?? 'unknown';
            $at     = isset($t['executed_at']) ? substr($t['executed_at'], 0, 16) : '?';

            if ($pnl !== null) {
                $pnlStr = sprintf('%+.2f$', $pnl);
                if ($pnl > 0) $wins++;
                elseif ($pnl < 0) $losses++;
                $totalPnl += $pnl;
            } else {
                $pnlStr = 'n/a';
            }

            $rows[] = "| {$at} | {$dir} | {$ep} | {$pnlStr} | {$reason} |";
        }

        $total   = count($slice);
        $winRate = $total > 0 ? round(($wins / $total) * 100, 1) : 0;
        $summary = sprintf(
            'Summary: %d trades | %d W / %d L | Win rate: %.1f%% | Total PnL: %+.2f$',
            $total, $wins, $losses, $winRate, $totalPnl
        );

        $header = "| Time (UTC)       | Dir  | Entry Price | PnL      | Reason   |";
        $sep    = "|------------------|------|-------------|----------|----------|";

        return $summary . "\n\n" . $header . "\n" . $sep . "\n" . implode("\n", $rows);
    }

    /**
     * Renders OHLC candles as a Markdown table.
     * Periods are labelled T-N (oldest) → T-0 (most recent) for chronological alignment.
     */
    private function summarizeCandles(array $candles): string
    {
        if (empty($candles)) return 'No candle data provided.';

        $total  = count($candles);
        $header = "| Period | Open | High | Low | Close |";
        $sep    = "|--------|------|------|-----|-------|";
        $rows   = [];

        foreach ($candles as $i => $c) {
            $period = 'T-' . ($total - 1 - $i);   // T-(N-1) down to T-0
            $rows[] = sprintf(
                '| %-6s | %s | %s | %s | %s |',
                $period,
                self::fmtPrice($c['open']  ?? 0),
                self::fmtPrice($c['high']  ?? 0),
                self::fmtPrice($c['low']   ?? 0),
                self::fmtPrice($c['close'] ?? 0)
            );
        }

        return $header . "\n" . $sep . "\n" . implode("\n", $rows);
    }

    private function describePriceTrend(array $candles): string
    {
        if (count($candles) < 3) return 'Insufficient candle data.';

        $closes = array_column($candles, 'close');
        if (empty($closes)) return 'No close data.';

        $first = (float)$closes[0];
        $last  = (float)end($closes);
        if ($first == 0) return 'No trend data.';

        $changePct = (($last - $first) / $first) * 100;
        $direction = $changePct > 0.3 ? 'Uptrend' : ($changePct < -0.3 ? 'Downtrend' : 'Sideways');

        $highs       = array_column($candles, 'high');
        $higherHighs = 0;
        for ($i = 1; $i < count($highs); $i++) {
            if ((float)$highs[$i] > (float)$highs[$i - 1]) $higherHighs++;
        }

        return sprintf(
            '%s (%.2f%% over last %d candles, %d/%d higher highs)',
            $direction, $changePct, count($candles), $higherHighs, count($highs) - 1
        );
    }
}
