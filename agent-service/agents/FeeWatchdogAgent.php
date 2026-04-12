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
        $tradeCount = count($input['trades'] ?? []);
        $prompt = <<<PROMPT
Analyze the fee efficiency of this bot:

TRADING DATA:
- Total Trades: {$tradeCount}
- Total PnL (Net): \${$input['total_pnl_usd']}
- Total Fees: \${$input['total_fees_usd']}
- Avg Fee per Trade: \${$input['avg_fee_per_trade']}
- Configured Trade Size: \${$input['trade_size_usd']}
- Manual Trade Count: {$input['manual_trade_count']}

Return JSON:
{
  "efficiency_grade": "A | B | C | D",
  "fee_ratio_pct": 00.0,
  "fee_drag_usd": 0.00,
  "net_profit_usd": 0.00,
  "warning": "description of any issue or null",
  "recommendation": "one actionable suggestion"
}
PROMPT;

        $result = $this->callLLMForJSON($prompt, [
            'max_tokens' => 1000,
        ]);

        if (isset($result['error'])) {
            return $result;
        }

        return $result['data'];
    }
}
