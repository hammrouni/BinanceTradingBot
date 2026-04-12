/**
 * plugins.js — Custom Chart.js plugins for the BinanceTradingBot chart.
 */

import { state } from './state.js';

// ── RSI zone background plugin ─────────────────────────────────────────────────
export const rsiZonePlugin = {
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

// ── Axis Tag Plugin ─────────────────────────────────────────────────────────────
export const axisTagPlugin = {
    id: 'axisTags',
    afterDatasetsDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        const { left, right, top, bottom } = chartArea;

        const drawTag = (yScale, value, color, label = null, isDashed = false) => {
            if (value == null) return;
            const y = yScale.getPixelForValue(value);
            if (y < top || y > bottom) return;

            ctx.save();
            ctx.font = 'bold 10px sans-serif';
            const valueStr = value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            const txt = label ? `${label}: $${valueStr}` : `$${valueStr}`;
            const padding = 4;
            const textWidth = ctx.measureText(txt).width;
            const tagWidth = textWidth + padding * 2;
            const tagHeight = 18;

            const isRightAxis = yScale.id === 'yPrice';
            const x = isRightAxis ? right : left - tagWidth;

            ctx.fillStyle = color;
            if (isDashed) {
                ctx.setLineDash([2, 2]);
            }

            ctx.beginPath();
            if (isRightAxis) {
                ctx.moveTo(x, y);
                ctx.lineTo(x + 6, y - tagHeight/2);
                ctx.lineTo(x + tagWidth + 6, y - tagHeight/2);
                ctx.lineTo(x + tagWidth + 6, y + tagHeight/2);
                ctx.lineTo(x + 6, y + tagHeight/2);
                ctx.closePath();
            } else {
                const rsiTxt = value.toFixed(1);
                const rsiWidth = ctx.measureText(rsiTxt).width + padding * 2;
                const rsiX = left - rsiWidth - 6;
                ctx.moveTo(left, y);
                ctx.lineTo(left - 6, y - tagHeight/2);
                ctx.lineTo(rsiX, y - tagHeight/2);
                ctx.lineTo(rsiX, y + tagHeight/2);
                ctx.lineTo(left - 6, y + tagHeight/2);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = '#fff';
                ctx.textAlign = 'right';
                ctx.fillText(rsiTxt, left - 10, y + 4);
                ctx.restore();
                return;
            }
            ctx.fill();

            ctx.fillStyle = '#fff';
            ctx.textAlign = 'left';
            ctx.fillText(txt, x + 10, y + 4);
            ctx.restore();
        };

        // 1. Current Price Tag
        const lastCandle = state.candles.length > 0 ? state.candles[state.candles.length - 1] : null;
        if (lastCandle) {
            drawTag(scales.yPrice, lastCandle.c, 'rgba(71, 85, 105, 0.9)'); 
        }

        // 2. Active Targets (only if visible)
        if (state.chartMode === 'BC' && state.currentBcPrice != null)     drawTag(scales.yPrice, state.currentBcPrice, 'rgba(14, 165, 233, 0.9)', 'BUY');
        if (state.chartMode === 'BC' && state.currentBcSellPrice != null) drawTag(scales.yPrice, state.currentBcSellPrice, 'rgba(245, 158, 11, 0.9)', 'SELL');
        if (state.currentEntryPrice != null)  drawTag(scales.yPrice, state.currentEntryPrice, 'rgba(34, 197, 94, 0.9)', 'ENTRY');
        if (state.currentSlPrice != null)     drawTag(scales.yPrice, state.currentSlPrice, 'rgba(239, 68, 68, 0.9)', 'SL');
        if (state.currentTpPrice != null)     drawTag(scales.yPrice, state.currentTpPrice, 'rgba(245, 158, 11, 0.9)', 'TP');

        // 3. Current RSI Tag (on the left)
        const lastRsi = state.buf.rsi.length > 0 ? state.buf.rsi[state.buf.rsi.length - 1] : null;
        if (lastRsi != null) {
            drawTag(scales.yRsi, lastRsi, 'rgba(59, 130, 246, 0.9)');
        }
    }
};

// ── OHLC Legend Plugin ────────────────────────────────────────────────────────
export const ohlcLegendPlugin = {
    id: 'ohlcLegend',
    afterDraw(chart) {
        const { ctx, chartArea } = chart;
        if (!chartArea) return;
        const lastCandle = state.candles.length > 0 ? state.candles[state.candles.length - 1] : null;
        if (!lastCandle) return;

        const lastRsi = state.buf.rsi.length > 0 ? state.buf.rsi[state.buf.rsi.length - 1] : null;
        
        ctx.save();
        ctx.font = 'bold 11px sans-serif';
        ctx.textBaseline = 'top';
        
        const x = chartArea.left + 10;
        const y = chartArea.top + 8;
        
        const drawItem = (label, value, startX, color = '#64748b') => {
            ctx.fillStyle = '#94a3b8';
            ctx.fillText(label + ':', startX, y);
            const labelWidth = ctx.measureText(label + ':').width;
            ctx.fillStyle = color;
            const valStr = (typeof value === 'number') ? value.toLocaleString('en-US', { minimumFractionDigits: 2 }) : value;
            ctx.fillText(valStr, startX + labelWidth + 4, y);
            return startX + labelWidth + ctx.measureText(valStr).width + 18;
        };
        
        let curX = x;
        const candleColor = lastCandle.c >= lastCandle.o ? '#16a34a' : '#dc2626';
        curX = drawItem('O', lastCandle.o, curX, candleColor);
        curX = drawItem('H', lastCandle.h, curX, candleColor);
        curX = drawItem('L', lastCandle.l, curX, candleColor);
        curX = drawItem('C', lastCandle.c, curX, candleColor);
        if (lastRsi != null) {
            drawItem('RSI', lastRsi.toFixed(2), curX, '#3b82f6');
        }
        ctx.restore();
    }
};
