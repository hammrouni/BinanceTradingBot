/**
 * api.js — Public API functions for the modular chart.
 */

import { state, MAX_BUFFER, MAX_CANDLES, saveThresholdHistory } from './state.js';
import { renderView } from './rendering.js';

export function setChartInterval(minutes) {
    state.viewMinutes = minutes;
    renderView();
    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        const raw = btn.dataset.minutes;
        btn.classList.toggle('active', minutes === null ? raw === 'all' : Number(raw) === minutes);
    });
}

export function setRsiHistory(points) {
    if (!points || !Array.isArray(points)) return;
    state.buf.ts = []; state.buf.rsi = []; state.buf.rsiUltraRaw = []; state.buf.rsiUltraSignal = [];
    state.buf.buy = []; state.buf.sell = []; state.buf.buyPrice = []; state.buf.sellPrice = [];
    state.buf.buyAmount = []; state.buf.sellAmount = [];
    state.buf.testBuy = []; state.buf.testSell = []; state.buf.testBuyPrice = []; state.buf.testSellPrice = [];
    state.buf.testBuyAmount = []; state.buf.testSellAmount = [];
    state.buf.buyReason = []; state.buf.sellReason = []; state.buf.testBuyReason = []; state.buf.testSellReason = [];

    // Rebuild candles from OHLC fields so the price chart shows history
    state.candles = [];

    points.forEach(p => {
        const ts = p.timestamp ? new Date(p.timestamp).getTime() : null;
        state.buf.ts.push(ts);
        state.buf.rsi.push(p.rsi);
        state.buf.rsiUltraRaw.push(p.rsi_ultra_raw ?? null);
        state.buf.rsiUltraSignal.push(p.rsi_ultra_signal ?? null);
        state.buf.buy.push(null); state.buf.sell.push(null);
        state.buf.buyPrice.push(null); state.buf.sellPrice.push(null);
        state.buf.buyAmount.push(null); state.buf.sellAmount.push(null);
        state.buf.testBuy.push(null); state.buf.testSell.push(null);
        state.buf.testBuyPrice.push(null); state.buf.testSellPrice.push(null);
        state.buf.testBuyAmount.push(null); state.buf.testSellAmount.push(null);
        state.buf.buyReason.push(null); state.buf.sellReason.push(null);
        state.buf.testBuyReason.push(null); state.buf.testSellReason.push(null);

        if (p.price != null && ts != null) {
            state.candles.push({
                x: ts,
                o: p.open  ?? p.price,
                h: p.high  ?? p.price,
                l: p.low   ?? p.price,
                c: p.price,
            });
        }
    });
    renderView();
}

export function updateRsiChart(rsiValue, timestamp, priceValue = null) {
    if (!state.rsiChart || rsiValue == null) return;
    state.buf.ts.push(timestamp ? new Date(timestamp).getTime() : null);
    state.buf.rsi.push(rsiValue);
    state.buf.rsiUltraRaw.push(null);
    state.buf.rsiUltraSignal.push(null);
    state.buf.buy.push(null); state.buf.sell.push(null);
    state.buf.buyPrice.push(null); state.buf.sellPrice.push(null);
    state.buf.buyAmount.push(null); state.buf.sellAmount.push(null);
    state.buf.testBuy.push(null); state.buf.testSell.push(null);
    state.buf.testBuyPrice.push(null); state.buf.testSellPrice.push(null);
    state.buf.testBuyAmount.push(null); state.buf.testSellAmount.push(null);
    state.buf.buyReason.push(null); state.buf.sellReason.push(null);
    state.buf.testBuyReason.push(null); state.buf.testSellReason.push(null);
    if (state.buf.ts.length > MAX_BUFFER) {
        ['ts','rsi','rsiUltraRaw','rsiUltraSignal','buy','sell','buyPrice','sellPrice','buyAmount','sellAmount',
         'testBuy','testSell','testBuyPrice','testSellPrice','testBuyAmount','testSellAmount',
         'buyReason','sellReason','testBuyReason','testSellReason']
            .forEach(k => state.buf[k].shift());
    }
    renderView();
}

export function updateRsiUltraChart(raw, signal, timestamp) {
    if (!state.rsiChart) return;
    const ts = timestamp ? new Date(timestamp).getTime() : Date.now();
    state.buf.ts.push(ts);
    state.buf.rsi.push(null);
    state.buf.rsiUltraRaw.push(raw);
    state.buf.rsiUltraSignal.push(signal);
    state.buf.buy.push(null); state.buf.sell.push(null);
    state.buf.buyPrice.push(null); state.buf.sellPrice.push(null);
    state.buf.buyAmount.push(null); state.buf.sellAmount.push(null);
    state.buf.testBuy.push(null); state.buf.testSell.push(null);
    state.buf.testBuyPrice.push(null); state.buf.testSellPrice.push(null);
    state.buf.testBuyAmount.push(null); state.buf.testSellAmount.push(null);
    state.buf.buyReason.push(null); state.buf.sellReason.push(null);
    state.buf.testBuyReason.push(null); state.buf.testSellReason.push(null);

    // Keep buffers in sync
    if (state.buf.ts.length > MAX_BUFFER) {
        ['ts','rsi','rsiUltraRaw','rsiUltraSignal','buy','sell','buyPrice','sellPrice','buyAmount','sellAmount',
         'testBuy','testSell','testBuyPrice','testSellPrice','testBuyAmount','testSellAmount',
         'buyReason','sellReason','testBuyReason','testSellReason']
            .forEach(k => state.buf[k].shift());
    }
    renderView();
}

export function updateChartSl(price) { state.currentSlPrice = price; renderView(); }
export function updateChartTp(price) { state.currentTpPrice = price; renderView(); }
export function updateChartEntry(price) { state.currentEntryPrice = price; renderView(); }
export function updateChartOpenPositionBuy(price) { state.currentOpenPositionBuy = price; renderView(); }
export function updateChartBcPrice(price) { state.currentBcPrice = price; renderView(); }
export function updateChartBcSellPrice(price) { state.currentBcSellPrice = price; renderView(); }

export function updateChartModeVisibility(mode) {
    state.chartMode = (mode === 'BC' || mode === 'RSI_ULTRA') ? mode : 'RSI';
    renderView();
}

export function updateCandleChart(candles) {
    state.candles = candles.slice(-MAX_CANDLES);
    renderView();
}

export function upsertCandle(candle) {
    const last = state.candles[state.candles.length - 1];
    if (last && last.x === candle.x) { state.candles[state.candles.length - 1] = candle; }
    else { state.candles.push(candle); if (state.candles.length > MAX_CANDLES) state.candles.shift(); }
    renderView();
}

export function updateChartThresholds(oversold, overbought) {
    state.currentOversold = oversold; state.currentOverbought = overbought; renderView();
}

export function recordRsiThresholdChange(oversold, overbought) {
    const now = Date.now();
    if (oversold != null)   state.buf.rsiThresholdHistory.oversold.push({ ts: now, val: oversold });
    if (overbought != null) state.buf.rsiThresholdHistory.overbought.push({ ts: now, val: overbought });
    state.currentOversold   = oversold   ?? state.currentOversold;
    state.currentOverbought = overbought ?? state.currentOverbought;
    saveThresholdHistory();
    renderView();
}

export function setRsiThresholdHistory(history) {
    if (!history || !Array.isArray(history)) return;
    state.buf.rsiThresholdHistory.oversold = history
        .filter(h=>h.type==='oversold').map(h=>({ts:new Date(h.timestamp).getTime(),val:h.value})).sort((a,b)=>a.ts-b.ts);
    state.buf.rsiThresholdHistory.overbought = history
        .filter(h=>h.type==='overbought').map(h=>({ts:new Date(h.timestamp).getTime(),val:h.value})).sort((a,b)=>a.ts-b.ts);
    renderView();
}

export function getLatestRsi() {
    if (!state.buf.rsi || state.buf.rsi.length === 0) return null;
    return state.buf.rsi[state.buf.rsi.length - 1];
}

export function getLatestPrice() {
    if (!state.candles || state.candles.length === 0) return null;
    const last = state.candles[state.candles.length - 1];
    return last.c;
}

export function getRecentCandles(n = 20) {
    if (!state.candles || state.candles.length === 0) return [];
    return state.candles.slice(-n).map(c => ({
        open:   c.o,
        high:   c.h,
        low:    c.l,
        close:  c.c,
        time:   c.x,
    }));
}

export function setChartHideTestData(hide) {
    state.hideTestData = hide;
    renderView();
}

export function setChartEnv(isLive) {
    state.hideTestData = isLive;
    renderView();
}

export function setMarkerVisibility(env) {
    if (env === 'live') {
        state.hideTestData = true;
        state.hideProdData = false;
    } else {
        state.hideTestData = false;
        state.hideProdData = true;
    }
    renderView();
}
