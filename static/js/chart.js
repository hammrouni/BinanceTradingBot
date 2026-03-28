// chart.js — RSI and Price chart with dual axes, stop-loss indicator, and trade markers

let rsiChart           = null;
let currentOversold    = 30;
let currentOverbought  = 70;
let currentSlPrice     = null; // Global for the active Stop-Loss line

// ─── Data buffer (full history, survives interval changes) ────────────────────
const MAX_BUFFER = 1440; 
const _buf = { 
    ts: [], labels: [], rsi: [], price: [],
    buy: [], sell: [], 
    buyPrice: [], sellPrice: [],
    testBuy: [], testSell: [],
    testBuyPrice: [], testSellPrice: [],
    rsiThresholdHistory: { oversold: [], overbought: [] }
};
let _viewMinutes = 60; 

// ─── Zone background plugin ───────────────────────────────────────────────────
const rsiZonePlugin = {
    id: 'rsiZones',
    beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea || !scales.y) return;
        const { left, right } = chartArea;
        const yScale = scales.y;
        const w = right - left;

        ctx.save();
        // Oversold zone: 0 – 30 (red tint)
        const y30 = yScale.getPixelForValue(30);
        const y0  = yScale.getPixelForValue(0);
        ctx.fillStyle = 'rgba(220, 38, 38, 0.06)';
        ctx.fillRect(left, y30, w, y0 - y30);

        // Overbought zone: 70 – 100 (green tint)
        const y70  = yScale.getPixelForValue(70);
        const y100 = yScale.getPixelForValue(100);
        ctx.fillStyle = 'rgba(22, 163, 74, 0.06)';
        ctx.fillRect(left, y100, w, y70 - y100);
        ctx.restore();
    },
};

// ─── Init ─────────────────────────────────────────────────────────────────────
function initRsiChart() {
    const canvas = document.getElementById('rsi-chart');
    if (!canvas) return;

    rsiChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        plugins: [rsiZonePlugin],
        data: {
            labels: [],
            datasets: [
                // 0 — RSI line
                {
                    label: 'RSI (14)',
                    data: [],
                    borderColor: '#3b82f6',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false,
                    order: 3,
                    yAxisID: 'y',
                },
                // 1 — Price line (Secondary Axis)
                {
                    label: 'Price',
                    data: [],
                    borderColor: 'rgba(100, 116, 139, 0.5)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.2,
                    fill: false,
                    order: 4,
                    yAxisID: 'yPrice',
                },
                // 2 — Stop-Loss line (Stepped or straight)
                {
                    label: 'Stop-Loss',
                    data: [],
                    borderColor: '#ef4444',
                    borderWidth: 2,
                    borderDash: [5, 3],
                    pointRadius: 0,
                    fill: false,
                    order: 5,
                    yAxisID: 'yPrice',
                    hidden: true,
                },
                // 3 — Oversold threshold
                {
                    label: 'Oversold',
                    data: [],
                    borderColor: '#ef4444',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    order: 6,
                    yAxisID: 'y',
                    stepped: 'after',
                },
                // 4 — Overbought threshold
                {
                    label: 'Overbought',
                    data: [],
                    borderColor: '#22c55e',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    order: 6,
                    yAxisID: 'y',
                    stepped: 'after',
                },
                // 5 — Buy signal markers
                {
                    label: 'Buy Signal',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: '#f97316',
                    pointRadius: 7,
                    pointStyle: 'triangle',
                    pointRotation: 180,
                    showLine: false,
                    order: 1,
                    yAxisID: 'y',
                },
                // 6 — Sell signal markers
                {
                    label: 'Sell Signal',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: '#ef4444',
                    pointRadius: 7,
                    pointStyle: 'triangle',
                    pointRotation: 0,
                    showLine: false,
                    order: 1,
                    yAxisID: 'y',
                },
                // 7 — Test Buy signal
                {
                    label: 'Test Buy Signal',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: '#a855f7',
                    pointRadius: 6,
                    pointStyle: 'rect',
                    pointRotation: 0,
                    showLine: false,
                    order: 1,
                    yAxisID: 'y',
                },
                // 8 — Test Sell signal
                {
                    label: 'Test Sell Signal',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: '#475569',
                    pointRadius: 6,
                    pointStyle: 'rect',
                    pointRotation: 0,
                    showLine: false,
                    order: 1,
                    yAxisID: 'y',
                },
            ],
        },
        options: {
            animation: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    position: 'left',
                    grid: { color: 'rgba(203, 213, 225, 0.6)' },
                    ticks: {
                        color: '#94a3b8',
                        stepSize: 10,
                        font: { size: 10 },
                    },
                    title: { display: false, text: 'RSI' }
                },
                yPrice: {
                    position: 'right',
                    grid: { display: false },
                    ticks: {
                        color: 'rgba(100, 116, 139, 0.7)',
                        font: { size: 10 },
                        callback: (v) => '$' + v.toLocaleString()
                    },
                    grace: '10%',
                    title: { display: false, text: 'Price' }
                },
                x: {
                    grid: { color: 'rgba(203, 213, 225, 0.4)' },
                    ticks: {
                        color: '#94a3b8',
                        font: { size: 10 },
                        maxTicksLimit: 8,
                        maxRotation: 0,
                    },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#ffffff',
                    borderColor: '#e2e8f0',
                    borderWidth: 1,
                    titleColor: '#64748b',
                    bodyColor: '#1e293b',
                    callbacks: {
                        title(ctx) {
                            const i = ctx[0].dataIndex;
                            const ts = _buf.ts[i];
                            if (!ts) return '';
                            return new Date(ts).toLocaleString('en-US', {
                                month: 'short', day: 'numeric',
                                hour: '2-digit', minute: '2-digit', second: '2-digit'
                            });
                        },
                        label(ctx) {
                            const i = ctx.dataIndex;
                            if (ctx.dataset.label === 'Price') {
                                return ` 📈 Price: $${ctx.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
                            }
                            if (ctx.dataset.label === 'Stop-Loss') {
                                return ` 🛑 Stop-Loss: $${ctx.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
                            }
                            if (ctx.dataset.label === 'Buy Signal' && ctx.parsed.y != null) {
                                const price = _buf.buyPrice[i];
                                return ` ▼ Buy executed at $${price?.toFixed(2) || '—'}`;
                            }
                            if (ctx.dataset.label === 'Sell Signal' && ctx.parsed.y != null) {
                                const price = _buf.sellPrice[i];
                                return ` ▲ Sell executed at $${price?.toFixed(2) || '—'}`;
                            }
                            if (ctx.dataset.label === 'Test Buy Signal' && ctx.parsed.y != null) {
                                const price = _buf.testBuyPrice[i];
                                return ` 🛠 [TEST] Buy at $${price?.toFixed(2) || '—'}`;
                            }
                            if (ctx.dataset.label === 'Test Sell Signal' && ctx.parsed.y != null) {
                                const price = _buf.testSellPrice[i];
                                return ` 🛠 [TEST] Sell at $${price?.toFixed(2) || '—'}`;
                            }
                            if (ctx.dataset.label === 'RSI (14)')
                                return ` RSI: ${ctx.parsed.y.toFixed(2)}`;
                            return null;
                        },
                    },
                },
            },
            responsive: true,
            maintainAspectRatio: false,
        },
    });

    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const raw = btn.dataset.minutes;
            setChartInterval(raw === 'all' ? null : Number(raw));
        });
    });
}

function _renderView() {
    if (!rsiChart) return;

    let start = 0;
    if (_viewMinutes !== null) {
        const cutoff = Date.now() - _viewMinutes * 60 * 1000;
        const idx = _buf.ts.findIndex(t => t != null && t >= cutoff);
        start = idx >= 0 ? idx : 0;
    }

    const len = _buf.labels.length - start;
    rsiChart.data.labels           = _buf.labels.slice(start);
    
    // RSI & Thresholds (Axis: y)
    rsiChart.data.datasets[0].data = _buf.rsi.slice(start);
    
    // Generate stepwise threshold series
    const visibleTs = _buf.ts.slice(start);
    rsiChart.data.datasets[3].data = _generateStepwiseSeries(visibleTs, _buf.rsiThresholdHistory.oversold, currentOversold);
    rsiChart.data.datasets[4].data = _generateStepwiseSeries(visibleTs, _buf.rsiThresholdHistory.overbought, currentOverbought);
    
    // Price and SL (Axis: yPrice)
    rsiChart.data.datasets[1].data = _buf.price.slice(start);
    if (currentSlPrice) {
        rsiChart.data.datasets[2].data = Array(len).fill(currentSlPrice);
        rsiChart.data.datasets[2].hidden = false;
    } else {
        rsiChart.data.datasets[2].data = [];
        rsiChart.data.datasets[2].hidden = true;
    }

    // Signals (Axis: y)
    rsiChart.data.datasets[5].data = _buf.buy.slice(start);
    rsiChart.data.datasets[6].data = _buf.sell.slice(start);
    rsiChart.data.datasets[7].data = _buf.testBuy.slice(start);
    rsiChart.data.datasets[8].data = _buf.testSell.slice(start);
    
    rsiChart.update('none');
}

function setChartInterval(minutes) {
    _viewMinutes = minutes;
    _renderView();
    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        const raw = btn.dataset.minutes;
        const isActive = minutes === null ? raw === 'all' : Number(raw) === minutes;
        btn.classList.toggle('active', isActive);
    });
}

function setRsiHistory(points) {
    if (!points || !Array.isArray(points)) return;
    
    _buf.ts = []; _buf.labels = []; _buf.rsi = []; _buf.price = [];
    _buf.buy = []; _buf.sell = []; _buf.buyPrice = []; _buf.sellPrice = [];
    _buf.testBuy = []; _buf.testSell = []; _buf.testBuyPrice = []; _buf.testSellPrice = [];

    points.forEach(p => {
        const tsMs = p.timestamp ? new Date(p.timestamp).getTime() : null;
        const label = p.timestamp 
            ? new Date(p.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : '';
        _buf.ts.push(tsMs);
        _buf.labels.push(label);
        _buf.rsi.push(p.rsi);
        _buf.price.push(p.price || p.entry_price || null); // Capture price from history
        
        _buf.buy.push(null); _buf.sell.push(null);
        _buf.buyPrice.push(null); _buf.sellPrice.push(null);
        _buf.testBuy.push(null); _buf.testSell.push(null);
        _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);
    });

    _renderView();
}

function updateRsiChart(rsiValue, timestamp, priceValue = null) {
    if (!rsiChart || rsiValue == null) return;

    const tsMs  = timestamp ? new Date(timestamp).getTime() : null;
    const label = timestamp
        ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';

    _buf.ts.push(tsMs);
    _buf.labels.push(label);
    _buf.rsi.push(rsiValue);
    _buf.price.push(priceValue);
    
    _buf.buy.push(null); _buf.sell.push(null);
    _buf.buyPrice.push(null); _buf.sellPrice.push(null);
    _buf.testBuy.push(null); _buf.testSell.push(null);
    _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);

    if (_buf.ts.length > MAX_BUFFER) {
        _buf.ts.shift(); _buf.labels.shift(); _buf.rsi.shift(); _buf.price.shift();
        _buf.buy.shift(); _buf.sell.shift();
        _buf.buyPrice.shift(); _buf.sellPrice.shift();
        _buf.testBuy.shift(); _buf.testSell.shift();
        _buf.testBuyPrice.shift(); _buf.testSellPrice.shift();
    }

    _renderView();
}

function updateChartSl(price) {
    currentSlPrice = price;

    // Expand the price axis to always include the SL line
    if (rsiChart) {
        const priceScale = rsiChart.options.scales.yPrice;
        if (price != null) {
            priceScale.min = price * 0.995; // small buffer below SL
        } else {
            delete priceScale.min;          // restore auto-scale
        }
    }

    _renderView();
}

function markBuySignal(price, isTest = false) {
    if (_buf.rsi.length === 0) return;
    const i = _buf.rsi.length - 1;
    if (isTest) {
        _buf.testBuy[i] = _buf.rsi[i];
        _buf.testBuyPrice[i] = price;
    } else {
        _buf.buy[i] = _buf.rsi[i];
        _buf.buyPrice[i] = price;
    }
    _renderView();
}

function markSellSignal(price, isTest = false) {
    if (_buf.rsi.length === 0) return;
    const i = _buf.rsi.length - 1;
    if (isTest) {
        _buf.testSell[i] = _buf.rsi[i];
        _buf.testSellPrice[i] = price;
    } else {
        _buf.sell[i] = _buf.rsi[i];
        _buf.sellPrice[i] = price;
    }
    _renderView();
}

function markSignalAtTime(isoTimestamp, direction, price, isTest = false) {
    if (!isoTimestamp || _buf.ts.length === 0) return;
    const ms = new Date(isoTimestamp).getTime();
    const firstTs = _buf.ts[0];
    const lastTs  = _buf.ts[_buf.ts.length - 1];
    
    if (firstTs === null || lastTs === null) return;
    if (ms < (firstTs - 60000) || ms > (lastTs + 60000)) return;

    let closestIdx = -1, minDiff = Infinity;
    _buf.ts.forEach((t, i) => {
        if (t == null) return;
        const diff = Math.abs(t - ms);
        if (diff < minDiff) { minDiff = diff; closestIdx = i; }
    });
    
    if (closestIdx < 0) return;
    const rsiVal = _buf.rsi[closestIdx];
    if (rsiVal == null) return;

    if (direction === 'sell') {
        if (isTest) {
            _buf.testSell[closestIdx] = rsiVal;
            _buf.testSellPrice[closestIdx] = price;
        } else {
            _buf.sell[closestIdx] = rsiVal;
            _buf.sellPrice[closestIdx] = price;
        }
    } else {
        if (isTest) {
            _buf.testBuy[closestIdx] = rsiVal;
            _buf.testBuyPrice[closestIdx] = price;
        } else {
            _buf.buy[closestIdx]  = rsiVal;
            _buf.buyPrice[closestIdx] = price;
        }
    }
    _renderView();
}

function updateChartThresholds(oversold, overbought) {
    currentOversold = oversold;
    currentOverbought = overbought;
    _renderView();
}

/**
 * Sets the historical RSI thresholds and triggers a re-render.
 * @param {Array} history - List of {timestamp, type, value}
 */
function setRsiThresholdHistory(history) {
    if (!history || !Array.isArray(history)) return;
    
    _buf.rsiThresholdHistory.oversold = history
        .filter(h => h.type === 'oversold')
        .map(h => ({ ts: new Date(h.timestamp).getTime(), val: h.value }))
        .sort((a, b) => a.ts - b.ts);
        
    _buf.rsiThresholdHistory.overbought = history
        .filter(h => h.type === 'overbought')
        .map(h => ({ ts: new Date(h.timestamp).getTime(), val: h.value }))
        .sort((a, b) => a.ts - b.ts);
        
    _renderView();
}

/**
 * Logic to generate a stepwise data array matching the chart's labels.
 */
function _generateStepwiseSeries(visibleTs, history, fallback) {
    if (!visibleTs.length) return [];
    
    return visibleTs.map(t => {
        if (t === null) return null;
        // Find the most recent entry that is <= t
        let activeVal = fallback;
        // Since history is small (usually < 100 entries), linear search is fine.
        // For larger history, binary search would be better.
        for (let i = history.length - 1; i >= 0; i--) {
            if (history[i].ts <= t) {
                activeVal = history[i].val;
                break;
            }
        }
        return activeVal;
    });
}

document.addEventListener('DOMContentLoaded', initRsiChart);
