<?php
/**
 * Agent Integration Test
 */

namespace Tests;

use PHPUnit\Framework\TestCase;
use App\Agents\DirectorAgent;
use App\Agents\NarrativeAgent;
use App\Agents\PromptEnhancerAgent;
use App\Agents\ResearchAgent;
use App\Agents\SceneBreakdownOrchestrator;

class AgentTest extends TestCase
{
    private $config;

    protected function setUp(): void
    {
        $this->config = [
            'llm' => [
                'base_url' => 'http://mock-llm:11434/v1',
                'api_key' => 'mock-key',
                'provider' => 'openai',
                'model' => 'llama3.2',
                'fallback_model' => 'mistral',
                'temperature' => 0.7,
                'max_tokens' => 4096,
            ],
            'api' => [
                'timeout' => 60,
                'retry_attempts' => 3,
            ],
            'storage' => [
                'projects_dir' => '/tmp/projects',
            ]
        ];
    }

    /**
     * Helper to mock LLM response in agents
     */
    private function getMockAgent($className, $mockResponse)
    {
        $agent = $this->getMockBuilder($className)
            ->setConstructorArgs([$this->config])
            ->onlyMethods(['callLLM'])
            ->getMock();

        $agent->method('callLLM')
            ->willReturn($mockResponse);

        return $agent;
    }

    public function testDirectorAgent()
    {
        $mockResponse = [
            'choices' => [
                ['message' => ['content' => 'Production guidelines: high energy, fast pacing.']]
            ]
        ];

        $agent = $this->getMockAgent(DirectorAgent::class, $mockResponse);
        $result = $agent->execute(['project' => 'A futuristic city']);

        $this->assertEquals('DirectorAgent', $result['agent']);
        $this->assertStringContainsString('Production guidelines', $result['directions']);
        $this->assertEquals('A futuristic city', $result['project']);
    }

    public function testNarrativeAgent()
    {
        $mockResponse = [
            'choices' => [
                ['message' => ['content' => 'The year was 2050, and the city glowed with neon lights.']]
            ]
        ];

        $agent = $this->getMockAgent(NarrativeAgent::class, $mockResponse);
        $result = $agent->execute(['topic' => 'Write a story about a futuristic city']);

        $this->assertEquals('NarrativeAgent', $result['agent']);
        $this->assertStringContainsString('2050', $result['narrative']);
    }

    public function testPromptEnhancerAgent()
    {
        $mockResponse = [
            'choices' => [
                ['message' => ['content' => 'Enhanced prompt: Cinematic view of a neon-lit cyberpunk metropolis.']]
            ]
        ];

        $agent = $this->getMockAgent(PromptEnhancerAgent::class, $mockResponse);
        $result = $agent->execute(['prompt' => 'futuristic city']);

        $this->assertEquals('PromptEnhancerAgent', $result['agent']);
        $this->assertStringContainsString('Cinematic view', $result['enhanced_prompt']);
    }

    public function testResearchAgent()
    {
        $mockResponse = [
            'choices' => [
                ['message' => ['content' => 'Research results: Futuristic cities often feature vertical farming.']]
            ]
        ];

        $agent = $this->getMockAgent(ResearchAgent::class, $mockResponse);
        $result = $agent->execute(['topic' => 'futuristic cities']);

        $this->assertEquals('ResearchAgent', $result['agent']);
        $this->assertStringContainsString('vertical farming', $result['research']);
    }

    public function testSceneBreakdownOrchestrator()
    {
        $jsonResponse = json_encode([
            ['spoken_text' => 'Welcome to the future.', 'visual_prompt' => 'Wide shot of skyscrapers.'],
            ['spoken_text' => 'It is bright and busy.', 'visual_prompt' => 'Close up of a flying car.']
        ]);

        $mockResponse = [
            'choices' => [
                ['message' => ['content' => "```json\n$jsonResponse\n```"]]
            ]
        ];

        $agent = $this->getMockAgent(SceneBreakdownOrchestrator::class, $mockResponse);
        $result = $agent->execute(['script' => 'Intro to future city', 'duration' => 20]);

        $this->assertEquals('SceneBreakdownOrchestrator', $result['agent']);

        // Test parsing separately
        $scenes = $agent->parseScenes($result['scenes']);
        $this->assertCount(2, $scenes);
        $this->assertEquals('Welcome to the future.', $scenes[0]['spoken_text']);
        $this->assertEquals('Wide shot of skyscrapers.', $scenes[0]['visual_prompt']);
    }
}
