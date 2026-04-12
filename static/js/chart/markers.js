/**
 * markers.js — Logic for drawing signals, SL/TP lines, and markers on the chart.
 */

import { state } from './state.js';
import { renderView } from './rendering.js';

export function markBuySignal(price, isTest = false, amount = null, reason = null) {
    if (!state.buf.ts.length) return;
    const now = Date.now();
    const candleMs = 60 * 1000;
    const lastTs = state.buf.ts[state.buf.ts.length - 1];
    const lastClosedTs = lastTs && (now - lastTs) >= candleMs ? lastTs : (state.buf.ts.length > 1 ? state.buf.ts[state.buf.ts.length - 2] : null);
    const i = lastClosedTs ? state.buf.ts.indexOf(lastClosedTs) : state.buf.ts.length - 1;
    if (isTest) {
        state.buf.testBuy[i] = price;
        state.buf.testBuyPrice[i] = price;
        state.buf.testBuyAmount[i] = amount;
        state.buf.testBuyReason[i] = reason;
    } else {
        state.buf.buy[i] = price;
        state.buf.buyPrice[i] = price;
        state.buf.buyAmount[i] = amount;
        state.buf.buyReason[i] = reason;
    }
    renderView();
}

export function markSellSignal(price, isTest = false, amount = null, reason = null) {
    if (!state.buf.ts.length) return;
    const now = Date.now();
    const candleMs = 60 * 1000;
    const lastTs = state.buf.ts[state.buf.ts.length - 1];
    const lastClosedTs = lastTs && (now - lastTs) >= candleMs ? lastTs : (state.buf.ts.length > 1 ? state.buf.ts[state.buf.ts.length - 2] : null);
    const i = lastClosedTs ? state.buf.ts.indexOf(lastClosedTs) : state.buf.ts.length - 1;
    if (isTest) {
        state.buf.testSell[i] = price;
        state.buf.testSellPrice[i] = price;
        state.buf.testSellAmount[i] = amount;
        state.buf.testSellReason[i] = reason;
    } else {
        state.buf.sell[i] = price;
        state.buf.sellPrice[i] = price;
        state.buf.sellAmount[i] = amount;
        state.buf.sellReason[i] = reason;
    }
    renderView();
}

/** 
 * Marker for simulation results or historical trade viewing. 
 * Finds the closest candle to the timestamp and plots a marker.
 */
export function markSignalAtTime(isoTimestamp, direction, price, isTest = false, amount = null, reason = null) {
    if (!isoTimestamp || !state.buf.ts.length) return;
    const ms = new Date(isoTimestamp).getTime();
    const now = Date.now();
    const candleMs = 60 * 1000;
    let closestIdx = -1, minDiff = Infinity;
    const lastTs = state.buf.ts[state.buf.ts.length - 1];
    const searchLimit = (lastTs && (now - lastTs) >= candleMs) ? state.buf.ts.length : state.buf.ts.length - 1;
    for (let i = 0; i < searchLimit; i++) {
        const t = state.buf.ts[i];
        if (t == null) continue;
        const d = Math.abs(t - ms);
        if (d < minDiff) { minDiff = d; closestIdx = i; }
    }
    if (closestIdx < 0) return;
    if (direction === 'sell') {
        if (isTest) {
            state.buf.testSell[closestIdx] = price;
            state.buf.testSellPrice[closestIdx] = price;
            state.buf.testSellAmount[closestIdx] = amount;
            state.buf.testSellReason[closestIdx] = reason;
        } else {
            state.buf.sell[closestIdx] = price;
            state.buf.sellPrice[closestIdx] = price;
            state.buf.sellAmount[closestIdx] = amount;
            state.buf.sellReason[closestIdx] = reason;
        }
    } else {
        if (isTest) {
            state.buf.testBuy[closestIdx] = price;
            state.buf.testBuyPrice[closestIdx] = price;
            state.buf.testBuyAmount[closestIdx] = amount;
            state.buf.testBuyReason[closestIdx] = reason;
        } else {
            state.buf.buy[closestIdx] = price;
            state.buf.buyPrice[closestIdx] = price;
            state.buf.buyAmount[closestIdx] = amount;
            state.buf.buyReason[closestIdx] = reason;
        }
    }
    renderView();
}

export function markCandleBuy(tsMs,  price, amount = null, reason = null) { markSignalAtTime(new Date(tsMs).toISOString(), 'buy',  price, false, amount, reason); }
export function markCandleSell(tsMs, price, amount = null, reason = null) { markSignalAtTime(new Date(tsMs).toISOString(), 'sell', price, false, amount, reason); }

export function updateChartWithPosition(pos) {
    if (!pos) {
        clearOpenPositionFromChart();
        return;
    }
    state.currentTpPrice = pos.take_profit_price ?? null;
    state.currentSlPrice = pos.stop_loss_price ?? null;
    state.currentEntryPrice = pos.entry_price ?? null;
    renderView();
}

export function clearOpenPositionFromChart() {
    state.currentTpPrice = null;
    state.currentSlPrice = null;
    state.currentEntryPrice = null;
    state.currentOpenPositionBuy = null;
    renderView();
}
