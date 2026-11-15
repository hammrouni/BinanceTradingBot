<?php
/**
 * Fee & Slippage Watchdog Agent
 * 
 * Analyses the ratio of fees to profit to identify "fee drag"
 * and efficiency issues.
 */

namespace App\Agents;

class FeeWatchdogAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are a Financial Auditor for a trading bot.
Your focus is "Fee Efficiency". Many bots lose money because fees eat their small profits (Fee Drag).

Heuristics:
- A-Grade: Fees are < 5% of gross profit.
- B-Grade: Fees are 5-15% of gross profit.
- C-Grade: Fees are 15-30% of gross profit. High drag.
- D-Grade: Fees are > 30% of gross profit. Strategy is likely unsustainable.

Special Attention:
- Small trades: If trade_size_usd is small, fixed fee components or percentage fees might be killing the edge.
- Manual trades: Often have higher slippage or emotional timing.
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.1;
    }

    public function execute(array $input): array
    {
        // The arithmetic is done here, not by the model: small local LLMs get ratios wrong.
        $tradeCount = count($input['trades'] ?? []);
        $netPnl     = (float) ($input['total_pnl_usd'] ?? 0);
        $fees       = (float) ($input['total_fees_usd'] ?? 0);
        $gross      = $netPnl + $fees;               // PnL before fees
        $feeRatio   = $gross > 0 ? round($fees / $gross * 100, 1) : null;
        $grade      = self::grade($feeRatio, $gross);
        $tradeSize  = $input['trade_size_usd'] ?? null;
        $avgFee     = $input['avg_fee_per_trade'] ?? 0;
        $feeRatioStr = $feeRatio === null ? 'n/a (gross PnL <= 0: fees are pure loss)' : "{$feeRatio}%";
        $manual     = $input['manual_trade_count'] ?? 0;

        $prompt = <<<PROMPT
Analyze the fee efficiency of this bot:

TRADING DATA (exact, already computed):
- Total Trades: {$tradeCount}
- Net PnL (after fees): \${$netPnl}
- Gross PnL (before fees): \${$gross}
- Total Fees: \${$fees}
- Fees as % of gross profit: {$feeRatioStr}
- Grade from the heuristics: {$grade}
- Avg Fee per Trade: \${$avgFee}
- Configured Trade Size: \${$tradeSize}
- Manual Trade Count: {$manual}

Return JSON:
{
  "warning": "description of the main fee issue, or null",
  "recommendation": "one actionable suggestion (e.g. wider take-profit, fewer trades, pay fees in BNB for 25% off)"
}
PROMPT;

        $result = $this->callLLMForJSON($prompt, [
            'max_tokens' => $this->defaultMaxTokens,
        ]);

        if (isset($result['error'])) {
            return $result;
        }

        // Numeric fields always come from the computation above, never from the model.
        return array_merge($result['data'], [
            'efficiency_grade' => $grade,
            'fee_ratio_pct'    => $feeRatio,
            'fee_drag_usd'     => round($fees, 2),
            'net_profit_usd'   => round($netPnl, 2),
        ]);
    }

    private static function grade(?float $feeRatio, float $gross): string
    {
        if ($feeRatio === null) {
            return $gross == 0.0 ? 'A' : 'D';
        }
        return $feeRatio < 5 ? 'A' : ($feeRatio < 15 ? 'B' : ($feeRatio <= 30 ? 'C' : 'D'));
    }
}
