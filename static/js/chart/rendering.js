/**
 * rendering.js — View rendering and logic for the BinanceTradingBot chart.
 */

import { state, REASON_LABEL } from './state.js';

/** Format a number for display: commas + fixed decimals. e.g. 67892.82 → "67,892.82" */
export function fmtNum(val, decimals = 2) {
    if (val == null || val === '' || isNaN(Number(val))) return '';
    return Number(val).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

export function fmt(v) {
    return v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

export function generateStepwiseSeries(visibleTs, history, fallback) {
    return visibleTs.map(t => {
        if (t === null) return null;
        let val = fallback;
        // Iterate backwards to find the most recent non-null entry at or before t
        for (let i = history.length - 1; i >= 0; i--) {
            if (history[i].ts <= t && history[i].val != null) { val = history[i].val; break; }
        }
        return val;
    });
}

export function updateTargetBanners(minY, maxY) {
    const tpBanner = document.getElementById('tp-banner');
    const slBanner = document.getElementById('sl-banner');
    const bcBanner = document.getElementById('bc-banner');
    if (!tpBanner || !slBanner) return;

    const lastCandle = state.candles.length > 0 ? state.candles[state.candles.length - 1] : null;
    const currentPrice = lastCandle ? lastCandle.c : 0;
    // Anchor percentage to the active entry price so TP/SL labels match config intent.
    const basePrice = state.currentEntryPrice ?? state.currentOpenPositionBuy ?? currentPrice;

    // TP Banner
    if (state.currentTpPrice != null && state.currentTpPrice > maxY) {
        const pct = basePrice > 0 ? ((state.currentTpPrice / basePrice - 1) * 100).toFixed(1) : 0;
        tpBanner.innerHTML = `🎯 TP: $${fmt(state.currentTpPrice)} (+${pct}%)`;
        tpBanner.classList.remove('hidden');
    } else {
        tpBanner.classList.add('hidden');
    }

    // SL Banner
    if (state.currentSlPrice != null && state.currentSlPrice < minY) {
        const pct = basePrice > 0 ? ((state.currentSlPrice / basePrice - 1) * 100).toFixed(1) : 0;
        slBanner.innerHTML = `🛑 SL: $${fmt(state.currentSlPrice)} (${pct}%)`;
        slBanner.classList.remove('hidden');
    } else {
        slBanner.classList.add('hidden');
    }

    // BC Banners
    const bcBuyBanner  = document.getElementById('bc-buy-banner');
    const bcSellBanner = document.getElementById('bc-sell-banner');
    
    // Target Buy Banner
    if (bcBuyBanner) {
        if (state.currentBcPrice != null && (state.currentBcPrice < minY || state.currentBcPrice > maxY)) {
            const pct = currentPrice > 0 ? ((state.currentBcPrice / currentPrice - 1) * 100).toFixed(1) : 0;
            bcBuyBanner.innerHTML = `🎯 Target Buy: $${fmt(state.currentBcPrice)} (${pct}%)`;
            bcBuyBanner.classList.remove('hidden');
        } else {
            bcBuyBanner.classList.add('hidden');
        }
    }

    // Target Sell Banner
    if (bcSellBanner) {
        if (state.currentBcSellPrice != null && (state.currentBcSellPrice < minY || state.currentBcSellPrice > maxY)) {
            const pct = currentPrice > 0 ? ((state.currentBcSellPrice / currentPrice - 1) * 100).toFixed(1) : 0;
            bcSellBanner.innerHTML = `🏁 Target Sell: $${fmt(state.currentBcSellPrice)} (${pct}%)`;
            bcSellBanner.classList.remove('hidden');
        } else {
            bcSellBanner.classList.add('hidden');
        }
    }
}

export function renderView() {
    if (!state.rsiChart) return;
    
    // Use the latest point in candles or buffer as the "now" for filtering
    const maxCandleTs = state.candles.length > 0 ? state.candles[state.candles.length - 1].x : 0;
    const validBufTs  = state.buf.ts.filter(t => t != null && !isNaN(t));
    const maxBufTs    = validBufTs.length > 0 ? Math.max(...validBufTs) : 0;
    const latestTs    = Math.max(maxCandleTs, maxBufTs) || Date.now();

    const cutoffMs = state.viewMinutes !== null ? latestTs - (state.viewMinutes * 60 * 1000) : null;

    // Candles
    const visCandles = cutoffMs ? state.candles.filter(c => c.x >= cutoffMs) : state.candles.slice();

    // RSI buffer slice
    const vTs = [], vRsi = [], vUltra = [], vSignal = [], vBuy = [], vSell = [], vTB = [], vTS = [];
    const vBA = [], vSA = [], vTBA = [], vTSA = [];
    const vBR = [], vSR = [], vTBR = [], vTSR = [];
    state.buf.ts.forEach((t, i) => {
        if (cutoffMs && t !== null && t < cutoffMs) return;
        vTs.push(t); vRsi.push(state.buf.rsi[i] ?? null);
        vUltra.push(state.buf.rsiUltraRaw[i] ?? null);
        vSignal.push(state.buf.rsiUltraSignal[i] ?? null);
        vBuy.push(state.buf.buy[i]); vSell.push(state.buf.sell[i]);
        vTB.push(state.buf.testBuy[i]); vTS.push(state.buf.testSell[i]);
        vBA.push(state.buf.buyAmount[i]); vSA.push(state.buf.sellAmount[i]);
        vTBA.push(state.buf.testBuyAmount[i]); vTSA.push(state.buf.testSellAmount[i]);
        vBR.push(state.buf.buyReason[i]); vSR.push(state.buf.sellReason[i]);
        vTBR.push(state.buf.testBuyReason[i]); vTSR.push(state.buf.testSellReason[i]);
    });

    const toXY = (ts, arr, amtArr = [], reasonArr = []) =>
        ts.map((t, i) => t != null && arr[i] != null
            ? { x: t, y: arr[i], amount: amtArr[i] || null, reason: reasonArr[i] || null }
            : null
        ).filter(Boolean);
    const rsiXY = toXY(vTs, vRsi);

    const oversoldSeries   = generateStepwiseSeries(vTs, state.buf.rsiThresholdHistory.oversold,   state.currentOversold);
    const overboughtSeries = generateStepwiseSeries(vTs, state.buf.rsiThresholdHistory.overbought, state.currentOverbought);
    // RSI threshold lines only shown in Standard RSI mode
    const isStandardRsi = (state.chartMode === 'RSI');
    const oversoldXY   = isStandardRsi
        ? vTs.map((t,i) => (t!=null && oversoldSeries[i]!=null)   ? {x:t, y:oversoldSeries[i]}   : null).filter(Boolean)
        : [];
    const overboughtXY = isStandardRsi
        ? vTs.map((t,i) => (t!=null && overboughtSeries[i]!=null) ? {x:t, y:overboughtSeries[i]} : null).filter(Boolean)
        : [];

    // Target lines (SL/TP) flat line spans candle range
    const slData = (state.currentSlPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentSlPrice }, { x:visCandles[visCandles.length-1].x, y:state.currentSlPrice }]
        : [];
    const tpData = (state.currentTpPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentTpPrice }, { x:visCandles[visCandles.length-1].x, y:state.currentTpPrice }]
        : [];
    const entryData = (state.currentEntryPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentEntryPrice }, { x:visCandles[visCandles.length-1].x, y:state.currentEntryPrice }]
        : [];
    const openPosBuyData = (state.currentOpenPositionBuy != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentOpenPositionBuy }, { x:visCandles[visCandles.length-1].x, y:state.currentOpenPositionBuy }]
        : [];

    // Map candles to simple line points
    const priceLineXY = visCandles.map(c => ({ x: c.x, y: c.c }));

    // BC price lines only shown in BC mode
    const bcData = (state.chartMode === 'BC' && state.currentBcPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentBcPrice }, { x:visCandles[visCandles.length-1].x, y:state.currentBcPrice }]
        : [];
    const bcSellData = (state.chartMode === 'BC' && state.currentBcSellPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:state.currentBcSellPrice }, { x:visCandles[visCandles.length-1].x, y:state.currentBcSellPrice }]
        : [];

    state.rsiChart.data.datasets[0].data = visCandles;
    state.rsiChart.data.datasets[1].data = priceLineXY;
    state.rsiChart.data.datasets[2].data = rsiXY;
    state.rsiChart.data.datasets[3].data = slData;
    state.rsiChart.data.datasets[3].hidden = slData.length === 0;
    state.rsiChart.data.datasets[14].data = tpData;
    state.rsiChart.data.datasets[14].hidden = tpData.length === 0;
    state.rsiChart.data.datasets[15].data = entryData;
    state.rsiChart.data.datasets[15].hidden = entryData.length === 0;
    state.rsiChart.data.datasets[16].data = openPosBuyData;
    state.rsiChart.data.datasets[16].hidden = openPosBuyData.length === 0;
    state.rsiChart.data.datasets[16].data = openPosBuyData;
    state.rsiChart.data.datasets[16].hidden = openPosBuyData.length === 0;
    
    // BC Mode Toggle
    const isBc = (state.chartMode === 'BC');
    state.rsiChart.data.datasets[17].data = bcData;
    state.rsiChart.data.datasets[17].hidden = !isBc || bcData.length === 0;
    state.rsiChart.data.datasets[18].data = bcSellData;
    state.rsiChart.data.datasets[18].hidden = !isBc || bcSellData.length === 0;
    
    // RSI Ultra Mode Toggle
    const isUltra = (state.chartMode === 'RSI_ULTRA');
    const ultraRawXY = isUltra ? toXY(vTs, vUltra) : [];
    const ultraSigXY = isUltra ? toXY(vTs, vSignal) : [];
    
    state.rsiChart.data.datasets[19].data = ultraRawXY;
    state.rsiChart.data.datasets[19].hidden = !isUltra;
    state.rsiChart.data.datasets[20].data = ultraSigXY;
    state.rsiChart.data.datasets[20].hidden = !isUltra;

    // Standard RSI Toggle
    state.rsiChart.data.datasets[2].hidden = !isStandardRsi;
    state.rsiChart.data.datasets[4].hidden = !isStandardRsi;
    state.rsiChart.data.datasets[5].hidden = !isStandardRsi;
    
    state.rsiChart.data.datasets[4].data = oversoldXY;
    state.rsiChart.data.datasets[5].data = overboughtXY;
    
    // Build candle lookup for marker offset positioning
    const candleMap = {};
    visCandles.forEach(c => { candleMap[c.x] = c; });
    const priceRange = (visCandles.length > 1)
        ? Math.max(...visCandles.map(c => c.h)) - Math.min(...visCandles.map(c => c.l))
        : 0;
    const markerOffset = priceRange * 0.012; // 1.2% of visible range

    const toBuyXY = (ts, arr, amtArr, reasonArr) =>
        ts.map((t, i) => {
            if (t == null || arr[i] == null) return null;
            const c = candleMap[t];
            const base = c ? c.l : arr[i];
            return { x: t, y: base - markerOffset, amount: amtArr[i], reason: reasonArr[i] };
        }).filter(Boolean);

    const toSellXY = (ts, arr, amtArr, reasonArr) =>
        ts.map((t, i) => {
            if (t == null || arr[i] == null) return null;
            const c = candleMap[t];
            const base = c ? c.h : arr[i];
            return { x: t, y: base + markerOffset, amount: amtArr[i], reason: reasonArr[i] };
        }).filter(Boolean);

    state.rsiChart.data.datasets[6].data = toBuyXY(vTs, vBuy,  vBA,  vBR);
    state.rsiChart.data.datasets[7].data = toSellXY(vTs, vSell, vSA,  vSR);
    state.rsiChart.data.datasets[8].data = toBuyXY(vTs, vTB,   vTBA, vTBR);
    state.rsiChart.data.datasets[9].data = toSellXY(vTs, vTS,   vTSA, vTSR);

    const isRsiAny = isStandardRsi || isUltra;
    const rsiSource = isUltra ? vUltra : vRsi;
    
    state.rsiChart.data.datasets[10].data = toXY(vTs, vBuy.map((p,i)  => p != null ? rsiSource[i] : null), vBA,  vBR);
    state.rsiChart.data.datasets[11].data = toXY(vTs, vSell.map((p,i) => p != null ? rsiSource[i] : null), vSA,  vSR);
    state.rsiChart.data.datasets[12].data = toXY(vTs, vTB.map((p,i)   => p != null ? rsiSource[i] : null), vTBA, vTBR);
    state.rsiChart.data.datasets[13].data = toXY(vTs, vTS.map((p,i)   => p != null ? rsiSource[i] : null), vTSA, vTSR);

    // Hide buy/sell markers on the RSI axis if in BC mode
    [10, 11, 12, 13].forEach(idx => {
        state.rsiChart.data.datasets[idx].hidden = !isRsiAny || state.rsiChart.data.datasets[idx].hidden;
    });

    // Visibility toggle for test data
    [8, 9, 12, 13].forEach(idx => {
        state.rsiChart.data.datasets[idx].hidden = state.hideTestData;
    });
    // Visibility toggle for prod data
    [6, 7, 10, 11].forEach(idx => {
        state.rsiChart.data.datasets[idx].hidden = state.hideProdData;
    });

    // Dynamic Price Scaling (Focus Zoom) - Prioritize Candles to avoid flattening
    if (visCandles.length > 0) {
        const lows  = visCandles.map(c => c.l);
        const highs = visCandles.map(c => c.h);
        const minC  = Math.min(...lows);
        const maxC  = Math.max(...highs);
        const rangeC = (maxC - minC) || (minC * 0.01);
        
        // FOCUS-FIRST ZOOM: Prioritize candles for 80% visibility
        const minY = minC - rangeC * 0.2;
        const maxY = maxC + rangeC * 0.2;

        state.rsiChart.options.scales.yPrice.min = minY;
        state.rsiChart.options.scales.yPrice.max = maxY;

        // Banners for off-screen targets
        updateTargetBanners(minY, maxY);
    }
    state.rsiChart.update('none');
}
