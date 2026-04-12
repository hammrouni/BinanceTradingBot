/**
 * chart_integration.js — Handles the History Chart for the simulator.
 */

export let historyChart = null;

export function initHistoryChart() {
    const canvas = document.getElementById('history-chart');
    if (!canvas) return;

    const existingChart = Chart.getChart(canvas);
    if (existingChart) existingChart.destroy();
    
    historyChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            datasets: [
                { label: 'Price', data: [], borderColor: '#94a3b8', backgroundColor: 'rgba(148,163,184,0.1)',
                  borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, yAxisID: 'yPrice', order: 5 },
                { label: 'RSI (14)', data: [], borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)',
                  borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'yRsi', order: 4 },
                { label: 'Ultra Raw', data: [], borderColor: '#f59e0b', backgroundColor: 'transparent',
                  borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'yRsi', order: 4 },
                { label: 'Ultra Signal', data: [], borderColor: '#ef4444', backgroundColor: 'transparent',
                  borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'yRsi', order: 4 },
                { label: 'Buy (Sim)', type: 'scatter', data: [], backgroundColor: '#10b981',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 180, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                { label: 'Sell (Sim)', type: 'scatter', data: [], backgroundColor: '#ef4444',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 0, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                { label: 'Target Buy', data: [], borderColor: '#10b981', borderDash: [5, 5], borderWidth: 1.5,
                  pointRadius: 0, fill: false, yAxisID: 'yPrice', order: 6 },
                { label: 'Target Sell', data: [], borderColor: '#ef4444', borderDash: [5, 5], borderWidth: 1.5,
                  pointRadius: 0, fill: false, yAxisID: 'yPrice', order: 6 },
            ],
        },
        options: {
            animation: false, responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'x', intersect: false },
            scales: {
                x: {
                    type: 'linear',
                    ticks: {
                        color:'#94a3b8', font:{ size:10 }, maxTicksLimit:8, maxRotation:0,
                        callback: function(value) {
                            const date = new Date(value);
                            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
                        }
                    },
                    grid: { color:'rgba(203,213,225,0.4)' },
                    title: { display: true, text: 'Time', color:'#94a3b8' },
                },
                yPrice: {
                    position: 'right',
                    grid: { color:'rgba(203,213,225,0.2)', drawBorder:false },
                    grace: '3%', beginAtZero: false,
                    ticks: { color:'rgba(100,116,139,0.8)', font:{ size:10 },
                        callback: v => '$' + v.toLocaleString('en-US',{ minimumFractionDigits:2 }) },
                },
                yRsi: {
                    position: 'left',
                    min: 0, max: 100, offset: true,
                    border: { display:false },
                    grid: { color:'rgba(203,213,225,0.5)', drawBorder:false },
                    ticks: { color:'#94a3b8', stepSize:25, font:{ size:10 } },
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        title: ctx => new Date(ctx[0].parsed.x).toLocaleString(),
                        label: function(ctx) {
                            let label = ctx.dataset.label || '';
                            const n = ctx.dataset.label;
                            if (label) label += ': ';
                            if (ctx.dataset.yAxisID === 'yRsi') {
                                label += ctx.parsed.y.toFixed(2);
                            } else if (n === 'Buy (Sim)' || n === 'Sell (Sim)') {
                                const side = n.includes('Buy') ? '▼ Buy' : '▲ Sell';
                                const reason = ctx.raw.reason || '';
                                const pnl = ctx.raw.pnl ? ` | PnL: $${ctx.raw.pnl}` : '';
                                return [` ${side}: $${ctx.parsed.y.toLocaleString()}${pnl}`, ` Reason: ${reason}`];
                            } else {
                                label += '$' + ctx.parsed.y.toLocaleString('en-US',{ minimumFractionDigits:2 });
                            }
                            return label;
                        }
                    }
                },
                legend: { labels: { color:'#475569', font:{ size:11 }, boxWidth: 12 } },
            },
        },
    });
}

export function updateHistoryChart(marketHistory) {
    if (!historyChart) return;
    if (!marketHistory || marketHistory.length === 0) return;

    const priceData = [];
    const rsiData = [];
    for (const point of marketHistory) {
        if (!point.timestamp || !point.price) continue;
        const ts = new Date(point.timestamp).getTime();
        priceData.push({ x: ts, y: point.price });
        if (point.rsi != null) rsiData.push({ x: ts, y: point.rsi });
    }

    const ultraRawData = [];
    const ultraSigData = [];
    for (const point of marketHistory) {
        if (!point.timestamp) continue;
        const ts = new Date(point.timestamp).getTime();
        if (point.rsi_ultra_raw != null) ultraRawData.push({ x: ts, y: point.rsi_ultra_raw });
        if (point.rsi_ultra_signal != null) ultraSigData.push({ x: ts, y: point.rsi_ultra_signal });
    }

    historyChart.data.datasets[0].data = priceData;
    historyChart.data.datasets[1].data = rsiData;
    historyChart.data.datasets[2].data = ultraRawData;
    historyChart.data.datasets[3].data = ultraSigData;

    // Shift indices for markers and target lines because we added 2 datasets
    const MARKER_BUY_IDX = 4;
    const MARKER_SELL_IDX = 5;
    const TARGET_BUY_IDX = 6;
    const TARGET_SELL_IDX = 7;

    // Clear markers when fresh market data is loaded
    if (historyChart.data.datasets[MARKER_BUY_IDX]) historyChart.data.datasets[MARKER_BUY_IDX].data = [];
    if (historyChart.data.datasets[MARKER_SELL_IDX]) historyChart.data.datasets[MARKER_SELL_IDX].data = [];
    if (historyChart.data.datasets[TARGET_BUY_IDX]) historyChart.data.datasets[TARGET_BUY_IDX].data = [];
    if (historyChart.data.datasets[TARGET_SELL_IDX]) historyChart.data.datasets[TARGET_SELL_IDX].data = [];
    historyChart.update();

    const infoDiv = document.getElementById('chart-data-info');
    if (infoDiv && priceData.length > 0) {
        const firstTs = new Date(priceData[0].x);
        const lastTs = new Date(priceData[priceData.length - 1].x);
        const range = firstTs.toLocaleDateString() + ' - ' + lastTs.toLocaleDateString();
        infoDiv.innerHTML = '<span>' + priceData.length + ' data points</span> <span style="color:#94a3b8;">(' + range + ')</span>';
    }
}

export function plotSimulationEvents(events) {
    if (!historyChart || !events) return;
    const buyMarkers = [];
    const sellMarkers = [];

    events.forEach(ev => {
        const m = { x: new Date(ev.timestamp).getTime(), y: ev.price, reason: ev.reason, pnl: ev.pnl };
        if (ev.action === 'buy') buyMarkers.push(m);
        else sellMarkers.push(m);
    });

    historyChart.data.datasets[4].data = buyMarkers;
    historyChart.data.datasets[5].data = sellMarkers;
    historyChart.update();
}

export function plotTargetPriceLines(buyPrice, sellPrice) {
    if (!historyChart || !historyChart.data.datasets[0] || !historyChart.data.datasets[0].data.length) return;
    
    // Clear old lines if any
    historyChart.data.datasets[6].data = [];
    historyChart.data.datasets[7].data = [];

    const xRange = historyChart.data.datasets[0].data;
    const firstX = xRange[0].x;
    const lastX = xRange[xRange.length - 1].x;

    if (buyPrice) {
        historyChart.data.datasets[6].data = [{ x: firstX, y: buyPrice }, { x: lastX, y: buyPrice }];
    }
    if (sellPrice) {
        historyChart.data.datasets[7].data = [{ x: firstX, y: sellPrice }, { x: lastX, y: sellPrice }];
    }
    historyChart.update();
}

// Make accessible to legacy handlers if needed, though they should use index.js
window.updateHistoryChart = updateHistoryChart;
