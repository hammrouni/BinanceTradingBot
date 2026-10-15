<?php
/**
 * Trade Health Agent
 * 
 * Evaluates the health of the current open position by comparing
 * unrealised PnL and drawdown to historical volatility (ATR).
 * 
 * Input:
 *   - current_pnl_usd: float
 *   - current_pnl_pct: float
 *   - entry_price: float
 *   - current_price: float
 *   - candles_24h: array (1-min OHLC)
 *   - recent_trades: array (last 10 closed trades)
 */

namespace App\Agents;

class TradeHealthAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are a Risk Management Specialist for an algorithmic trading desk.
Your task is to evaluate the "health" of a single open position.
You are given the current PnL, entry price, recent market volatility (candles), and a baseline of recent trade performance.

Metrics to consider:
1. Drawdown vs ATR: Is the current loss within the normal expected "noise" of the last 24h?
2. Historical Baseline: How does this drawdown compare to the average loss of the last 10 trades?
3. Recovery Probability: Based on the 24h trend, is the price showing signs of mean reversion or accelerating away from entry?

Classification Rules:
- HOLD: PnL is positive or drawdown is < 0.5x ATR.
- CAUTION: Drawdown is 0.5x - 1.2x ATR or volatility is spiking.
- AVERAGE_DOWN: Only suggest if drawdown > 1.2x ATR AND recent candles show a reversal pattern or strong support nearby.

Output constraints:
- Return ONLY valid JSON.
- Reasoning must be exactly one line.
- Confidence is a float between 0.0 and 1.0.
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.2;
    }

    public function execute(array $input): array
    {
        $volatilitySummary = $this->summarizeVolatility($input['candles_24h'] ?? [], $input['candle_summary'] ?? []);
        $historySummary = $this->summarizeHistory($input['recent_trades'] ?? []);
        
        $prompt = <<<PROMPT
Evaluate the health of this trade:

CONTEXT:
- Current PnL: \${$input['current_pnl_usd']} ({$input['current_pnl_pct']}%)
- Entry Price: \${$input['entry_price']}
- Current Price: \${$input['current_price']}

RECENT VOLATILITY (24h 1-min candles):
{$volatilitySummary}

RECENT HISTORY (Last 10 trades):
{$historySummary}

Return JSON:
{
  "verdict": "HOLD | AVERAGE_DOWN | CAUTION",
  "confidence": 0.0-1.0,
  "drawdown_vs_atr": "short description of PnL vs volatility",
  "reasoning": "one line explanation"
}
PROMPT;

        $result = $this->callLLMForJSON($prompt, [
            'max_tokens' => $this->defaultMaxTokens,
        ]);

        if (isset($result['error'])) {
            return $result;
        }

        return $result['data'];
    }

    private function summarizeVolatility(array $candles, array $summary = []): string
    {
        if (!empty($summary['count'])) {
            return sprintf(
                "Analyzed %d 1-min candles. Range: %.2f - %.2f (%.2f%%). ATR(14): %.4f. Swing highs: %s. Swing lows: %s.",
                $summary['count'], $summary['range_low'], $summary['range_high'], $summary['range_pct'],
                $summary['atr_14'], implode(', ', $summary['swing_highs'] ?? []), implode(', ', $summary['swing_lows'] ?? [])
            );
        }
        if (empty($candles)) return "No candle data.";
        
        $count = count($candles);
        $highs = array_column($candles, 'high');
        $lows = array_column($candles, 'low');
        
        $range = max($highs) - min($lows);
        $avg_range = array_sum(array_map(fn($h, $l) => $h - $l, $highs, $lows)) / $count;
        
        return sprintf(
            "Analyzed %d 1-min candles. 24h Range: %.2f. Average Candle Range (Micro-ATR): %.2f.",
            $count, $range, $avg_range
        );
    }

    private function summarizeHistory(array $trades): string
    {
        if (empty($trades)) return "No recent trade history.";
        
        $pnl_sums = array_sum(array_column($trades, 'pnl_usd'));
        $wins = count(array_filter($trades, fn($t) => ($t['pnl_usd'] ?? 0) > 0));
        
        return sprintf(
            "Last %d trades: %d wins. Total historical PnL: \$%.2f.",
            count($trades), $wins, $pnl_sums
        );
    }
}
