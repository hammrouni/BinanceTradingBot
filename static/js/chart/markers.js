/**
 * markers.js — Logic for drawing signals, SL/TP lines, and banners on the chart.
 */

// Global visibility for backward compatibility with dashboard.js and index.js
export function markBuySignal(price, isTest, amountUsd, reason) {
    const symbol = isTest ? '🔷' : '🟢';
    const label = `${symbol} BUY: $${amountUsd.toFixed(0)} (${reason})`;
    addChartAnnotation(price, 'rgba(0, 255, 0, 0.5)', label);
}

export function markSellSignal(price, isTest, amountUsd, reason) {
    const symbol = isTest ? '🔶' : '🔴';
    const label = `${symbol} SELL: $${amountUsd.toFixed(0)} (${reason})`;
    addChartAnnotation(price, 'rgba(255, 0, 0, 0.5)', label);
}

function addChartAnnotation(price, color, label) {
    // Current Chart.js implementation doesn't have the annotation plugin yet,
    // so we'll simulate it by adding a vertical bar or just logging it.
    // In a full implementation, we'd use chartjs-plugin-annotation.
    console.log(`[Chart Annotation] ${label} at ${price}`);
}

export function updateChartWithPosition(pos) {
    const tpBanner = document.getElementById('tp-banner');
    const slBanner = document.getElementById('sl-banner');
    const bcBuyBanner = document.getElementById('bc-buy-banner');
    const bcSellBanner = document.getElementById('bc-sell-banner');

    if (pos.take_profit_price) {
        if (tpBanner) {
            tpBanner.textContent = `TP: $${pos.take_profit_price.toFixed(2)}`;
            tpBanner.style.borderTop = '2px dashed rgba(0, 255, 127, 0.8)';
            tpBanner.classList.remove('hidden');
        }
    } else {
        tpBanner?.classList.add('hidden');
    }

    if (pos.stop_loss_price) {
        if (slBanner) {
            slBanner.textContent = `SL: $${pos.stop_loss_price.toFixed(2)}`;
            slBanner.style.borderTop = '2px dashed rgba(255, 69, 58, 0.8)';
            slBanner.classList.remove('hidden');
        }
    } else {
        slBanner?.classList.add('hidden');
    }
}

export function clearOpenPositionFromChart() {
    document.getElementById('tp-banner')?.classList.add('hidden');
    document.getElementById('sl-banner')?.classList.add('hidden');
}

// Global assignment for backward compatibility
window.markBuySignal = markBuySignal;
window.markSellSignal = markSellSignal;
window.updateChartWithPosition = updateChartWithPosition;
window.clearOpenPositionFromChart = clearOpenPositionFromChart;
