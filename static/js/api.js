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
