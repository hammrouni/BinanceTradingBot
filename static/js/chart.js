// chart.js — RSI chart with zone fills, buy/sell markers, and interval navigation

let rsiChart         = null;
let currentThreshold = 30;

// ─── Data buffer (full history, survives interval changes) ────────────────────
const MAX_BUFFER = 1440; // ~24 h at 1-min intervals; ~24 min at 1-sec intervals
const _buf = { ts: [], labels: [], rsi: [], buy: [], sell: [] };
let _viewMinutes = null; // null = show all buffered data

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
                    order: 2,
                },
                // 1 — Oversold threshold (dashed)
                {
                    label: 'Oversold',
                    data: [],
                    borderColor: '#ef4444',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    order: 3,
                },
                // 2 — Overbought threshold (dashed)
                {
                    label: 'Overbought',
                    data: [],
                    borderColor: '#22c55e',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    order: 3,
                },
                // 3 — Buy signal markers (orange downward triangle)
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
                },
                // 4 — Sell signal markers (red upward triangle)
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
                    grid: { color: 'rgba(203, 213, 225, 0.6)' },
                    ticks: {
                        color: '#94a3b8',
                        stepSize: 10,
                        font: { size: 11 },
                    },
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
                        label(ctx) {
                            if (ctx.dataset.label === 'Buy Signal' && ctx.parsed.y != null)
                                return ' ▼ Buy signal executed';
                            if (ctx.dataset.label === 'Sell Signal' && ctx.parsed.y != null)
                                return ' ▲ Sell signal executed';
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

    // Wire interval buttons
    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const raw = btn.dataset.minutes;
            setChartInterval(raw === 'all' ? null : Number(raw));
        });
    });
}

// ─── Render the chart from the buffer using the current view window ───────────
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
    rsiChart.data.datasets[0].data = _buf.rsi.slice(start);
    rsiChart.data.datasets[1].data = Array(len).fill(currentThreshold);
    rsiChart.data.datasets[2].data = Array(len).fill(70);
    rsiChart.data.datasets[3].data = _buf.buy.slice(start);
    rsiChart.data.datasets[4].data = _buf.sell.slice(start);
    rsiChart.update('none');
}

// ─── Set the visible interval and update active button ────────────────────────
function setChartInterval(minutes) {
    _viewMinutes = minutes;
    _renderView();
    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        const raw = btn.dataset.minutes;
        const isActive = minutes === null ? raw === 'all' : Number(raw) === minutes;
        btn.classList.toggle('active', isActive);
    });
}

// ─── Update threshold line when config changes ────────────────────────────────
function updateRsiThresholdLine(threshold) {
    currentThreshold = threshold;
    _renderView();
}

// ─── Push new RSI value ───────────────────────────────────────────────────────
function updateRsiChart(rsiValue, timestamp) {
    if (!rsiChart || rsiValue == null) return;

    const tsMs  = timestamp ? new Date(timestamp).getTime() : null;
    const label = timestamp
        ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';

    _buf.ts.push(tsMs);
    _buf.labels.push(label);
    _buf.rsi.push(rsiValue);
    _buf.buy.push(null);
    _buf.sell.push(null);

    // Trim buffer
    if (_buf.ts.length > MAX_BUFFER) {
        _buf.ts.shift(); _buf.labels.shift();
        _buf.rsi.shift(); _buf.buy.shift(); _buf.sell.shift();
    }

    _renderView();
}

// ─── Mark buy signal at the latest data point ─────────────────────────────────
function markBuySignal() {
    if (_buf.rsi.length === 0) return;
    const i = _buf.rsi.length - 1;
    _buf.buy[i] = _buf.rsi[i];
    _renderView();
}

// ─── Mark sell signal at the latest data point ────────────────────────────────
function markSellSignal() {
    if (_buf.rsi.length === 0) return;
    const i = _buf.rsi.length - 1;
    _buf.sell[i] = _buf.rsi[i];
    _renderView();
}

// ─── Mark a signal at the closest historical timestamp ───────────────────────
function markSignalAtTime(isoTimestamp, direction) {
    if (!isoTimestamp) return;
    const ms = new Date(isoTimestamp).getTime();
    let closestIdx = -1, minDiff = Infinity;
    _buf.ts.forEach((t, i) => {
        if (t == null) return;
        const diff = Math.abs(t - ms);
        if (diff < minDiff) { minDiff = diff; closestIdx = i; }
    });
    if (closestIdx < 0) return;
    const rsiVal = _buf.rsi[closestIdx];
    if (rsiVal == null) return;
    if (direction === 'sell') _buf.sell[closestIdx] = rsiVal;
    else                      _buf.buy[closestIdx]  = rsiVal;
    _renderView();
}

document.addEventListener('DOMContentLoaded', initRsiChart);
