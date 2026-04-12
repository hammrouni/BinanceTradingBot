/**
 * interaction.js — Logic for chart-specific interactions like drag-to-adjust targets.
 */

import { state } from './state.js';
import { renderView, fmtNum } from './rendering.js';

export function setupChartInteractions() {
    const canvas = document.getElementById('rsi-chart');
    if (!canvas || !state.rsiChart) return;
    
    let bcDragging = null; // 'buy' or 'sell'
    const BC_HIT_PX = 10;
    let dragRafPending = false;

    canvas.addEventListener('mousedown', (e) => {
        if (!state.rsiChart) return;
        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        
        // Check Buy line first
        if (state.currentBcPrice != null) {
            const bcY = state.rsiChart.scales.yPrice.getPixelForValue(state.currentBcPrice);
            if (Math.abs(y - bcY) <= BC_HIT_PX) {
                bcDragging = 'buy';
                canvas.style.cursor = 'ns-resize';
                e.preventDefault();
                return;
            }
        }
        
        // Check Sell line second
        if (state.currentBcSellPrice != null) {
            const bcSellY = state.rsiChart.scales.yPrice.getPixelForValue(state.currentBcSellPrice);
            if (Math.abs(y - bcSellY) <= BC_HIT_PX) {
                bcDragging = 'sell';
                canvas.style.cursor = 'ns-resize';
                e.preventDefault();
                return;
            }
        }
    });

    canvas.addEventListener('mousemove', (e) => {
        if (!state.rsiChart) return;
        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;

        if (bcDragging) {
            const newPrice = state.rsiChart.scales.yPrice.getValueForPixel(y);
            if (newPrice != null && newPrice > 0) {
                const rounded = Math.round(newPrice * 100) / 100;

                if (bcDragging === 'buy') {
                    state.currentBcPrice = rounded;
                    const input = document.getElementById('bc-buy-price');
                    if (input) {
                        input.value = fmtNum(state.currentBcPrice, 2);
                        input.classList.add('dirty');
                    }
                } else {
                    state.currentBcSellPrice = rounded;
                    const input = document.getElementById('bc-sell-price');
                    if (input) {
                        input.value = fmtNum(state.currentBcSellPrice, 2);
                        input.classList.add('dirty');
                    }
                }

                // Sync module-system state
                const cfg = window.state?.currentConfig;
                if (cfg) {
                    if (bcDragging === 'buy') cfg.bc_buy_price = rounded;
                    else cfg.bc_sell_price = rounded;
                }

                // TP always follows BC buy price
                const tpInput = document.getElementById('take-profit-pct');
                const tpPct = tpInput ? (parseFloat(tpInput.value) || 0) : 0;
                state.currentTpPrice = tpPct > 0 ? Math.round(state.currentBcPrice * (1 + tpPct / 100) * 100) / 100 : null;

                // Throttle renders to one per animation frame
                if (!dragRafPending) {
                    dragRafPending = true;
                    requestAnimationFrame(() => {
                        dragRafPending = false;
                        renderView();
                    });
                }
            }
        } else {
            // Check hover for BOTH lines to show cursor
            let onLine = false;
            if (state.currentBcPrice != null) {
                const bcY = state.rsiChart.scales.yPrice.getPixelForValue(state.currentBcPrice);
                if (Math.abs(y - bcY) <= BC_HIT_PX) onLine = true;
            }
            if (!onLine && state.currentBcSellPrice != null) {
                const bcSellY = state.rsiChart.scales.yPrice.getPixelForValue(state.currentBcSellPrice);
                if (Math.abs(y - bcSellY) <= BC_HIT_PX) onLine = true;
            }
            canvas.style.cursor = onLine ? 'ns-resize' : 'default';
        }
    });

    const stopDragging = () => {
        if (bcDragging) {
            bcDragging = null;
            canvas.style.cursor = 'default';
            if (typeof window.autoSaveConfig === 'function') window.autoSaveConfig();
        }
    };

    window.addEventListener('mouseup', stopDragging);
    canvas.addEventListener('mouseleave', stopDragging);
}
