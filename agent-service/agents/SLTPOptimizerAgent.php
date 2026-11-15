<?php
/**
 * SLTP Optimizer Agent
 * 
 * Evaluates whether current Take-Profit and Stop-Loss levels are "realistic"
 * based on nearby Support and Resistance levels.
 */

namespace App\Agents;

class SLTPOptimizerAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are a Technical Analyst specialized in Support/Resistance (S/R) levels.
Your goal is to validate if the bot's TP (Take Profit) and SL (Stop Loss) prices make sense given the chart geometry.

Logic (long positions only):
- TP is "above_resistance" when a major resistance sits between the current price and the TP (price likely reverses first).
- TP is "too_small" when it is less than ~0.3% above entry: the 0.2% round-trip fee eats the profit.
- Otherwise TP is "realistic".
- SL is "above_support" when it sits above the nearest major support (normal noise stops you out before the bounce).
- SL is "too_tight" when it is closer to the price than about 1x ATR(14), even if below support.
- Otherwise SL is "safe".
- If there is no open position or no TP/SL set, say so in reasoning and suggest levels from the S/R found.
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.2;
    }

    public function execute(array $input): array
    {
        $candleSummary = $this->summarizeCandles($input['candles_24h'] ?? [], $input['candle_summary'] ?? []);
        $orNone  = fn($v) => $v === null ? 'none' : '$' . self::fmtPrice($v);
        $cur     = self::fmtPrice($input['current_price'] ?? null);
        $entry   = ($input['entry_price'] ?? null) === null ? 'no open position' : $orNone($input['entry_price']);
        $tpPrice = $orNone($input['take_profit_price'] ?? null);
        $slPrice = $orNone($input['stop_loss_price'] ?? null);
        
        $prompt = <<<PROMPT
Optimize the TP/SL levels:

CURRENT LEVELS:
- Current Price: \${$cur}
- Entry Price: {$entry}
- Take Profit Price: {$tpPrice}
- Stop Loss Price: {$slPrice}
- Active Strategy: {$input['active_strategy']}

CANDLE CONTEXT (24h):
{$candleSummary}

Return JSON:
{
  "tp_realism": "realistic | above_resistance | too_small",
  "sl_realism": "safe | above_support | too_tight",
  "nearest_resistance": 0.00,
  "nearest_support": 0.00,
  "suggested_tp": 0.00,
  "suggested_sl": 0.00,
  "reasoning": "Explanation of the S/R levels found and why adjustment is needed (one line)"
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

    private function summarizeCandles(array $candles, array $summary = []): string
    {
        if (!empty($summary['count'])) {
            return sprintf(
                "ATR(14): %.4f. Window range: %.2f - %.2f. Swing highs: %s. Swing lows: %s.",
                $summary['atr_14'], $summary['range_low'], $summary['range_high'],
                implode(', ', $summary['swing_highs'] ?? []), implode(', ', $summary['swing_lows'] ?? [])
            );
        }
        if (empty($candles)) return "No candle data.";
        $highs = array_column($candles, 'high');
        $lows = array_column($candles, 'low');
        return sprintf(
            "Recent Highs: %s... Recent Lows: %s...",
            implode(", ", array_slice($highs, -10)),
            implode(", ", array_slice($lows, -10))
        );
    }
}
