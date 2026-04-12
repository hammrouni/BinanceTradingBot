/**
 * state.js — Simulator-specific state management.
 */

export const state = {
    pendingApplyResult: null,
    marketHistory: [],
    lastSimResults: [],
    // Cache for historical market data
    cachedMarketHistory: {
        data: null,
        timestamp: null,
        symbol: null,
        days: null
    }
};

export function updateState(key, val) {
    state[key] = val;
    // Notify any listeners if needed in the future
}

// Cache management functions
export function cacheMarketHistory(data, symbol, days) {
    state.cachedMarketHistory = {
        data: data,
        timestamp: Date.now(),
        symbol: symbol,
        days: days
    };
    // Also save to localStorage for persistence across reloads
    try {
        localStorage.setItem(
            `binanceTradingBot_marketHistory_${symbol}_${days}d`,
            JSON.stringify({
                data: data,
                timestamp: Date.now()
            })
        );
    } catch (e) {
        console.warn('Failed to cache market history to localStorage', e);
    }
}

export function getCachedMarketHistory(symbol, days, maxAgeMs = 5 * 60 * 1000) { // 5 minutes max age
    // First check memory cache
    if (state.cachedMarketHistory.data &&
        state.cachedMarketHistory.symbol === symbol &&
        state.cachedMarketHistory.days === days &&
        (Date.now() - state.cachedMarketHistory.timestamp) < maxAgeMs) {
        return state.cachedMarketHistory.data;
    }

    // Then check localStorage
    try {
        const cached = localStorage.getItem(`binanceTradingBot_marketHistory_${symbol}_${days}d`);
        if (cached) {
            const parsed = JSON.parse(cached);
            if ((Date.now() - parsed.timestamp) < maxAgeMs) {
                // Restore to memory cache
                state.cachedMarketHistory = {
                    data: parsed.data,
                    timestamp: parsed.timestamp,
                    symbol: symbol,
                    days: days
                };
                return parsed.data;
            }
        }
    } catch (e) {
        console.warn('Failed to read market history from localStorage', e);
    }

    return null;
}
