// api.js — fetch() wrappers for REST endpoints

async function getConfig() {
    const res = await fetch('/api/v1/config');
    if (!res.ok) throw new Error('Failed to load config');
    const body = await res.json();
    return body.data;
}

async function updateConfig(data) {
    return fetch('/api/v1/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
}

async function startBot() {
    return fetch('/api/v1/bot/start', { method: 'POST' });
}

async function pauseBot() {
    return fetch('/api/v1/bot/pause', { method: 'POST' });
}

async function resumeBot() {
    return fetch('/api/v1/bot/resume', { method: 'POST' });
}

async function stopBot() {
    return fetch('/api/v1/bot/stop', { method: 'POST' });
}

async function getTrades() {
    const res = await fetch('/api/v1/trades');
    if (!res.ok) throw new Error('Failed to load trades');
    const body = await res.json();
    return body.data;
}

async function getStatus() {
    const res = await fetch('/api/v1/status');
    if (!res.ok) throw new Error('Failed to load status');
    const body = await res.json();
    return body.data;
}

async function getRsiHistory(type = null) {
    let url = '/api/v1/config/rsi-history';
    if (type) url += `?type=${type}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch RSI history');
    const body = await res.json();
    return body.data;
}

async function addRsiHistoryEntry(type, value, timestamp = null) {
    const res = await fetch('/api/v1/config/rsi-history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, value, timestamp }),
    });
    if (!res.ok) throw new Error('Failed to add RSI history entry');
    return res.json();
}

async function clearRsiHistory(type = null) {
    let url = '/api/v1/config/rsi-history';
    if (type) url += `?type=${type}`;
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to clear RSI history');
    return res.json();
}
async function refreshWallet() {
    return fetch('/api/v1/refresh-wallet', { method: 'POST' });
}
