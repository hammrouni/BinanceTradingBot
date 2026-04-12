<?php
/**
 * Liquidity Scout Agent
 * 
 * Evaluates market depth and slippage risk for the configured order size.
 */

namespace App\Agents;

class LiquidityScoutAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        $systemPrompt = <<<'PROMPT'
You are a Market Microstructure Expert. 
Your goal is to evaluate if a specific trade size can be executed on the current order book without excessive slippage.

Indicators:
- GREEN: Very high liquidity, slippage < 0.05%.
- YELLOW: Moderate liquidity, slippage 0.05% - 0.2%.
- RED: Low liquidity or "Flash Crash" risk, slippage > 0.2% or thin book.

Logic:
Compare the 'trade_size_usd' to the 'bid_depth_usd' and 'ask_depth_usd' within 0.5% of the current price.
Flag if the 24h volume is suspiciously low for the symbol.
PROMPT;

        parent::__construct($config, $systemPrompt);
        $this->defaultTemperature = 0.1;
    }

    public function execute(array $input): array
    {
        $bookSummary = $this->summarizeBook($input['order_book_depth'] ?? []);
        
        $prompt = <<<PROMPT
Scout the liquidity for this trade:

CONTEXT:
- Symbol: {$input['symbol']}
- Order Size: \${$input['trade_size_usd']}
- Current Price: \${$input['current_price']}
- 24h Volume: \${$input['24h_volume_usd']}

ORDER BOOK (Top 20):
{$bookSummary}

Return JSON:
{
  "liquidity_level": "GREEN | YELLOW | RED",
  "bid_depth_usd": 0.00,
  "ask_depth_usd": 0.00,
  "spread_pct": 0.00,
  "estimated_slippage_pct": 0.00,
  "fill_confidence": "high | medium | low",
  "reasoning": "one line summary"
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

    private function summarizeBook(array $book): string
    {
        if (empty($book)) return "Order book data missing.";
        $bids = $book['bids'] ?? [];
        $asks = $book['asks'] ?? [];
        return sprintf(
            "Bids: %d levels. Best Bid: %s. Asks: %d levels. Best Ask: %s.",
            count($bids),
            $bids[0][0] ?? 'N/A',
            count($asks),
            $asks[0][0] ?? 'N/A'
        );
    }
}
