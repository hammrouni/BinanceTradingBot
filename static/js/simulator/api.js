/**
 * api.js — HTTP requests for the Parameter Simulator.
 */

export async function fetchSimulatorData(params) {
    const response = await fetch('/api/v1/simulator/data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
    });
    return response.json();
}

export async function runSimulationSweep(params) {
    const response = await fetch('/api/v1/simulator/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
    });
    return response.json();
}

export async function runCurrentConfigSim(days, initialBalance, feePct) {
    const response = await fetch('/api/v1/simulator/run-current', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            historical_days: days,
            initial_balance: initialBalance,
            fee_pct: feePct,
        }),
    });
    return response.json();
}

export async function fetchSimulationTrades(replayRequest) {
    const response = await fetch('/api/v1/simulator/trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(replayRequest),
    });
    return response.json();
}

export async function getBotConfig() {
    return fetch('/api/v1/config').then(r => r.json());
}

export async function updateBotConfig(newConfig) {
    return fetch('/api/v1/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
    });
}

export async function getBotStatus() {
    return fetch('/api/v1/status').then(r => r.json());
}
