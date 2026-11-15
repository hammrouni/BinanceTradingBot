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
        $book      = $input['order_book_depth'] ?? [];
        $tradeSize = (float) ($input['trade_size_usd'] ?? 0);
        $m         = self::bookMetrics($book, $tradeSize);
        $price     = self::fmtPrice($input['current_price'] ?? null);
        $volume    = round((float) ($input['24h_volume_usd'] ?? 0));
        $level     = self::level($m);
        $fmt       = fn($v) => $v === null ? 'n/a' : (string) $v;

        $prompt = <<<PROMPT
Scout the liquidity for this trade:

CONTEXT:
- Symbol: {$input['symbol']}
- Order Size: \${$tradeSize}
- Current Price: \${$price}
- 24h Quote Volume: \${$volume}

ORDER BOOK METRICS (exact, computed from the top {$m['levels']} levels per side):
- Best bid / ask: {$fmt($m['best_bid'])} / {$fmt($m['best_ask'])}
- Spread: {$fmt($m['spread_pct'])}%
- Bid depth within 0.5% of mid: \${$m['bid_depth_usd']}
- Ask depth within 0.5% of mid: \${$m['ask_depth_usd']}
- Estimated slippage for a market BUY of the order size: {$fmt($m['buy_slippage_pct'])}%
- Level from the heuristics: {$level}

Return JSON:
{
  "fill_confidence": "high | medium | low",
  "reasoning": "one line summary"
}
PROMPT;

        $result = $this->callLLMForJSON($prompt, [
            'max_tokens' => $this->defaultMaxTokens,
        ]);

        if (isset($result['error'])) {
            return $result;
        }

        return array_merge($result['data'], [
            'liquidity_level'        => $level,
            'bid_depth_usd'          => $m['bid_depth_usd'],
            'ask_depth_usd'          => $m['ask_depth_usd'],
            'spread_pct'             => $m['spread_pct'],
            'estimated_slippage_pct' => $m['buy_slippage_pct'],
        ]);
    }

    /** Spread, depth within 0.5% of mid, and slippage of a market buy walking the asks. */
    public static function bookMetrics(array $book, float $tradeSizeUsd): array
    {
        $bids = $book['bids'] ?? [];
        $asks = $book['asks'] ?? [];
        $bestBid = isset($bids[0][0]) ? (float) $bids[0][0] : null;
        $bestAsk = isset($asks[0][0]) ? (float) $asks[0][0] : null;
        $out = [
            'levels' => max(count($bids), count($asks)), 'best_bid' => $bestBid, 'best_ask' => $bestAsk,
            'spread_pct' => null, 'bid_depth_usd' => 0.0, 'ask_depth_usd' => 0.0, 'buy_slippage_pct' => null,
        ];
        if (!$bestBid || !$bestAsk) {
            return $out;
        }
        $mid = ($bestBid + $bestAsk) / 2;
        $out['spread_pct'] = round(($bestAsk - $bestBid) / $mid * 100, 4);
        foreach ($bids as [$p, $q]) {
            if ((float) $p >= $mid * 0.995) $out['bid_depth_usd'] += (float) $p * (float) $q;
        }
        foreach ($asks as [$p, $q]) {
            if ((float) $p <= $mid * 1.005) $out['ask_depth_usd'] += (float) $p * (float) $q;
        }
        $out['bid_depth_usd'] = round($out['bid_depth_usd'], 2);
        $out['ask_depth_usd'] = round($out['ask_depth_usd'], 2);

        // Walk the asks to fill $tradeSizeUsd; slippage = avg fill price vs best ask.
        if ($tradeSizeUsd > 0) {
            $left = $tradeSizeUsd; $qty = 0.0;
            foreach ($asks as [$p, $q]) {
                $take = min($left, (float) $p * (float) $q);
                $qty += $take / (float) $p;
                $left -= $take;
                if ($left <= 1e-9) break;
            }
            if ($left <= 1e-9 && $qty > 0) {
                $out['buy_slippage_pct'] = round((($tradeSizeUsd / $qty) / $bestAsk - 1) * 100, 4);
            }
        }
        return $out;
    }

    private static function level(array $m): string
    {
        if ($m['spread_pct'] === null || $m['buy_slippage_pct'] === null) {
            return 'RED';  // empty book or the order is bigger than the visible book
        }
        $cost = $m['spread_pct'] + $m['buy_slippage_pct'];
        return $cost < 0.05 ? 'GREEN' : ($cost <= 0.2 ? 'YELLOW' : 'RED');
    }
}
