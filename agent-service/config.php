<?php
/**
 * Agent Service Configuration
 */

// Helper function to get env var (checks both getenv and $_ENV)
// Only declare if not already declared
if (!function_exists('getEnvVar')) {
    function getEnvVar($name, $default = '')
    {
        $value = getenv($name);
        if ($value === false) {
            $value = $_ENV[$name] ?? $default;
        }
        return $value;
    }
}

return [
    // LLM Configuration
    'llm' => [
        'base_url' => getEnvVar('LLM_BASE_URL', 'http://host.docker.internal:11434/v1'),
        'api_key' => getEnvVar('LLM_API_KEY', ''),
        'provider' => getEnvVar('LLM_PROVIDER', 'openai'),
        'model' => getEnvVar('LLM_MODEL', 'gemma4:26b'),
        'timeout' => (int) getEnvVar('LLM_TIMEOUT', '600'),
        'max_tokens' => (int) getEnvVar('LLM_MAX_TOKENS', '16384'),
    ],

    // Storage Configuration
    'storage' => [
        'projects_dir' => getEnvVar('PROJECTS_DIR', '/var/www/html/storage'),
    ],
];
