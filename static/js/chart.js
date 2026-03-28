// chart.js — Combined Candlestick (price) + RSI chart

let rsiChart = null;
let currentOversold   = 30;
let currentOverbought = 70;
let currentSlPrice    = null;

const MAX_BUFFER  = 1440;
const MAX_CANDLES = 1440;

const _buf = {
    ts: [], rsi: [],
    buy: [], sell: [], buyPrice: [], sellPrice: [],
    testBuy: [], testSell: [], testBuyPrice: [], testSellPrice: [],
    rsiThresholdHistory: { oversold: [], overbought: [] },
};
let _candles     = [];
let _viewMinutes = 60;

// ── RSI zone background plugin ─────────────────────────────────────────────────
const rsiZonePlugin = {
    id: 'rsiZones',
    beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea || !scales.yRsi) return;
        const { left, right } = chartArea;
        const S = scales.yRsi;
        ctx.save();
        ctx.fillStyle = 'rgba(220,38,38,0.06)';
        ctx.fillRect(left, S.getPixelForValue(currentOversold), right - left, S.getPixelForValue(0) - S.getPixelForValue(currentOversold));
        ctx.fillStyle = 'rgba(22,163,74,0.06)';
        ctx.fillRect(left, S.getPixelForValue(100), right - left, S.getPixelForValue(currentOverbought) - S.getPixelForValue(100));
        ctx.restore();
    },
};

// ── Init ───────────────────────────────────────────────────────────────────────
function initRsiChart() {
    const canvas = document.getElementById('rsi-chart');
    if (!canvas) return;
    if (rsiChart) { rsiChart.destroy(); rsiChart = null; }

    rsiChart = new Chart(canvas.getContext('2d'), {
        type: 'candlestick',
        plugins: [rsiZonePlugin],
        data: {
            datasets: [
                /* 0 – Candlestick OHLC */
                { label: 'Price', type: 'candlestick', data: [], yAxisID: 'yPrice', order: 5,
                  color: { up:'rgba(22,163,74,.85)', down:'rgba(220,38,38,.85)', unchanged:'rgba(100,116,139,.75)' },
                  borderColor: { up:'#16a34a', down:'#dc2626', unchanged:'#64748b' } },
                /* 1 – Price line (superimposed) */
                { label: 'Price Line', type: 'line', data: [], borderColor: '#94a3b8', borderWidth: 1.5,
                  pointRadius: 0, tension: 0.2, fill: false, yAxisID: 'yPrice', order: 4 },
                /* 2 – RSI line */
                { label: 'RSI (14)', type: 'line', data: [], borderColor: '#3b82f6', borderWidth: 2,
                  pointRadius: 0, tension: 0.3, fill: false, yAxisID: 'yRsi', order: 3 },
                /* 3 – Stop-Loss */
                { label: 'Stop-Loss', type: 'line', data: [], borderColor: '#ef4444', borderWidth: 1.5,
                  borderDash: [5,3], pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 4 – Oversold threshold */
                { label: 'Oversold', type: 'line', data: [], borderColor: '#ef4444', borderDash: [5,5],
                  borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'yRsi', stepped: 'after', order: 6 },
                /* 5 – Overbought threshold */
                { label: 'Overbought', type: 'line', data: [], borderColor: '#22c55e', borderDash: [5,5],
                  borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'yRsi', stepped: 'after', order: 6 },
                /* 6 – Buy (prod) */
                { label: 'Buy Signal', type: 'scatter', data: [], backgroundColor: '#f97316',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 180, borderColor: 'transparent', yAxisID: 'yPrice', order: 1 },
                /* 7 – Sell (prod) */
                { label: 'Sell Signal', type: 'scatter', data: [], backgroundColor: '#ef4444',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 0, borderColor: 'transparent', yAxisID: 'yPrice', order: 1 },
                /* 8 – Buy (test) */
                { label: 'Test Buy Signal', type: 'scatter', data: [], backgroundColor: '#a855f7',
                  pointStyle: 'rect', pointRadius: 6, borderColor: 'transparent', yAxisID: 'yPrice', order: 1 },
                /* 9 – Sell (test) */
                { label: 'Test Sell Signal', type: 'scatter', data: [], backgroundColor: '#475569',
                  pointStyle: 'rect', pointRadius: 6, borderColor: 'transparent', yAxisID: 'yPrice', order: 1 },
            ],
        },
        options: {
            animation: false, responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'x', intersect: false },
            scales: {
                x: {
                    type: 'time',
                    time: { displayFormats: { minute:'HH:mm', hour:'HH:mm', day:'MMM d' }, tooltipFormat:'HH:mm' },
                    ticks: { color:'#94a3b8', font:{ size:10 }, maxTicksLimit:8, maxRotation:0 },
                    grid: { color:'rgba(203,213,225,0.4)' },
                },
                yRsi: {
                    min: 0, max: 100, position: 'left',
                    grid: { color:'rgba(203,213,225,0.5)' },
                    ticks: { color:'#94a3b8', stepSize:10, font:{ size:10 } },
                },
                yPrice: {
                    position: 'right', grid: { display: false }, grace: '3%',
                    ticks: { color:'rgba(100,116,139,0.8)', font:{ size:10 },
                        callback: v => '$' + v.toLocaleString('en-US',{ minimumFractionDigits:2 }) },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor:'#ffffff', borderColor:'#e2e8f0', borderWidth:1,
                    titleColor:'#64748b', bodyColor:'#1e293b',
                    callbacks: {
                        title(items) {
                            if (!items.length) return '';
                            return new Date(items[0].parsed.x).toLocaleString('en-US',{
                                month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'
                            });
                        },
                        label(ctx) {
                            if (ctx.datasetIndex === 0) {
                                const d = ctx.raw;
                                return [` O:$${_fmt(d.o)}`, ` H:$${_fmt(d.h)}`, ` L:$${_fmt(d.l)}`, ` C:$${_fmt(d.c)}`];
                            }
                            const n = ctx.dataset.label;
                            if (n === 'RSI (14)')         return ` RSI: ${ctx.parsed.y?.toFixed(2)}`;
                            if (n === 'Stop-Loss')         return ` 🛑 SL: $${_fmt(ctx.parsed.y)}`;
                            if (n === 'Buy Signal')        return ` ▼ Buy: $${_fmt(ctx.parsed.y)}`;
                            if (n === 'Sell Signal')       return ` ▲ Sell: $${_fmt(ctx.parsed.y)}`;
                            if (n === 'Test Buy Signal')   return ` 🛠 [T] Buy: $${_fmt(ctx.parsed.y)}`;
                            if (n === 'Test Sell Signal')  return ` 🛠 [T] Sell: $${_fmt(ctx.parsed.y)}`;
                            return null;
                        },
                    },
                },
            },
        },
    });

    window.rsiChart   = rsiChart;
    window.candleChart = rsiChart;

    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const raw = btn.dataset.minutes;
            setChartInterval(raw === 'all' ? null : Number(raw));
        });
    });
}

// ── Render ─────────────────────────────────────────────────────────────────────
function _renderView() {
    if (!rsiChart) return;
    const cutoffMs = _viewMinutes !== null ? Date.now() - _viewMinutes * 60 * 1000 : null;

    // Candles
    const visCandles = cutoffMs ? _candles.filter(c => c.x >= cutoffMs) : _candles.slice();

    // RSI buffer slice
    const vTs = [], vRsi = [], vBuy = [], vSell = [], vTB = [], vTS = [];
    _buf.ts.forEach((t, i) => {
        if (cutoffMs && t !== null && t < cutoffMs) return;
        vTs.push(t); vRsi.push(_buf.rsi[i]);
        vBuy.push(_buf.buy[i]); vSell.push(_buf.sell[i]);
        vTB.push(_buf.testBuy[i]); vTS.push(_buf.testSell[i]);
    });

    const toXY  = (ts, arr) => ts.map((t, i) => t != null && arr[i] != null ? {x:t, y:arr[i]} : null).filter(Boolean);
    const rsiXY = toXY(vTs, vRsi);

    const oversoldSeries   = _generateStepwiseSeries(vTs, _buf.rsiThresholdHistory.oversold,   currentOversold);
    const overboughtSeries = _generateStepwiseSeries(vTs, _buf.rsiThresholdHistory.overbought, currentOverbought);
    const oversoldXY   = vTs.map((t,i) => t!=null ? {x:t, y:oversoldSeries[i]}   : null).filter(Boolean);
    const overboughtXY = vTs.map((t,i) => t!=null ? {x:t, y:overboughtSeries[i]} : null).filter(Boolean);

    // SL flat line spans candle range
    const slData = (currentSlPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:currentSlPrice }, { x:visCandles[visCandles.length-1].x, y:currentSlPrice }]
        : [];

    // Map candles to simple line points
    const priceLineXY = visCandles.map(c => ({ x: c.x, y: c.c }));

    rsiChart.data.datasets[0].data = visCandles;
    rsiChart.data.datasets[1].data = priceLineXY;
    rsiChart.data.datasets[2].data = rsiXY;
    rsiChart.data.datasets[3].data = slData;
    rsiChart.data.datasets[3].hidden = slData.length === 0;
    rsiChart.data.datasets[4].data = oversoldXY;
    rsiChart.data.datasets[5].data = overboughtXY;
    rsiChart.data.datasets[6].data = toXY(vTs, vBuy);
    rsiChart.data.datasets[7].data = toXY(vTs, vSell);
    rsiChart.data.datasets[8].data = toXY(vTs, vTB);
    rsiChart.data.datasets[9].data = toXY(vTs, vTS);
    rsiChart.update('none');
}

// ── Public API ─────────────────────────────────────────────────────────────────
function setChartInterval(minutes) {
    _viewMinutes = minutes;
    _renderView();
    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        const raw = btn.dataset.minutes;
        btn.classList.toggle('active', minutes === null ? raw === 'all' : Number(raw) === minutes);
    });
}

function setRsiHistory(points) {
    if (!points || !Array.isArray(points)) return;
    _buf.ts = []; _buf.rsi = [];
    _buf.buy = []; _buf.sell = []; _buf.buyPrice = []; _buf.sellPrice = [];
    _buf.testBuy = []; _buf.testSell = []; _buf.testBuyPrice = []; _buf.testSellPrice = [];
    points.forEach(p => {
        _buf.ts.push(p.timestamp ? new Date(p.timestamp).getTime() : null);
        _buf.rsi.push(p.rsi);
        _buf.buy.push(null); _buf.sell.push(null);
        _buf.buyPrice.push(null); _buf.sellPrice.push(null);
        _buf.testBuy.push(null); _buf.testSell.push(null);
        _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);
    });
    _renderView();
}

function updateRsiChart(rsiValue, timestamp, priceValue = null) {
    if (!rsiChart || rsiValue == null) return;
    _buf.ts.push(timestamp ? new Date(timestamp).getTime() : null);
    _buf.rsi.push(rsiValue);
    _buf.buy.push(null); _buf.sell.push(null);
    _buf.buyPrice.push(null); _buf.sellPrice.push(null);
    _buf.testBuy.push(null); _buf.testSell.push(null);
    _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);
    if (_buf.ts.length > MAX_BUFFER) {
        ['ts','rsi','buy','sell','buyPrice','sellPrice','testBuy','testSell','testBuyPrice','testSellPrice']
            .forEach(k => _buf[k].shift());
    }
    _renderView();
}

function updateChartSl(price) { currentSlPrice = price; _renderView(); }
function updateCandleChartSl(price) { updateChartSl(price); }
function setCandleInterval(minutes) { /* unified — no-op */ }

function updateCandleChart(candles) {
    _candles = candles.slice(-MAX_CANDLES);
    _renderView();
}

function upsertCandle(candle) {
    const last = _candles[_candles.length - 1];
    if (last && last.x === candle.x) { _candles[_candles.length - 1] = candle; }
    else { _candles.push(candle); if (_candles.length > MAX_CANDLES) _candles.shift(); }
    _renderView();
}

function markBuySignal(price, isTest = false) {
    if (!_buf.ts.length) return;
    const i = _buf.ts.length - 1;
    if (isTest) { _buf.testBuy[i] = price; _buf.testBuyPrice[i] = price; }
    else        { _buf.buy[i] = price;     _buf.buyPrice[i] = price; }
    _renderView();
}

function markSellSignal(price, isTest = false) {
    if (!_buf.ts.length) return;
    const i = _buf.ts.length - 1;
    if (isTest) { _buf.testSell[i] = price; _buf.testSellPrice[i] = price; }
    else        { _buf.sell[i] = price;     _buf.sellPrice[i] = price; }
    _renderView();
}

function markSignalAtTime(isoTimestamp, direction, price, isTest = false) {
    if (!isoTimestamp || !_buf.ts.length) return;
    const ms = new Date(isoTimestamp).getTime();
    let closestIdx = -1, minDiff = Infinity;
    _buf.ts.forEach((t, i) => { if (t==null) return; const d=Math.abs(t-ms); if(d<minDiff){minDiff=d;closestIdx=i;} });
    if (closestIdx < 0) return;
    if (direction === 'sell') {
        if (isTest) { _buf.testSell[closestIdx]=price; _buf.testSellPrice[closestIdx]=price; }
        else        { _buf.sell[closestIdx]=price;     _buf.sellPrice[closestIdx]=price; }
    } else {
        if (isTest) { _buf.testBuy[closestIdx]=price;  _buf.testBuyPrice[closestIdx]=price; }
        else        { _buf.buy[closestIdx]=price;      _buf.buyPrice[closestIdx]=price; }
    }
    _renderView();
}

function markCandleBuy(tsMs,  price) { markSignalAtTime(new Date(tsMs).toISOString(), 'buy',  price, false); }
function markCandleSell(tsMs, price) { markSignalAtTime(new Date(tsMs).toISOString(), 'sell', price, false); }

function updateChartThresholds(oversold, overbought) {
    currentOversold = oversold; currentOverbought = overbought; _renderView();
}

function setRsiThresholdHistory(history) {
    if (!history || !Array.isArray(history)) return;
    _buf.rsiThresholdHistory.oversold = history
        .filter(h=>h.type==='oversold').map(h=>({ts:new Date(h.timestamp).getTime(),val:h.value})).sort((a,b)=>a.ts-b.ts);
    _buf.rsiThresholdHistory.overbought = history
        .filter(h=>h.type==='overbought').map(h=>({ts:new Date(h.timestamp).getTime(),val:h.value})).sort((a,b)=>a.ts-b.ts);
    _renderView();
}

function _generateStepwiseSeries(visibleTs, history, fallback) {
    return visibleTs.map(t => {
        if (t === null) return null;
        let val = fallback;
        for (let i = history.length-1; i >= 0; i--) { if (history[i].ts <= t) { val=history[i].val; break; } }
        return val;
    });
}

function _fmt(v) {
    return v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

document.addEventListener('DOMContentLoaded', initRsiChart);
