<?php
/**
 * Configuration Auditor Agent
 * 
 * Evaluates whether the active strategy and thresholds are well-suited
 * to the current market regime (volatility, trend, RSI history).
 */

namespace App\Agents;

class ConfigAuditorAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are a Strategy Auditor. Your job is to determine if the bot's current settings (RSI bands, SL/TP) match the current market environment.

Market Regimes:
- Sideways: Price oscillating in a range. Mean-reversion (RSI) works best.
- Trending: Strong directional move. Mean-reversion fails (price "hugs" overbought/oversold).
- High Volatility: Wide swings. Requires wider SL and looser RSI bands.
- Low Volatility: Tight range. Requires tight SL/TP and sensitive RSI.

Evaluation:
- Compatibility Score: % based on how well the strategy fits the regime.
- Strategy Fit: "good" (regime matches strategy), "acceptable" (minor tweaks needed), "poor" (high risk of failure).
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.2;
    }

    public function execute(array $input): array
    {
        $rsiSummary = $this->summarizeRsiHistory($input['rsi_threshold_history'] ?? []);
        
        $prompt = <<<PROMPT
Audit this configuration against the market:

STRATEGY:
- Active Mode: {$input['active_strategy']}
- RSI Thresholds: Buy < {$input['rsi_oversold']}, Sell > {$input['rsi_overbought']}
- SL/TP: SL {$input['stop_loss_pct']}%, TP {$input['take_profit_pct']}%

MARKET STATE:
- Current RSI: {$input['current_rsi']}
- 24h Volatility: {$input['volatility_24h_pct']}%
- Trend Direction: {$input['candle_pattern']} (based on EMA slope)
- Recent Changes: {$rsiSummary}

Return JSON:
{
  "compatibility_score": 0-100,
  "market_regime": "sideways | trending_up | trending_down | high_volatility",
  "strategy_fit": "good | acceptable | poor",
  "key_finding": "Short summary of why it fits or doesn't",
  "suggestion": "Optional technical tweak"
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

    private function summarizeRsiHistory(array $history): string
    {
        if (empty($history)) return "No recent configuration changes.";
        $count = count($history);
        return "Last changed {$count} times recently. Latest: " . json_encode(end($history));
    }
}
