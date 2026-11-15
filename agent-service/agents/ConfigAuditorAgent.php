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
        
        $mode = strtoupper((string) ($input['active_strategy'] ?? 'RSI'));
        $pct  = fn($v) => is_numeric($v) ? "{$v}%" : 'off';
        $strategyLine = match ($mode) {
            'RSI_ULTRA' => sprintf('RSI Ultra crossover: period %s, signal %s, zone mid %s',
                $input['rsi_ultra_period'] ?? 14, $input['rsi_ultra_signal_period'] ?? 9, $input['rsi_ultra_zone_mid'] ?? 50),
            'BC'        => sprintf('BC fixed prices: buy at %s, sell at %s (RSI is not used)',
                self::fmtPrice($input['bc_buy_price'] ?? null), self::fmtPrice($input['bc_sell_price'] ?? null)),
            default     => sprintf('RSI(14): buy < %s, sell > %s', $input['rsi_oversold'] ?? 'n/a', $input['rsi_overbought'] ?? 'n/a'),
        };
        $sl = $pct($input['stop_loss_pct'] ?? null);
        $tp = $pct($input['take_profit_pct'] ?? null);
        $ts = $pct($input['trailing_stop_pct'] ?? null);
        $trend = $input['trend_pct'] ?? null;
        $trendStr = is_numeric($trend) ? sprintf('%+.2f%% over the window', $trend) : 'unknown';
        $vol = $input['volatility_24h_pct'] ?? 'n/a';
        $rsi = $input['current_rsi'] ?? 'n/a';

        $prompt = <<<PROMPT
Audit this configuration against the market:

STRATEGY:
- Active Mode: {$mode}
- Entry/exit rule: {$strategyLine}
- Exits: SL {$sl}, TP {$tp}, trailing {$ts}

MARKET STATE:
- Current RSI(14): {$rsi}
- Volatility (high-low range of the window): {$vol}%
- Net price change (trend): {$trendStr}
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
