/**
 * index.js — Main entry point for the modular chart system.
 * 
 * Exports all public functions to the global window object to maintain
 * backward compatibility with legacy scripts and external modules.
 */

import { state } from './state.js';
import { initRsiChart } from './core.js';
import { setupChartInteractions } from './interaction.js';
import * as api from './api.js';
import * as markers from './markers.js';

// ── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    console.log('--- Initializing Modular Chart (ES Modules) ---');
    const chart = initRsiChart();
    if (chart) {
        setupChartInteractions();
    }
});

// ── Global Exports (Backward Compatibility) ──────────────────────────────────

// Shared State (read-only for external scripts is preferred, but writeable for legacy)
window.state ??= {};
// We merge our chart state into the existing window.state if needed, 
// or just expose the chart-specific ones.
Object.assign(window, {
    // API Functions
    setMarkerVisibility:       api.setMarkerVisibility,
    setRsiHistory:             api.setRsiHistory,
    updateRsiChart:            api.updateRsiChart,
    updateRsiUltraChart:       api.updateRsiUltraChart,
    updateChartSl:             api.updateChartSl,
    updateCandleChartSl:       api.updateChartSl,
    updateChartTp:             api.updateChartTp,
    updateCandleChartTp:       api.updateChartTp,
    updateChartEntry:          api.updateChartEntry,
    updateChartOpenPositionBuy: api.updateChartOpenPositionBuy,
    updateChartBcPrice:        api.updateChartBcPrice,
    updateChartBcSellPrice:    api.updateChartBcSellPrice,
    updateChartModeVisibility: api.updateChartModeVisibility,
    setChartInterval:          api.setChartInterval,
    setChartEnv:               api.setChartEnv,
    recordRsiThresholdChange:  api.recordRsiThresholdChange,
    updateChartThresholds:     api.updateChartThresholds,
    setRsiThresholdHistory:    api.setRsiThresholdHistory,
    getLatestRsi:              api.getLatestRsi,
    getLatestPrice:            api.getLatestPrice,
    getRecentCandles:          api.getRecentCandles,
    
    // Candle Updates
    upsertCandle:              api.upsertCandle,
    updateCandleChart:         api.updateCandleChart,
    
    // Marker Functions
    markBuySignal:             markers.markBuySignal,
    markSellSignal:            markers.markSellSignal,
    markSignalAtTime:          markers.markSignalAtTime,
    markCandleBuy:             markers.markCandleBuy,
    markCandleSell:            markers.markCandleSell,
    updateChartWithPosition:   markers.updateChartWithPosition,
    clearOpenPositionFromChart: markers.clearOpenPositionFromChart,
});

// Keep reference to the chart instance globally
// Note: core.js already sets state.rsiChart
Object.defineProperty(window, 'rsiChart', {
    get: () => state.rsiChart,
    set: (v) => { state.rsiChart = v; }
});
Object.defineProperty(window, 'candleChart', {
    get: () => state.rsiChart // Both aliases point to the same combined chart
});
