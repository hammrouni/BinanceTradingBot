// chart.js — Combined Candlestick (price) + RSI chart

let rsiChart = null;
let currentOversold   = 30;
let currentOverbought = 70;
let currentSlPrice    = null;
let currentTpPrice    = null;
let currentEntryPrice = null;
let currentOpenPositionBuy = null;

const MAX_BUFFER  = 1440;
const MAX_CANDLES = 1440;

const _buf = {
    ts: [], rsi: [],
    buy: [], sell: [], buyPrice: [], sellPrice: [], buyAmount: [], sellAmount: [], buyReason: [], sellReason: [],
    testBuy: [], testSell: [], testBuyPrice: [], testSellPrice: [], testBuyAmount: [], testSellAmount: [], testBuyReason: [], testSellReason: [],
    rsiThresholdHistory: { oversold: [], overbought: [] },
};

const _REASON_LABEL = {
    'buy_signal':  '📈 RSI Oversold',
    'stop_loss':   '🛑 Stop Loss',
    'take_profit': '🎯 Take Profit',
    'signal':      '📉 RSI Overbought',
    'manual':      '✋ Manual',
};
let _candles     = [];
let _viewMinutes = 120;
let _hideTestData = false;

// ── RSI zone background plugin ─────────────────────────────────────────────────
const rsiZonePlugin = {
    id: 'rsiZones',
    beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        const S = scales.yRsi;
        if (!chartArea || !S) return;
        const { left, right, top, bottom } = chartArea;
        
        ctx.save();
        // Red zone (Oversold - Below 30)
        const yOS = S.getPixelForValue(30);
        ctx.fillStyle = 'rgba(220,38,38,0.06)';
        ctx.fillRect(left, yOS, right - left, bottom - yOS);
        
        // Green zone (Overbought - Above 70)
        const yOB  = S.getPixelForValue(70);
        ctx.fillStyle = 'rgba(22,163,74,0.06)';
        ctx.fillRect(left, top, right - left, yOB - top);
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
                { label: 'Stop-Loss', type: 'line', data: [], borderColor: 'rgba(239,68,68,0.7)', borderWidth: 1.5,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 4 – Oversold threshold */
                { label: 'Oversold', type: 'line', data: [], borderColor: '#ef4444', borderDash: [5,5],
                  borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'yRsi', stepped: 'after', order: 6 },
                /* 5 – Overbought threshold */
                { label: 'Overbought', type: 'line', data: [], borderColor: '#22c55e', borderDash: [5,5],
                  borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'yRsi', stepped: 'after', order: 6 },
                /* 6 – Buy (prod) */
                { label: 'Buy Signal', type: 'scatter', data: [], backgroundColor: '#f97316',
                  pointStyle: 'triangle', pointRadius: 10, pointRotation: 180, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 7 – Sell (prod) */
                { label: 'Sell Signal', type: 'scatter', data: [], backgroundColor: '#ef4444',
                  pointStyle: 'triangle', pointRadius: 10, pointRotation: 0, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 8 – Buy (test) */
                { label: 'Test Buy Signal', type: 'scatter', data: [], backgroundColor: '#a855f7',
                  pointStyle: 'rect', pointRadius: 8, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 9 – Sell (test) */
                { label: 'Test Sell Signal', type: 'scatter', data: [], backgroundColor: '#475569',
                  pointStyle: 'rect', pointRadius: 8, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 10 – Buy (prod) on RSI */
                { label: 'Buy (RSI)', type: 'scatter', data: [], backgroundColor: '#f97316',
                  pointStyle: 'rect', pointRadius: 6, borderColor: '#ffffff', borderWidth: 1, yAxisID: 'yRsi', order: 2 },
                /* 11 – Sell (prod) on RSI */
                { label: 'Sell (RSI)', type: 'scatter', data: [], backgroundColor: '#ef4444',
                  pointStyle: 'rect', pointRadius: 6, borderColor: '#ffffff', borderWidth: 1, yAxisID: 'yRsi', order: 2 },
                /* 12 – Buy (test) on RSI */
                { label: 'Test Buy (RSI)', type: 'scatter', data: [], backgroundColor: '#a855f7',
                  pointStyle: 'rect', pointRadius: 5, borderColor: '#ffffff', borderWidth: 1, yAxisID: 'yRsi', order: 2 },
                /* 13 – Sell (test) on RSI */
                { label: 'Test Sell (RSI)', type: 'scatter', data: [], backgroundColor: '#475569',
                  pointRadius: 5, borderColor: '#ffffff', borderWidth: 1, yAxisID: 'yRsi', order: 2 },
                /* 14 – Take Profit */
                { label: 'Take Profit', type: 'line', data: [], borderColor: 'rgba(245,158,11,0.7)', borderWidth: 1.5,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 15 – Entry Price */
                { label: 'Entry', type: 'line', data: [], borderColor: '#0ea5e9', borderWidth: 1.5,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 16 – Open Position Buy */
                { label: 'Open Position Buy', type: 'line', data: [], borderColor: '#22c55e', borderWidth: 2,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
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
                legend: { 
                    display: true,
                    position: 'bottom',
                    labels: { 
                        color:'#94a3b8', font:{ size:10 }, boxWidth: 12, boxHeight: 12, padding: 8,
                        filter: function(item) {
                            if (_hideTestData && item.text.includes('Test')) return false;
                            return true;
                        }
                    }
                },
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
                                // Hide the main candlestick OHLC from the popup
                                return null;
                            }
                            const n = ctx.dataset.label;
                            const val = ctx.parsed.y;
                            const amt = ctx.raw.amount;

                            if (n === 'RSI (14)')         return ` RSI: ${val?.toFixed(2)}`;
                            if (n === 'Stop-Loss')         return ` 🛑 SL: $${_fmt(val)}`;
                            if (n === 'Take Profit')      return ` 🎯 TP: $${_fmt(val)}`;
                            if (n === 'Entry')            return ` 📥 Entry: $${_fmt(val)}`;
                            if (n === 'Open Position Buy') return ` 🟢 Buy Entry: $${_fmt(val)}`;
                            
                            // Only show Buy/Sell signals for the Price-side datasets, not the RSI-side duplicates
                            if ((n.includes('Buy') || n.includes('Sell')) && !n.includes('(RSI)')) {
                                const side = n.includes('Buy') ? '▼ Buy' : '▲ Sell';
                                const prefix = n.includes('Test') ? '🛠 [T] ' : '';
                                const reason = ctx.raw.reason;
                                const reasonLabel = reason ? (_REASON_LABEL[reason] || reason) : null;
                                const lines = [` ${prefix}${side}: $${_fmt(val)}`];
                                if (reasonLabel) lines.push(` ${reasonLabel}`);
                                if (amt) lines.push(` Amount: $${_fmt(amt)}`);
                                return lines;
                            }
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
    
    // Use the latest point in candles or buffer as the "now" for filtering
    const maxCandleTs = _candles.length > 0 ? _candles[_candles.length - 1].x : 0;
    const maxBufTs    = _buf.ts.length > 0 ? Math.max(..._buf.ts.filter(t => t !== null)) : 0;
    const latestTs    = Math.max(maxCandleTs, maxBufTs) || Date.now();

    const cutoffMs = _viewMinutes !== null ? latestTs - (_viewMinutes * 60 * 1000) : null;

    // Candles
    const visCandles = cutoffMs ? _candles.filter(c => c.x >= cutoffMs) : _candles.slice();

    // RSI buffer slice
    const vTs = [], vRsi = [], vBuy = [], vSell = [], vTB = [], vTS = [];
    const vBA = [], vSA = [], vTBA = [], vTSA = [];
    const vBR = [], vSR = [], vTBR = [], vTSR = [];
    _buf.ts.forEach((t, i) => {
        if (cutoffMs && t !== null && t < cutoffMs) return;
        vTs.push(t); vRsi.push(_buf.rsi[i]);
        vBuy.push(_buf.buy[i]); vSell.push(_buf.sell[i]);
        vTB.push(_buf.testBuy[i]); vTS.push(_buf.testSell[i]);
        vBA.push(_buf.buyAmount[i]); vSA.push(_buf.sellAmount[i]);
        vTBA.push(_buf.testBuyAmount[i]); vTSA.push(_buf.testSellAmount[i]);
        vBR.push(_buf.buyReason[i]); vSR.push(_buf.sellReason[i]);
        vTBR.push(_buf.testBuyReason[i]); vTSR.push(_buf.testSellReason[i]);
    });

    const toXY = (ts, arr, amtArr = [], reasonArr = []) =>
        ts.map((t, i) => t != null && arr[i] != null
            ? { x: t, y: arr[i], amount: amtArr[i] || null, reason: reasonArr[i] || null }
            : null
        ).filter(Boolean);
    const rsiXY = toXY(vTs, vRsi);

    const oversoldSeries   = _generateStepwiseSeries(vTs, _buf.rsiThresholdHistory.oversold,   currentOversold);
    const overboughtSeries = _generateStepwiseSeries(vTs, _buf.rsiThresholdHistory.overbought, currentOverbought);
    const oversoldXY   = vTs.map((t,i) => t!=null ? {x:t, y:oversoldSeries[i]}   : null).filter(Boolean);
    const overboughtXY = vTs.map((t,i) => t!=null ? {x:t, y:overboughtSeries[i]} : null).filter(Boolean);

    // Target lines (SL/TP) flat line spans candle range
    const slData = (currentSlPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:currentSlPrice }, { x:visCandles[visCandles.length-1].x, y:currentSlPrice }]
        : [];
    const tpData = (currentTpPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:currentTpPrice }, { x:visCandles[visCandles.length-1].x, y:currentTpPrice }]
        : [];
    const entryData = (currentEntryPrice != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:currentEntryPrice }, { x:visCandles[visCandles.length-1].x, y:currentEntryPrice }]
        : [];
    const openPosBuyData = (currentOpenPositionBuy != null && visCandles.length > 0)
        ? [{ x:visCandles[0].x, y:currentOpenPositionBuy }, { x:visCandles[visCandles.length-1].x, y:currentOpenPositionBuy }]
        : [];

    // Map candles to simple line points
    const priceLineXY = visCandles.map(c => ({ x: c.x, y: c.c }));

    rsiChart.data.datasets[0].data = visCandles;
    rsiChart.data.datasets[1].data = priceLineXY;
    rsiChart.data.datasets[2].data = rsiXY;
    rsiChart.data.datasets[3].data = slData;
    rsiChart.data.datasets[3].hidden = slData.length === 0;
    rsiChart.data.datasets[14].data = tpData;
    rsiChart.data.datasets[14].hidden = tpData.length === 0;
    rsiChart.data.datasets[15].data = entryData;
    rsiChart.data.datasets[15].hidden = entryData.length === 0;
    rsiChart.data.datasets[16].data = openPosBuyData;
    rsiChart.data.datasets[16].hidden = openPosBuyData.length === 0;
    rsiChart.data.datasets[4].data = oversoldXY;
    rsiChart.data.datasets[5].data = overboughtXY;
    rsiChart.data.datasets[6].data = toXY(vTs, vBuy,  vBA,  vBR);
    rsiChart.data.datasets[7].data = toXY(vTs, vSell, vSA,  vSR);
    rsiChart.data.datasets[8].data = toXY(vTs, vTB,   vTBA, vTBR);
    rsiChart.data.datasets[9].data = toXY(vTs, vTS,   vTSA, vTSR);

    rsiChart.data.datasets[10].data = toXY(vTs, vBuy.map((p,i)  => p != null ? vRsi[i] : null), vBA,  vBR);
    rsiChart.data.datasets[11].data = toXY(vTs, vSell.map((p,i) => p != null ? vRsi[i] : null), vSA,  vSR);
    rsiChart.data.datasets[12].data = toXY(vTs, vTB.map((p,i)   => p != null ? vRsi[i] : null), vTBA, vTBR);
    rsiChart.data.datasets[13].data = toXY(vTs, vTS.map((p,i)   => p != null ? vRsi[i] : null), vTSA, vTSR);

    // Visibility toggle for test data
    [8, 9, 12, 13].forEach(idx => {
        rsiChart.data.datasets[idx].hidden = _hideTestData;
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

        rsiChart.options.scales.yPrice.min = minY;
        rsiChart.options.scales.yPrice.max = maxY;

        // Banners for off-screen targets
        _updateTargetBanners(minY, maxY);
    }
    rsiChart.update('none');
}

function _updateTargetBanners(minY, maxY) {
    const tpBanner = document.getElementById('tp-banner');
    const slBanner = document.getElementById('sl-banner');
    if (!tpBanner || !slBanner) return;

    const lastCandle = _candles.length > 0 ? _candles[_candles.length - 1] : null;
    const currentPrice = lastCandle ? lastCandle.c : 0;

    // TP Banner
    if (currentTpPrice != null && currentTpPrice > maxY) {
        const pct = currentPrice > 0 ? ((currentTpPrice / currentPrice - 1) * 100).toFixed(1) : 0;
        tpBanner.innerHTML = `🎯 TP: $${_fmt(currentTpPrice)} (+${pct}%)`;
        tpBanner.classList.remove('hidden');
    } else {
        tpBanner.classList.add('hidden');
    }

    // SL Banner
    if (currentSlPrice != null && currentSlPrice < minY) {
        const pct = currentPrice > 0 ? ((currentSlPrice / currentPrice - 1) * 100).toFixed(1) : 0;
        slBanner.innerHTML = `🛑 SL: $${_fmt(currentSlPrice)} (${pct}%)`;
        slBanner.classList.remove('hidden');
    } else {
        slBanner.classList.add('hidden');
    }
}

function setChartHideTestData(hide) {
    _hideTestData = hide;
    _renderView();
}

function setChartEnv(isLive) {
    _hideTestData = isLive;
    _renderView();
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
    _buf.buyReason = []; _buf.sellReason = []; _buf.testBuyReason = []; _buf.testSellReason = [];
    points.forEach(p => {
        _buf.ts.push(p.timestamp ? new Date(p.timestamp).getTime() : null);
        _buf.rsi.push(p.rsi);
        _buf.buy.push(null); _buf.sell.push(null);
        _buf.buyPrice.push(null); _buf.sellPrice.push(null);
        _buf.buyAmount.push(null); _buf.sellAmount.push(null);
        _buf.testBuy.push(null); _buf.testSell.push(null);
        _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);
        _buf.testBuyAmount.push(null); _buf.testSellAmount.push(null);
        _buf.buyReason.push(null); _buf.sellReason.push(null);
        _buf.testBuyReason.push(null); _buf.testSellReason.push(null);
    });
    _renderView();
}

function updateRsiChart(rsiValue, timestamp, priceValue = null) {
    if (!rsiChart || rsiValue == null) return;
    _buf.ts.push(timestamp ? new Date(timestamp).getTime() : null);
    _buf.rsi.push(rsiValue);
    _buf.buy.push(null); _buf.sell.push(null);
    _buf.buyPrice.push(null); _buf.sellPrice.push(null);
    _buf.buyAmount.push(null); _buf.sellAmount.push(null);
    _buf.testBuy.push(null); _buf.testSell.push(null);
    _buf.testBuyPrice.push(null); _buf.testSellPrice.push(null);
    _buf.testBuyAmount.push(null); _buf.testSellAmount.push(null);
    _buf.buyReason.push(null); _buf.sellReason.push(null);
    _buf.testBuyReason.push(null); _buf.testSellReason.push(null);
    if (_buf.ts.length > MAX_BUFFER) {
        ['ts','rsi','buy','sell','buyPrice','sellPrice','buyAmount','sellAmount',
         'testBuy','testSell','testBuyPrice','testSellPrice','testBuyAmount','testSellAmount',
         'buyReason','sellReason','testBuyReason','testSellReason']
            .forEach(k => _buf[k].shift());
    }
    _renderView();
}

function updateChartSl(price) { currentSlPrice = price; _renderView(); }
function updateCandleChartSl(price) { updateChartSl(price); }
function updateChartTp(price) {
    currentTpPrice = price;
    _renderView();
}

function updateChartEntry(price) {
    currentEntryPrice = price;
    _renderView();
}

function updateChartOpenPositionBuy(price) {
    currentOpenPositionBuy = price;
    _renderView();
}

function updateCandleChartTp(price) { updateChartTp(price); }
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

function markBuySignal(price, isTest = false, amount = null, reason = null) {
    if (!_buf.ts.length) return;
    const i = _buf.ts.length - 1;
    if (isTest) {
        _buf.testBuy[i] = price;
        _buf.testBuyPrice[i] = price;
        _buf.testBuyAmount[i] = amount;
        _buf.testBuyReason[i] = reason;
    } else {
        _buf.buy[i] = price;
        _buf.buyPrice[i] = price;
        _buf.buyAmount[i] = amount;
        _buf.buyReason[i] = reason;
    }
    _renderView();
}

function markSellSignal(price, isTest = false, amount = null, reason = null) {
    if (!_buf.ts.length) return;
    const i = _buf.ts.length - 1;
    if (isTest) {
        _buf.testSell[i] = price;
        _buf.testSellPrice[i] = price;
        _buf.testSellAmount[i] = amount;
        _buf.testSellReason[i] = reason;
    } else {
        _buf.sell[i] = price;
        _buf.sellPrice[i] = price;
        _buf.sellAmount[i] = amount;
        _buf.sellReason[i] = reason;
    }
    _renderView();
}

function markSignalAtTime(isoTimestamp, direction, price, isTest = false, amount = null, reason = null) {
    if (!isoTimestamp || !_buf.ts.length) return;
    const ms = new Date(isoTimestamp).getTime();
    let closestIdx = -1, minDiff = Infinity;
    _buf.ts.forEach((t, i) => { if (t==null) return; const d=Math.abs(t-ms); if(d<minDiff){minDiff=d;closestIdx=i;} });
    if (closestIdx < 0) return;
    if (direction === 'sell') {
        if (isTest) {
            _buf.testSell[closestIdx] = price;
            _buf.testSellPrice[closestIdx] = price;
            _buf.testSellAmount[closestIdx] = amount;
            _buf.testSellReason[closestIdx] = reason;
        } else {
            _buf.sell[closestIdx] = price;
            _buf.sellPrice[closestIdx] = price;
            _buf.sellAmount[closestIdx] = amount;
            _buf.sellReason[closestIdx] = reason;
        }
    } else {
        if (isTest) {
            _buf.testBuy[closestIdx] = price;
            _buf.testBuyPrice[closestIdx] = price;
            _buf.testBuyAmount[closestIdx] = amount;
            _buf.testBuyReason[closestIdx] = reason;
        } else {
            _buf.buy[closestIdx] = price;
            _buf.buyPrice[closestIdx] = price;
            _buf.buyAmount[closestIdx] = amount;
            _buf.buyReason[closestIdx] = reason;
        }
    }
    _renderView();
}

function markCandleBuy(tsMs,  price, amount = null, reason = null) { markSignalAtTime(new Date(tsMs).toISOString(), 'buy',  price, false, amount, reason); }
function markCandleSell(tsMs, price, amount = null, reason = null) { markSignalAtTime(new Date(tsMs).toISOString(), 'sell', price, false, amount, reason); }

function updateChartThresholds(oversold, overbought) {
    currentOversold = oversold; currentOverbought = overbought; _renderView();
}

function getLatestRsi() {
    if (!_buf.rsi || _buf.rsi.length === 0) return null;
    return _buf.rsi[_buf.rsi.length - 1];
}

function getLatestPrice() {
    if (!_candles || _candles.length === 0) return null;
    const last = _candles[_candles.length - 1];
    return last.c;
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
