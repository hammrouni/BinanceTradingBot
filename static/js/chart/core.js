/**
 * core.js — Chart.js initialization and base configuration for the modular chart.
 */

import { state, REASON_LABEL, loadThresholdHistory } from './state.js';
import { rsiZonePlugin, axisTagPlugin, ohlcLegendPlugin } from './plugins.js';
import { setChartInterval } from './api.js';

export function initRsiChart() {
    const canvas = document.getElementById('rsi-chart');
    if (!canvas) return;
    if (state.rsiChart) { state.rsiChart.destroy(); state.rsiChart = null; }
    loadThresholdHistory();

    const ctx = canvas.getContext('2d');
    state.rsiChart = new Chart(ctx, {
        type: 'bar',
        plugins: [rsiZonePlugin, axisTagPlugin, ohlcLegendPlugin],
        data: {
            datasets: [
                /* 0 – Candlestick OHLC */
                { label: 'Price', type: 'candlestick', data: [], yAxisID: 'yPrice', order: 5,
                  color: { up:'rgba(22,163,74,.85)', down:'rgba(220,38,38,.85)', unchanged:'rgba(100,116,139,.75)' } },
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
                /* 6 – Buy (prod) — triangle UP, placed below candle low */
                { label: 'Buy Signal', type: 'scatter', data: [], backgroundColor: '#22c55e',
                  pointStyle: 'triangle', pointRadius: 10, pointRotation: 0, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 7 – Sell (prod) — triangle DOWN, placed above candle high */
                { label: 'Sell Signal', type: 'scatter', data: [], backgroundColor: '#ef4444',
                  pointStyle: 'triangle', pointRadius: 10, pointRotation: 180, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 8 – Buy (test) — triangle UP, placed below candle low */
                { label: 'Test Buy Signal', type: 'scatter', data: [], backgroundColor: '#a855f7',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 0, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
                /* 9 – Sell (test) — triangle DOWN, placed above candle high */
                { label: 'Test Sell Signal', type: 'scatter', data: [], backgroundColor: '#475569',
                  pointStyle: 'triangle', pointRadius: 8, pointRotation: 180, borderColor: '#ffffff', borderWidth: 1.5, yAxisID: 'yPrice', order: 1 },
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
                  pointStyle: 'rect', pointRadius: 5, borderColor: '#ffffff', borderWidth: 1, yAxisID: 'yRsi', order: 2 },
                /* 14 – Take Profit */
                { label: 'Take Profit', type: 'line', data: [], borderColor: 'rgba(245,158,11,0.7)', borderWidth: 1.5,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 15 – Entry Price */
                { label: 'Entry', type: 'line', data: [], borderColor: 'rgba(34,197,94,0.85)', borderWidth: 2,
                  borderDash: [6, 4], pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 16 – Open Position Buy */
                { label: 'Open Position Buy', type: 'line', data: [], borderColor: '#22c55e', borderWidth: 2,
                  pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 17 – Target Buy Price ($) */
                { label: 'Target Buy Price ($)', type: 'line', data: [], borderColor: 'rgba(56,189,248,0.9)', borderWidth: 2,
                  borderDash: [8, 4], pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 18 – Target Sell Price ($) */
                { label: 'Target Sell Price ($)', type: 'line', data: [], borderColor: 'rgba(245,158,11,0.9)', borderWidth: 2,
                  borderDash: [8, 4], pointRadius: 0, fill: false, tension: 0, yAxisID: 'yPrice', hidden: true, order: 2 },
                /* 19 – RSI Ultra Raw */
                { label: 'RSI Ultra', type: 'line', data: [], borderColor: '#f59e0b', borderWidth: 2,
                  pointRadius: 0, tension: 0.3, fill: false, yAxisID: 'yRsi', hidden: true, order: 3 },
                /* 20 – RSI Ultra Signal */
                { label: 'RSI Ultra Signal', type: 'line', data: [], borderColor: '#fca5a5', borderWidth: 1.5,
                  borderDash: [3, 2], pointRadius: 0, tension: 0.3, fill: false, yAxisID: 'yRsi', hidden: true, order: 3 },
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
                            if (state.hideTestData && item.text.includes('Test')) return false;
                            if (state.hideProdData && !item.text.includes('Test') && (item.text.includes('Buy') || item.text.includes('Sell'))) return false;
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
                            const f = (v) => v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});

                            if (n === 'RSI (14)')         return ` RSI: ${val?.toFixed(2)}`;
                            if (n === 'Stop-Loss')         return ` 🛑 SL: $${f(val)}`;
                            if (n === 'Take Profit')      return ` 🎯 TP: $${f(val)}`;
                            if (n === 'Entry')            return ` 📥 Entry: $${f(val)}`;
                            if (n === 'Open Position Buy') return ` 🟢 Buy Entry: $${f(val)}`;
                            if (n === 'Target Buy Price ($)')  return ` 🎯 Buy: $${f(val)} (drag to adjust)`;
                            if (n === 'Target Sell Price ($)') return ` 🏁 Sell: $${f(val)} (drag to adjust)`;
                            if (n === 'RSI Ultra')         return ` RSI Ultra: ${val?.toFixed(2)}`;
                            if (n === 'RSI Ultra Signal')  return ` Signal: ${val?.toFixed(2)}`;
                            
                            // Only show Buy/Sell signals for the Price-side datasets, not the RSI-side duplicates
                            if ((n.includes('Buy') || n.includes('Sell')) && !n.includes('(RSI)')) {
                                const side = n.includes('Buy') ? '▼ Buy' : '▲ Sell';
                                const prefix = n.includes('Test') ? '🛠 [T] ' : '';
                                const reason = ctx.raw.reason;
                                const reasonLabel = reason ? (REASON_LABEL[reason] || reason) : null;
                                const lines = [` ${prefix}${side}: $${f(val)}`];
                                if (reasonLabel) lines.push(` ${reasonLabel}`);
                                if (amt) lines.push(` Amount: $${f(amt)}`);
                                return lines;
                            }
                            return null;
                        },
                    },
                },
            },
        },
    });

    document.querySelectorAll('.chart-interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const raw = btn.dataset.minutes;
            setChartInterval(raw === 'all' ? null : Number(raw));
        });
    });

    return state.rsiChart;
}
