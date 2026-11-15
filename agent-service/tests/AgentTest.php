<?php
/**
 * Agent tests: the deterministic parts of each agent (formatting, order-book math, fee grading)
 * with the LLM call mocked out.
 */

namespace Tests;

use PHPUnit\Framework\TestCase;
use App\Agents\BaseAgent;
use App\Agents\FeeWatchdogAgent;
use App\Agents\LiquidityScoutAgent;

class AgentTest extends TestCase
{
    private array $config = [
        'llm' => [
            'base_url' => 'http://mock-llm:11434/v1',
            'api_key' => 'mock-key',
            'model' => 'mock',
            'max_tokens' => 1024,
        ],
    ];

    /** Agent whose callLLM returns $content as the model reply. */
    private function mockAgent(string $className, string $content): BaseAgent
    {
        $agent = $this->getMockBuilder($className)
            ->setConstructorArgs([$this->config])
            ->onlyMethods(['callLLM'])
            ->getMock();
        $agent->method('callLLM')->willReturn(['choices' => [['message' => ['content' => $content]]]]);
        $agent->setLoggingEnabled(false);
        return $agent;
    }

    public function testFmtPriceKeepsDecimalsForCheapCoins(): void
    {
        $this->assertSame('65432.1', BaseAgent::fmtPrice(65432.1));
        $this->assertSame('0.12345', BaseAgent::fmtPrice(0.12345));
        $this->assertSame('0.00001234', BaseAgent::fmtPrice(0.00001234));
        $this->assertSame('n/a', BaseAgent::fmtPrice(null));
    }

    public function testBookMetricsSpreadDepthAndSlippage(): void
    {
        $book = [
            'bids' => [['99.9', '10'], ['99.0', '10']],
            'asks' => [['100.1', '1'], ['100.2', '10']],
        ];
        $m = LiquidityScoutAgent::bookMetrics($book, 200.0);
        $this->assertEqualsWithDelta(0.2, $m['spread_pct'], 1e-6);
        $this->assertEqualsWithDelta(999.0, $m['bid_depth_usd'], 0.01);   // 99.0 is outside 0.5% of mid 100
        $this->assertNotNull($m['buy_slippage_pct']);
        $this->assertGreaterThan(0, $m['buy_slippage_pct']);                      // second ask level was needed
    }

    public function testBookMetricsOrderBiggerThanBookHasNoSlippageEstimate(): void
    {
        $m = LiquidityScoutAgent::bookMetrics(['bids' => [['1', '1']], 'asks' => [['1.01', '1']]], 1000.0);
        $this->assertNull($m['buy_slippage_pct']);
    }

    public function testFeeWatchdogNumbersComeFromCodeNotModel(): void
    {
        // The model answers with a wrong grade/ratio; the agent must override them.
        $agent = $this->mockAgent(FeeWatchdogAgent::class,
            '{"efficiency_grade":"A","fee_ratio_pct":1,"warning":null,"recommendation":"widen TP"}');
        $out = $agent->execute([
            'trades' => array_fill(0, 10, []),
            'total_pnl_usd' => 6.0,     // net
            'total_fees_usd' => 4.0,    // gross = 10 → fees are 40% of gross
            'avg_fee_per_trade' => 0.4,
            'trade_size_usd' => 15,
            'manual_trade_count' => 0,
        ]);
        $this->assertSame('D', $out['efficiency_grade']);
        $this->assertEqualsWithDelta(40.0, $out['fee_ratio_pct'], 1e-9);
        $this->assertSame('widen TP', $out['recommendation']);
    }

    public function testFeeWatchdogLosingGrossIsGradeD(): void
    {
        $agent = $this->mockAgent(FeeWatchdogAgent::class, '{"warning":"x","recommendation":"y"}');
        $out = $agent->execute(['trades' => [[]], 'total_pnl_usd' => -5, 'total_fees_usd' => 1]);
        $this->assertSame('D', $out['efficiency_grade']);
        $this->assertNull($out['fee_ratio_pct']);
    }
}
