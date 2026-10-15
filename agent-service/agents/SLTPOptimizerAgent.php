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

Logic:
- TP Realism: If TP is *above* a major resistance level, it is "unrealistic" (price likely reverses before hitting it).
- SL Realism: If SL is *above* a major support level, it is "too tight" (noise likely stops you out before the bounce).

Classification:
- TP: realistic | above_resistance | below_target
- SL: safe | above_support | too_tight
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.2;
    }

    public function execute(array $input): array
    {
        $candleSummary = $this->summarizeCandles($input['candles_24h'] ?? [], $input['candle_summary'] ?? []);
        
        $prompt = <<<PROMPT
Optimize the TP/SL levels:

CURRENT LEVELS:
- Current Price: \${$input['current_price']}
- Entry Price: \${$input['entry_price']} (if active)
- Take Profit Price: \${$input['take_profit_price']}
- Stop Loss Price: \${$input['stop_loss_price']}
- Active Strategy: {$input['active_strategy']}

CANDLE CONTEXT (24h):
{$candleSummary}

Return JSON:
{
  "tp_realism": "realistic | above_resistance | below_target",
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
