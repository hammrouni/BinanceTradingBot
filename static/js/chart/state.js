/**
 * state.js — Shared constants and state for the modular chart.
 */

export const MAX_BUFFER  = 2000;
export const MAX_CANDLES = 1440;

export const REASON_LABEL = {
    'buy_signal':  '📈 RSI Oversold',
    'stop_loss':   '🛑 Stop Loss',
    'take_profit': '🎯 Take Profit',
    'signal':      '📉 RSI Overbought',
    'manual':      '✋ Manual',
    'bc_signal':   '🔵 BC Price',
};

export const state = {
    rsiChart: null,
    currentOversold: 30,
    currentOverbought: 70,
    currentSlPrice: null,
    currentTpPrice: null,
    currentEntryPrice: null,
    currentOpenPositionBuy: null,
    currentBcPrice: null,
    currentBcSellPrice: null,
    chartMode: 'RSI', // 'RSI' or 'BC'
    
    candles: [],
    viewMinutes: 120,
    hideTestData: false,
    hideProdData: false,
    
    buf: {
        ts: [], 
        rsi: [],
        rsiUltraRaw: [],
        rsiUltraSignal: [],
        buy: [], sell: [], buyPrice: [], sellPrice: [], buyAmount: [], sellAmount: [], buyReason: [], sellReason: [],
        testBuy: [], testSell: [], testBuyPrice: [], testSellPrice: [], testBuyAmount: [], testSellAmount: [], testBuyReason: [], testSellReason: [],
        rsiThresholdHistory: { oversold: [], overbought: [] },
    }
};

/** Load the RSI threshold history from local storage. */
export const LS_THRESH_KEY = 'btb_rsiThresholdHistory';

export function loadThresholdHistory() {
    try {
        const raw = localStorage.getItem(LS_THRESH_KEY);
        if (!raw) return;
        const data = JSON.parse(raw);
        const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
        if (Array.isArray(data.oversold))
            state.buf.rsiThresholdHistory.oversold = data.oversold.filter(h => h.ts > cutoff);
        if (Array.isArray(data.overbought))
            state.buf.rsiThresholdHistory.overbought = data.overbought.filter(h => h.ts > cutoff);
    } catch (e) { /* ignore corrupt storage */ }
}

/** Save the RSI threshold history to local storage. */
export function saveThresholdHistory() {
    try {
        const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
        localStorage.setItem(LS_THRESH_KEY, JSON.stringify({
            oversold:   state.buf.rsiThresholdHistory.oversold.filter(h => h.ts > cutoff),
            overbought: state.buf.rsiThresholdHistory.overbought.filter(h => h.ts > cutoff),
        }));
    } catch (e) { /* ignore quota errors */ }
}
