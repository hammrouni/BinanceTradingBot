<?php
/**
 * Base Agent Class
 * 
 * Foundation for all specialized agents in the agent service.
 * Provides LLM communication, context injection, JSON extraction,
 * retry logic, and conversation management following NanoAgent patterns.
 * 
 * Architecture notes:
 * - Uses direct cURL to OpenAI-compatible endpoint (model-runner/Ollama)
 *   because the NanoAgent Agent class requires a non-empty API key and
 *   a supported provider matching its resolver, while this setup uses
 *   a local model runner with OpenAI-compatible API and no auth.
 * - Follows NanoAgent's ContextBuilder pattern for context injection
 * - Follows NanoAgent's Agent pattern for conversation history management
 * - Includes comprehensive JSON logging for AI calls via AILogger
 */

namespace App\Agents;

use NanoAgent\Agent;
use NanoAgent\Tools\FunctionTool;

abstract class BaseAgent
{
    protected array $config;
    protected string $name;
    protected ?Agent $agent = null;
    protected string $systemPrompt = '';
    protected ?AILogger $logger = null;

    /** @var array<string, string> Context data injected into system prompt (NanoAgent ContextBuilder pattern) */
    protected array $context = [];

    /** @var array Conversation history for multi-turn interactions */
    protected array $conversationHistory = [];

    /** @var string Language for agent responses (EN, FR, AR) */
    protected string $language = 'EN';

    /** @var string Theme for agent responses (technical, simple, detailed) */
    protected string $theme = 'technical';

    /** @var int Default timeout in seconds for LLM calls */
    protected int $defaultTimeout = 900;

    /** @var int Default max tokens for LLM responses */
    protected int $defaultMaxTokens = 16384;

    /** @var float Default temperature for LLM calls */
    protected float $defaultTemperature = 0.8;

    /** @var float top_p nucleus sampling — higher = more creative word choices */
    protected float $defaultTopP = 0.95;

    /** @var float Penalise repeating the same phrases */
    protected float $defaultRepeatPenalty = 1.1;

    /**
     * Facts about the bot every agent must respect (appended to each system prompt).
     * Without them the models suggested shorts and take-profits smaller than the fees.
     */
    protected const TRADING_RULES = <<<'RULES'


BOT FACTS (always true, never contradict them):
- Binance SPOT, long-only: one position at a time. BUY opens it, SELL only closes it. There is no shorting and no leverage.
- Fees: 0.1% per side, so a round trip costs about 0.2% of the trade size plus slippage. Any take-profit below ~0.3% loses money after fees; never suggest one.
- Numbers already computed in the input (ratios, depths, percentages, win rates) are exact: reuse them, do not recompute or round them differently.
- Quote prices with the same number of decimals as the input prices (low-priced coins need more than 2 decimals).
- If the data is insufficient, say so and prefer HOLD / no change over guessing.
RULES;

    /** @var bool Whether logging is enabled */
    protected bool $loggingEnabled = true;

    public function __construct(array $config, string $systemPrompt = '')
    {
        $this->config = $config;
        $this->name = static::class;
        $this->systemPrompt = $systemPrompt;

        if (!empty($config['llm']['timeout'])) {
            $this->defaultTimeout = (int) $config['llm']['timeout'];
        }
        if (!empty($config['llm']['max_tokens'])) {
            $this->defaultMaxTokens = (int) $config['llm']['max_tokens'];
        }

        // Initialize logger
        $this->initLogger();
    }

    /**
     * Initialize the AI logger
     */
    private function initLogger(): void
    {
        try {
            $this->logger = new AILogger();
        } catch (\Exception $e) {
            $this->loggingEnabled = false;
            error_log("Failed to initialize AILogger: " . $e->getMessage());
        }
    }

    /**
     * Enable or disable logging
     */
    public function setLoggingEnabled(bool $enabled): void
    {
        $this->loggingEnabled = $enabled;
    }

    /**
     * Execute the agent's task
     */
    abstract public function execute(array $input): array;

    /**
     * Add context data to be injected into the system prompt.
     * Follows NanoAgent's ContextBuilder pattern: labeled blocks appended to system prompt.
     */
    public function addContext(string $label, string $content): void
    {
        $this->context[$label] = $content;
    }

    /**
     * Clear all context data
     */
    public function clearContext(): void
    {
        $this->context = [];
    }

    /**
     * Set language for agent responses
     */
    public function setLanguage(string $language): void
    {
        $lang = strtoupper($language);
        if (in_array($lang, ['EN', 'FR', 'AR'], true)) {
            $this->language = $lang;
        }
    }

    /**
     * Set theme for agent responses
     */
    public function setTheme(string $theme): void
    {
        $t = strtolower($theme);
        if (in_array($t, ['technical', 'simple', 'detailed'], true)) {
            $this->theme = $t;
        }
    }

    /**
     * Build the full system prompt with injected context.
     * Mirrors NanoAgent\Utils\ContextBuilder::build()
     */
    protected function buildSystemPrompt(): string
    {
        $fullPrompt = $this->systemPrompt . self::TRADING_RULES;

        // Add language instruction — explicit about JSON text values
        $langInstructions = [
            'EN' => "\n\nLANGUAGE RULE: Write all text values in English. JSON keys stay in English.",
            'FR' => "\n\nLANGUAGE RULE: Write ALL text values inside the JSON in French. JSON keys stay in English. Every string field (structural_analysis, historical_evaluation, logical_synthesis, reasoning, action_advice, risk_notes, reason, etc.) MUST be written in French. This is mandatory.",
            'AR' => "\n\nLANGUAGE RULE: Write ALL text values inside the JSON in Arabic. JSON keys stay in English. Every string field (structural_analysis, historical_evaluation, logical_synthesis, reasoning, action_advice, risk_notes, reason, etc.) MUST be written in Arabic. This is mandatory.",
        ];
        $fullPrompt .= $langInstructions[$this->language] ?? $langInstructions['EN'];

        // Add theme instruction — concrete behavioral directives, not vague hints
        $themeInstructions = [
            'technical' => "\n\nSTYLE RULE (technical): Use precise financial terminology. Quote exact prices, percentages, and indicator values. Cite specific candle patterns by name (e.g. engulfing, inside bar). Keep sentences dense and data-driven. No explanatory padding.",
            'simple'    => "\n\nSTYLE RULE (simple): You are explaining to a beginner trader with no technical background. Avoid all jargon — if you must use a term, explain it in plain words immediately after. Replace terms like 'structural resistance' with 'price level where sellers have pushed price down before'. Use short sentences. The action_advice must tell the user exactly what to do, as if instructing a child.",
            'detailed'  => "\n\nSTYLE RULE (detailed): Write exhaustive explanations for every field. Each analysis field must contain at least 3-4 sentences covering multiple scenarios. Explain your reasoning chain step by step, including what you considered and rejected. The action_advice must include the rationale, the risk, and the expected outcome.",
        ];
        $fullPrompt .= $themeInstructions[$this->theme] ?? $themeInstructions['technical'];

        if (!empty($this->context)) {
            $fullPrompt .= "\n\n---\nContext Data:\n";
            foreach ($this->context as $label => $data) {
                $fullPrompt .= sprintf("\n[%s]:\n%s\n", $label, trim($data));
            }
            $fullPrompt .= "\n---\n";
        }

        return $fullPrompt;
    }

    /**
     * Call LLM with enhanced options.
     * 
     * @param string $prompt User message to send
     * @param array $options Configuration overrides:
     *   - temperature: float (0.0-1.0) controls creativity
     *   - timeout: int seconds before timeout
     *   - max_tokens: int maximum response length
     *   - json_mode: bool request JSON response format
     *   - system_prompt_override: string replace system prompt for this call
     *   - conversation: bool use conversation history (multi-turn)
     * @return array LLM response with 'choices' or 'error'
     */
    protected function callLLM(string $prompt, array $options = []): array
    {
        $baseUrl = $this->config['llm']['base_url'] ?? 'http://host.docker.internal:11434/v1';
        $model = $this->config['llm']['model'] ?? 'gemma4:26b';
        $apiKey = $this->config['llm']['api_key'] ?? '';

        $url = rtrim($baseUrl, '/') . '/chat/completions';

        // Build system prompt with context injection
        $systemPrompt = $options['system_prompt_override'] ?? $this->buildSystemPrompt();

        // Build messages array
        $messages = [];
        if (!empty($systemPrompt)) {
            $messages[] = ['role' => 'system', 'content' => $systemPrompt];
        }

        // Include conversation history for multi-turn interactions
        if (!empty($options['conversation']) && !empty($this->conversationHistory)) {
            foreach ($this->conversationHistory as $historyMsg) {
                $messages[] = $historyMsg;
            }
        }

        // Append language + theme reminders to reinforce system rules
        $userContent = $prompt;
        if ($this->language === 'FR') {
            $userContent .= "\n\nREMINDER: All text values in your JSON response must be written in French.";
        } elseif ($this->language === 'AR') {
            $userContent .= "\n\nREMINDER: All text values in your JSON response must be written in Arabic.";
        }
        if ($this->theme === 'simple') {
            $userContent .= "\n\nREMINDER: Write for a complete beginner. No jargon. Short sentences. Explain every term you use.";
        } elseif ($this->theme === 'detailed') {
            $userContent .= "\n\nREMINDER: Write exhaustive explanations. Every text field must have at least 3-4 sentences with full reasoning chains.";
        }

        $messages[] = ['role' => 'user', 'content' => $userContent];

        $temperature = $options['temperature'] ?? $this->defaultTemperature;
        $timeout = $options['timeout'] ?? $this->defaultTimeout;
        $topP = $options['top_p'] ?? $this->defaultTopP;
        $repeatPenalty = $options['repeat_penalty'] ?? $this->defaultRepeatPenalty;

        $data = [
            'model' => $model,
            'messages' => $messages,
            'temperature' => $temperature,
            'top_p' => $topP,
        ];

        // repeat_penalty is Ollama-specific — unsupported by Groq/OpenAI
        if (($this->config['llm']['api_key'] ?? '') === 'ollama') {
            $data['repeat_penalty'] = $repeatPenalty;
        }

        // Use per-call max_tokens or fall back to config-driven default
        $data['max_tokens'] = $options['max_tokens'] ?? $this->defaultMaxTokens;

        // Request JSON response format if supported by the model
        if (!empty($options['json_mode'])) {
            $data['response_format'] = ['type' => 'json_object'];
        }

        // Start logging if enabled
        $logEntryId = null;
        if ($this->loggingEnabled && $this->logger) {
            $logEntryId = $this->logger->startLogEntry($this->name, $data);
        }

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        $headers = ['Content-Type: application/json'];
        if (!empty($apiKey)) {
            $headers[] = 'Authorization: Bearer ' . $apiKey;
        }
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 15);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curlError = curl_error($ch);
        curl_close($ch);

        // Complete logging
        if ($this->loggingEnabled && $this->logger && $logEntryId) {
            $responseData = null;
            $errorMsg = null;

            if ($curlError) {
                $errorMsg = $curlError;
                $responseData = ['error' => $curlError];
            } elseif ($httpCode !== 200) {
                $errorMsg = "HTTP {$httpCode}: {$response}";
                $responseData = ['error' => $errorMsg, 'http_status' => $httpCode];
            } else {
                $responseData = json_decode($response, true) ?? ['raw' => $response];
            }

            $this->logger->completeLogEntry(
                $logEntryId,
                $responseData,
                $httpCode,
                0,
                $errorMsg
            );
        }

        if ($curlError) {
            return ['error' => "LLM request failed ({$this->name}): {$curlError}"];
        }

        if ($httpCode !== 200) {
            return ['error' => "LLM HTTP {$httpCode} ({$this->name}): {$response}"];
        }

        $result = json_decode($response, true);

        if (isset($result['choices'][0]['message']['content'])) {
            $content = $result['choices'][0]['message']['content'];

            // Detect empty content — thinking model exhausted max_tokens on <think> block
            if ($content === '' || $content === null) {
                $usage = $result['usage'] ?? [];
                $limit = $data['max_tokens'] ?? 'unset';
                $completion = $usage['completion_tokens'] ?? '?';
                error_log("[{$this->name}] WARNING: Empty content returned. completion_tokens={$completion} max_tokens={$limit}. Model likely hit token limit during thinking. Increase max_tokens.");
                return ['error' => "Empty response from model — hit max_tokens={$limit} during thinking (completion_tokens={$completion}). Increase max_tokens."];
            }

            // Store in conversation history for multi-turn
            if (!empty($options['conversation'])) {
                $this->conversationHistory[] = ['role' => 'user', 'content' => $prompt];
                $this->conversationHistory[] = ['role' => 'assistant', 'content' => $content];
            }

            return [
                'choices' => [
                    ['message' => ['content' => $content]]
                ]
            ];
        }

        error_log("[{$this->name}] Unexpected response structure: " . substr($response, 0, 300));
        return ['error' => "Invalid LLM response ({$this->name}): " . substr($response, 0, 500)];
    }

    /**
     * Call LLM and extract a JSON structure from the response.
     * Implements retry logic with progressively stricter prompting.
     * 
     * @param string $prompt The user prompt requesting JSON output
     * @param array $options LLM options (see callLLM)
     * @param int $maxRetries Maximum number of retry attempts
     * @return array Decoded JSON data or ['error' => string]
     */
    protected function callLLMForJSON(string $prompt, array $options = [], int $maxRetries = 2): array
    {
        $options['temperature'] = $options['temperature'] ?? 0.4; // Lower temperature for structured output
        // Ask the server for a JSON object (OpenAI / Ollama / Groq all support it); LLM_JSON_MODE=0 turns it off
        $options['json_mode'] = $options['json_mode'] ?? ($this->config['llm']['json_mode'] ?? true);

        // Track retries for logging
        $totalRetries = 0;
        $logEntryId = null;

        // Start logging for this JSON call
        if ($this->loggingEnabled && $this->logger) {
            // Prepare request data for logging
            $baseUrl = $this->config['llm']['base_url'] ?? 'http://host.docker.internal:11434/v1';
            $model = $this->config['llm']['model'] ?? 'gemma4:26b';
            $systemPrompt = $options['system_prompt_override'] ?? $this->buildSystemPrompt();

            $data = [
                'model' => $model,
                'messages' => [
                    ['role' => 'system', 'content' => $systemPrompt],
                    ['role' => 'user', 'content' => $prompt]
                ],
                'temperature' => $options['temperature'],
                'response_format' => ['type' => 'json_object'],
            ];

            $logEntryId = $this->logger->startLogEntry($this->name . '::JSON', $data);
        }

        for ($attempt = 0; $attempt <= $maxRetries; $attempt++) {
            $currentPrompt = $prompt;

            // On retries, add stronger JSON enforcement
            if ($attempt > 0) {
                $totalRetries++;
                $currentPrompt .= "\n\n⚠️ CRITICAL: Your previous response was not valid JSON. " .
                    "You MUST respond with ONLY a valid JSON structure. " .
                    "No markdown, no code fences, no explanatory text. " .
                    "Start your response with [ or { and end with ] or }.";
                $options['temperature'] = max(0.1, ($options['temperature'] ?? 0.4) - 0.1);
            }

            $response = $this->callLLM($currentPrompt, $options);

            if (isset($response['error'])) {
                // Log error and return
                if ($this->loggingEnabled && $this->logger && $logEntryId) {
                    $this->logger->completeLogEntry(
                        $logEntryId,
                        ['error' => $response['error']],
                        0,
                        $totalRetries,
                        $response['error']
                    );
                }
                return $response;
            }

            $content = $this->getContent($response);
            $parsed = $this->extractJSON($content);

            if ($parsed !== null) {
                // Log success
                if ($this->loggingEnabled && $this->logger && $logEntryId) {
                    $this->logger->completeLogEntry(
                        $logEntryId,
                        [
                            'choices' => [
                                ['message' => ['content' => json_encode(['data' => $parsed, 'raw' => $content])]]
                            ]
                        ],
                        200,
                        $totalRetries,
                        null
                    );
                }
                return ['data' => $parsed, 'raw' => $content];
            }
        }

        // All retries exhausted - log final failure
        if ($this->loggingEnabled && $this->logger && $logEntryId) {
            $this->logger->completeLogEntry(
                $logEntryId,
                ['error' => "Failed to extract valid JSON after " . ($maxRetries + 1) . " attempts"],
                0,
                $totalRetries,
                "JSON extraction failed after {$totalRetries} retries"
            );
        }

        return [
            'error' => "Failed to extract valid JSON after " . ($maxRetries + 1) . " attempts from {$this->name}",
            'raw' => $content ?? ''
        ];
    }

    /**
     * Get the logger instance
     * 
     * @return AILogger|null
     */
    public function getLogger(): ?AILogger
    {
        return $this->logger;
    }

    /**
     * Extract JSON from LLM response text.
     * Handles markdown code blocks, mixed text, and common formatting issues.
     */
    protected function extractJSON(string $text): ?array
    {
        $text = trim($text);

        // Strip thinking-model reasoning blocks (<think>...</think>, <thinking>...</thinking>)
        // emitted by models like gemma4, deepseek-r1, qwen3 before the actual response.
        $text = preg_replace('/<think(?:ing)?>[\s\S]*?<\/think(?:ing)?>/i', '', $text);
        $text = trim($text);

        // Strategy 1: Try direct parse (cleanest case)
        $decoded = json_decode($text, true);
        if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
            return $decoded;
        }

        // Strategy 2: Extract from markdown code fence
        if (preg_match('/```(?:json)?\s*\n?([\s\S]*?)\n?\s*```/', $text, $matches)) {
            $decoded = json_decode(trim($matches[1]), true);
            if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
                return $decoded;
            }
        }

        // Strategy 3: Find JSON array in text
        if (preg_match('/(\[\s*\{[\s\S]*\}\s*\])/', $text, $matches)) {
            $decoded = json_decode($matches[1], true);
            if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
                return $decoded;
            }
        }

        // Strategy 4: Find JSON object in text
        if (preg_match('/(\{\s*"[\s\S]*\})/', $text, $matches)) {
            $decoded = json_decode($matches[1], true);
            if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
                return $decoded;
            }
        }

        // Strategy 5: Try to fix common issues (trailing commas, single quotes)
        $cleaned = preg_replace('/,\s*([\]}])/', '$1', $text); // Remove trailing commas
        $decoded = json_decode($cleaned, true);
        if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
            return $decoded;
        }

        return null;
    }

    /**
     * Add a tool to the agent (for NanoAgent integration)
     */
    public function addTool($tool): void
    {
        if ($this->agent) {
            $this->agent->addTool($tool);
        }
    }

    /**
     * Reset the conversation history
     */
    public function resetHistory(): void
    {
        $this->conversationHistory = [];
        if ($this->agent) {
            $this->agent->resetHistory();
        }
    }

    /**
     * Price with enough decimals for its magnitude (BTC 2, DOGE 5, PEPE 10).
     */
    public static function fmtPrice($value): string
    {
        if ($value === null || $value === '' || !is_numeric($value)) {
            return 'n/a';
        }
        $v = (float) $value;
        $abs = abs($v);
        $decimals = $abs >= 1000 ? 2 : ($abs >= 1 ? 4 : ($abs > 0 ? min(10, 4 + (int) ceil(-log10($abs))) : 2));
        return rtrim(rtrim(number_format($v, $decimals, '.', ''), '0'), '.') ?: '0';
    }

    /**
     * Get response content from LLM response
     */
    protected function getContent(array $llmResponse): string
    {
        return $llmResponse['choices'][0]['message']['content'] ?? '';
    }

    /**
     * Log a message for debugging (can be extended for structured logging)
     */
    protected function log(string $message): void
    {
        error_log("[{$this->name}] {$message}");
    }
}
