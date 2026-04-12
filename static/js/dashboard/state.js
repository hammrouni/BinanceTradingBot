/**
 * state.js — Centralized frontend state for the BinanceTradingBot.
 * 
 * Using ES Modules to provide a single source of truth for the dashboard.
 */

export const state = {
    openPosition: null,
    prevPrice: null,
    currentConfig: {},
    botState: 'STOPPED',
    startedAt: null,
    totalPnl: 0,
    tradeCount: 0,
    rsiHistoryLoaded: false,
    loadedProdTrades: [],
    loadedTestTrades: [],
    currentBalances: null,
    latestRsi: null,
    latestRsiUltraRaw: null,
    latestRsiUltraSignal: null,
    
    // Internal state for candlestick aggregation
    activeCandleTs: null,
    activeCandle: null,
    
    // UI state
    uptimeInterval: null
};

export function updateState(key, value) {
    state[key] = value;
}

export function resetUptime() {
    if (state.uptimeInterval) {
        clearInterval(state.uptimeInterval);
        state.uptimeInterval = null;
    }
    state.startedAt = null;
}
