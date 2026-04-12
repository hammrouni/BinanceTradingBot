<?php
/**
 * AI Call Logger
 * 
 * Comprehensive JSON logging for AI agent interactions.
 * Captures complete request payload, response data, timestamps,
 * agent identifier, and execution metadata.
 */

namespace App\Agents;

class AILogger
{
    private string $logDirectory;
    private string $currentLogFile;
    private ?array $currentLogEntry = null;
    
    /**
     * Constructor
     * 
     * @param string|null $logDirectory Override default log directory
     */
    public function __construct(?string $logDirectory = null)
    {
        $this->logDirectory = $logDirectory ?? $this->getDefaultLogDirectory();
        $this->ensureLogDirectoryExists();
    }
    
    /**
     * Get default log directory from config
     */
    private function getDefaultLogDirectory(): string
    {
        $config = $this->loadConfig();
        $projectsDir = $config['storage']['projects_dir'] ?? '/data/projects';
        return $projectsDir . '/ai-logs';
    }
    
    /**
     * Load configuration
     */
    private function loadConfig(): array
    {
        $configPath = __DIR__ . '/../config.php';
        if (file_exists($configPath)) {
            return require $configPath;
        }
        return [];
    }
    
    /**
     * Ensure log directory exists
     */
    private function ensureLogDirectoryExists(): void
    {
        if (!is_dir($this->logDirectory)) {
            mkdir($this->logDirectory, 0755, true);
        }
    }
    
    /**
     * Start a new log entry for an AI call
     * 
     * @param string $agentName The agent class name making the call
     * @param array $requestPayload The complete request payload
     * @return string The log entry ID
     */
    public function startLogEntry(string $agentName, array $requestPayload): string
    {
        $entryId = $this->generateEntryId();
        $timestamp = microtime(true);
        
        // Extract model from payload
        $model = $requestPayload['model'] ?? 'unknown';
        
        // Create the initial log entry
        $this->currentLogEntry = [
            'id' => $entryId,
            'agent' => [
                'name' => $agentName,
                'class' => $agentName,
            ],
            'timestamp' => [
                'started_at' => date('c', (int)$timestamp),
                'started_at_unix' => $timestamp,
            ],
            'request' => [
                'model' => $model,
                'messages' => $this->sanitizeMessages($requestPayload['messages'] ?? []),
                'temperature' => $requestPayload['temperature'] ?? 0.7,
                'max_tokens' => $requestPayload['max_tokens'] ?? null,
                'response_format' => $requestPayload['response_format'] ?? null,
            ],
            'response' => null,
            'execution' => [
                'duration_ms' => null,
                'http_status' => null,
                'retries' => 0,
                'error' => null,
            ],
            'metadata' => [
                'environment' => $this->getEnvironmentInfo(),
                'server' => $this->getServerInfo(),
                'client_ip' => $this->getClientIP(),
            ],
        ];
        
        $this->currentLogFile = $this->logDirectory . '/' . date('Y-m-d') . '.jsonl';
        
        return $entryId;
    }
    
    /**
     * Complete the log entry with response data
     * 
     * @param string $entryId The log entry ID
     * @param array $response The LLM response
     * @param int $httpStatus HTTP status code
     * @param int $retries Number of retries made
     * @param string|null $error Error message if any
     */
    public function completeLogEntry(
        string $entryId, 
        array $response, 
        int $httpStatus = 200, 
        int $retries = 0,
        ?string $error = null
    ): void {
        if (!isset($this->currentLogEntry) || $this->currentLogEntry['id'] !== $entryId) {
            return;
        }
        
        $timestamp = microtime(true);
        $startTime = $this->currentLogEntry['timestamp']['started_at_unix'];
        $durationMs = round(($timestamp - $startTime) * 1000, 2);
        
        // Update execution metadata
        $this->currentLogEntry['execution'] = [
            'duration_ms' => $durationMs,
            'http_status' => $httpStatus,
            'retries' => $retries,
            'error' => $error,
            'completed_at' => date('c', (int)$timestamp),
            'completed_at_unix' => $timestamp,
        ];
        
        // Add response data (sanitized)
        $this->currentLogEntry['response'] = $this->sanitizeResponse($response);
        
        // Write the log entry
        $this->writeLogEntry();
        
        // Clear current entry
        $this->currentLogEntry = null;
    }
    
    /**
     * Write log entry to JSONL file
     */
    private function writeLogEntry(): void
    {
        if (empty($this->currentLogEntry)) {
            return;
        }
        
        $jsonLine = json_encode($this->currentLogEntry, JSON_UNESCAPED_UNICODE);
        file_put_contents($this->currentLogFile, $jsonLine . "\n", FILE_APPEND | LOCK_EX);
    }
    
    /**
     * Generate unique entry ID
     */
    private function generateEntryId(): string
    {
        return bin2hex(random_bytes(8));
    }
    
    /**
     * Sanitize messages to remove sensitive data
     */
    private function sanitizeMessages(array $messages): array
    {
        return array_map(function($msg) {
            return [
                'role' => $msg['role'] ?? 'unknown',
                'content' => $this->truncateContent($msg['content'] ?? ''),
            ];
        }, $messages);
    }
    
    /**
     * Truncate content for log efficiency
     */
    private function truncateContent(string $content, int $maxLength = 5000): string
    {
        if (strlen($content) > $maxLength) {
            return substr($content, 0, $maxLength) . "\n... [truncated]";
        }
        return $content;
    }
    
    /**
     * Sanitize response data
     */
    private function sanitizeResponse(array $response): array
    {
        if (isset($response['error'])) {
            return [
                'error' => true,
                'message' => $response['error'],
            ];
        }
        
        $sanitized = [
            'has_content' => isset($response['choices'][0]['message']['content']),
        ];
        
        if (isset($response['choices'][0]['message']['content'])) {
            $content = $response['choices'][0]['message']['content'];
            $sanitized['content'] = $this->truncateContent($content);
            $sanitized['content_length'] = strlen($content);
            if ($content === '') {
                $sanitized['content_empty_warning'] = 'Model returned empty content — likely hit max_tokens during thinking.';
            }
        }

        if (isset($response['usage'])) {
            $sanitized['token_budget'] = [
                'prompt'     => $response['usage']['prompt_tokens']     ?? null,
                'completion' => $response['usage']['completion_tokens'] ?? null,
                'total'      => $response['usage']['total_tokens']      ?? null,
            ];
        }
        
        if (isset($response['model'])) {
            $sanitized['model'] = $response['model'];
        }
        
        return $sanitized;
    }
    
    /**
     * Get environment information
     */
    private function getEnvironmentInfo(): array
    {
        return [
            'php_version' => PHP_VERSION,
            'os' => PHP_OS,
            'memory_limit' => ini_get('memory_limit'),
            'max_execution_time' => ini_get('max_execution_time'),
        ];
    }
    
    /**
     * Get server information
     */
    private function getServerInfo(): array
    {
        return [
            'hostname' => gethostname() ?: 'unknown',
            'server_software' => $_SERVER['SERVER_SOFTWARE'] ?? 'unknown',
            'document_root' => $_SERVER['DOCUMENT_ROOT'] ?? 'unknown',
        ];
    }
    
    /**
     * Get client IP address
     */
    private function getClientIP(): string
    {
        $headers = [
            'HTTP_CF_CONNECTING_IP',
            'HTTP_X_FORWARDED_FOR',
            'HTTP_X_FORWARDED',
            'HTTP_FORWARDED_FOR',
            'HTTP_FORWARDED',
            'REMOTE_ADDR',
        ];
        
        foreach ($headers as $header) {
            if (!empty($_SERVER[$header])) {
                $ip = $_SERVER[$header];
                if (strpos($ip, ',') !== false) {
                    $ip = trim(explode(',', $ip)[0]);
                }
                return $ip;
            }
        }
        
        return 'unknown';
    }
    
    /**
     * Get all log files
     * 
     * @return array Array of log file info
     */
    public function getLogFiles(): array
    {
        $files = glob($this->logDirectory . '/*.jsonl');
        $result = [];
        
        foreach ($files as $file) {
            $stat = stat($file);
            $result[] = [
                'filename' => basename($file),
                'path' => $file,
                'size' => $stat['size'],
                'modified' => date('c', $stat['mtime']),
                'entries' => $this->countEntries($file),
            ];
        }
        
        return $result;
    }
    
    /**
     * Count entries in a log file
     */
    private function countEntries(string $file): int
    {
        $count = 0;
        $handle = fopen($file, 'r');
        if ($handle) {
            while (!feof($handle)) {
                $line = fgets($handle);
                if (!empty(trim($line))) {
                    $count++;
                }
            }
            fclose($handle);
        }
        return $count;
    }
    
    /**
     * Get logs with optional filtering
     * 
     * @param array $filters Filter options
     * @return array Filtered log entries
     */
    public function getLogs(array $filters = []): array
    {
        $logs = [];
        $files = $filters['files'] ?? null;
        
        if ($files === 'all') {
            $logFiles = glob($this->logDirectory . '/*.jsonl');
        } elseif ($files) {
            $logFiles = is_array($files) ? $files : [$files];
        } else {
            // Default: today's logs
            $logFiles = [$this->logDirectory . '/' . date('Y-m-d') . '.jsonl'];
        }
        
        $limit = $filters['limit'] ?? 50;
        $offset = $filters['offset'] ?? 0;
        $agentFilter = $filters['agent'] ?? null;
        $search = $filters['search'] ?? null;
        
        foreach ($logFiles as $file) {
            if (!file_exists($file)) {
                continue;
            }
            
            $handle = fopen($file, 'r');
            if (!$handle) {
                continue;
            }
            
            while (!feof($handle) && count($logs) < ($offset + $limit)) {
                $line = fgets($handle);
                if (empty(trim($line))) {
                    continue;
                }
                
                $entry = json_decode($line, true);
                if (!$entry) {
                    continue;
                }
                
                // Apply filters
                if ($agentFilter && ($entry['agent']['name'] ?? '') !== $agentFilter) {
                    continue;
                }
                
                if ($search) {
                    $searchLower = strtolower($search);
                    $content = strtolower(json_encode($entry));
                    if (strpos($content, $searchLower) === false) {
                        continue;
                    }
                }
                
                $logs[] = $entry;
            }
            
            fclose($handle);
        }
        
        // Apply pagination
        return array_slice($logs, $offset, $limit);
    }
    
    /**
     * Get log entry by ID
     * 
     * @param string $entryId The log entry ID
     * @return array|null The log entry or null
     */
    public function getLogById(string $entryId): ?array
    {
        $files = glob($this->logDirectory . '/*.jsonl');
        
        foreach ($files as $file) {
            $handle = fopen($file, 'r');
            if (!$handle) {
                continue;
            }
            
            while (!feof($handle)) {
                $line = fgets($handle);
                if (empty(trim($line))) {
                    continue;
                }
                
                $entry = json_decode($line, true);
                if ($entry && ($entry['id'] ?? '') === $entryId) {
                    fclose($handle);
                    return $entry;
                }
            }
            
            fclose($handle);
        }
        
        return null;
    }
    
    /**
     * Get unique agent names from logs
     * 
     * @return array List of unique agent names
     */
    public function getAgentNames(): array
    {
        $agents = [];
        $files = glob($this->logDirectory . '/*.jsonl');
        
        foreach ($files as $file) {
            $handle = fopen($file, 'r');
            if (!$handle) {
                continue;
            }
            
            while (!feof($handle)) {
                $line = fgets($handle);
                if (empty(trim($line))) {
                    continue;
                }
                
                $entry = json_decode($line, true);
                if ($entry && !empty($entry['agent']['name'])) {
                    $agents[$entry['agent']['name']] = true;
                }
            }
            
            fclose($handle);
        }
        
        return array_keys($agents);
    }
    
    /**
     * Get statistics from logs
     * 
     * @param string|null $date Date to get stats for (Y-m-d format)
     * @return array Statistics
     */
    public function getStats(?string $date = null): array
    {
        $date = $date ?? date('Y-m-d');
        $file = $this->logDirectory . '/' . $date . '.jsonl';
        
        if (!file_exists($file)) {
            return [
                'date' => $date,
                'total_calls' => 0,
                'by_agent' => [],
                'avg_duration_ms' => 0,
                'errors' => 0,
            ];
        }
        
        $stats = [
            'date' => $date,
            'total_calls' => 0,
            'by_agent' => [],
            'avg_duration_ms' => 0,
            'total_duration_ms' => 0,
            'errors' => 0,
        ];
        
        $handle = fopen($file, 'r');
        if (!$handle) {
            return $stats;
        }
        
        while (!feof($handle)) {
            $line = fgets($handle);
            if (empty(trim($line))) {
                continue;
            }
            
            $entry = json_decode($line, true);
            if (!$entry) {
                continue;
            }
            
            $stats['total_calls']++;
            
            $agentName = $entry['agent']['name'] ?? 'unknown';
            if (!isset($stats['by_agent'][$agentName])) {
                $stats['by_agent'][$agentName] = [
                    'calls' => 0,
                    'total_duration_ms' => 0,
                    'errors' => 0,
                ];
            }
            
            $stats['by_agent'][$agentName]['calls']++;
            
            $duration = $entry['execution']['duration_ms'] ?? 0;
            if ($duration) {
                $stats['total_duration_ms'] += $duration;
                $stats['by_agent'][$agentName]['total_duration_ms'] += $duration;
            }
            
            $error = $entry['execution']['error'] ?? null;
            if ($error || !empty($entry['response']['error'])) {
                $stats['errors']++;
                $stats['by_agent'][$agentName]['errors']++;
            }
        }
        
        fclose($handle);
        
        if ($stats['total_calls'] > 0) {
            $stats['avg_duration_ms'] = round($stats['total_duration_ms'] / $stats['total_calls'], 2);
        }
        
        foreach ($stats['by_agent'] as $agent => &$agentStats) {
            if ($agentStats['calls'] > 0) {
                $agentStats['avg_duration_ms'] = round($agentStats['total_duration_ms'] / $agentStats['calls'], 2);
            }
        }
        
        return $stats;
    }
    
    /**
     * Delete old log files (cleanup)
     * 
     * @param int $daysToKeep Number of days to keep
     * @return int Number of files deleted
     */
    public function cleanup(int $daysToKeep = 30): int
    {
        $deleted = 0;
        $cutoff = strtotime("-{$daysToKeep} days");
        $files = glob($this->logDirectory . '/*.jsonl');
        
        foreach ($files as $file) {
            if (filemtime($file) < $cutoff) {
                if (unlink($file)) {
                    $deleted++;
                }
            }
        }
        
        return $deleted;
    }
}
