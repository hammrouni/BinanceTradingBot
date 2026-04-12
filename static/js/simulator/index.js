/**
 * index.js — Main orchestrator for the Parameter Simulator.
 */

import { state, updateState, getCachedMarketHistory, cacheMarketHistory } from './state.js';
import * as api from './api.js';
import * as ui from './ui_manager.js';
import * as form from './form_manager.js';
import * as chart from './chart_integration.js';

document.addEventListener('DOMContentLoaded', async () => {
    chart.initHistoryChart();
    await form.prefillFromCurrentConfig();
    form.updateModeVisibility();
    form.setupToggles();
    
    // Load saved simulation params from localStorage
    const savedParams = localStorage.getItem('simulator_params');
    if (savedParams) {
        try {
            form.setFormValues(JSON.parse(savedParams));
        } catch (e) {
            console.warn('Failed to load saved simulator params:', e);
        }
    }
    
    // Initial data load
    await loadHistoricalData();
});

// ── Event Handlers ──────────────────────────────────────────────────────────

async function loadHistoricalData() {
    ui.hideError();
    const btn = document.getElementById('btn-run-simulation');
    const originalText = btn.innerHTML;
    if (btn) btn.disabled = true;
    ui.showStatus('Loading historical data...');

    try {
        const params = form.getFormValues();
        
        // Try to get cached market history first
        const symbol = 'BTCUSDT'; // TODO: Get this from config or form
        const days = params.historical_days;
        const cachedData = getCachedMarketHistory(symbol, days);
        
        let data;
        if (cachedData) {
            // Use cached data
            ui.showStatus('Using cached historical data...');
            // Format cached data to match expected API response
            const chartData = [];
            const step = cachedData.length > 1000 ? Math.max(1, Math.floor(cachedData.length / 1000)) : 1;
            for (let i = 0; i < cachedData.length; i += step) {
                const p = cachedData[i];
                chartData.push({
                    'timestamp': p.timestamp,
                    'price': p.price,
                    'rsi': p.rsi
                });
            }
            data = {
                status: 'ok',
                data_points: cachedData.length,
                market_history: chartData
            };
            // Also update the chart with sampled data from cache
            if (data.market_history) {
                chart.updateHistoryChart(data.market_history);
            }
        } else {
            // Fetch new data
            data = await api.fetchSimulatorData(params);
            
            if (data.status === 'error') {
                ui.showError(data.message || 'Failed to load data');
                ui.hideStatus();
                return;
            }
            
            // Cache the full resolution market history if available
            if (data.full_market_history) {
                cacheMarketHistory(data.full_market_history, symbol, days);
            }
        }

        ui.hideStatus();
        if (data.market_history) {
            chart.updateHistoryChart(data.market_history);
        }

        const summaryDiv = document.getElementById('results-summary');
        if (summaryDiv && data.data_points) {
            summaryDiv.innerHTML = `<p><strong>${ui.fmtInt(data.data_points)}</strong> data points loaded. Click "Run Simulation" to test parameters.</p>`;
        }
    } catch (err) {
        ui.showError(`Request failed: ${err.message}`);
        ui.hideStatus();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}


async function runSimulation() {
    ui.hideError();
    document.getElementById('results-table-container')?.classList.add('hidden');
    document.getElementById('results-tbody').innerHTML = '';
    document.getElementById('results-thead').innerHTML = '';

    const btn = document.getElementById('btn-run-simulation');
    const originalText = btn.innerHTML;
    if (btn) btn.disabled = true;
    ui.showStatus('Running simulation...');

    try {
        const params = form.getFormValues();
        
        // Add cached market history if available
        const symbol = 'BTCUSDT'; // TODO: Get this from config or form
        const days = params.historical_days;
        const cachedData = getCachedMarketHistory(symbol, days);
        if (cachedData) {
            params.market_history = cachedData;
            ui.showStatus('Running simulation with cached historical data...');
        }

        const data = await api.runSimulationSweep(params);

        if (data.status === 'error') {
            ui.showError(data.message || 'Simulation failed');
            ui.hideStatus();
            return;
        }

        ui.hideStatus();
        ui.displayResults(data, chart.updateHistoryChart);
    } catch (err) {
        ui.showError(`Request failed: ${err.message}`);
        ui.hideStatus();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}

async function runWithCurrentConfig() {
    ui.hideError();
    document.getElementById('results-table-container')?.classList.add('hidden');
    document.getElementById('results-tbody').innerHTML = '';
    document.getElementById('results-thead').innerHTML = '';

    const btn = document.getElementById('btn-run-current');
    const originalText = btn.innerHTML;
    if (btn) btn.disabled = true;
    ui.showStatus('Running simulation with current config...');

    try {
        const days = parseInt(document.getElementById('historical-days').value) || 1;
        const initialBalance = parseFloat(document.getElementById('initial-balance').value) || 1000;
        const feePct = parseFloat(document.getElementById('fee-pct').value) || 0;

        // Try to get cached market history first
        const symbol = 'BTCUSDT'; // TODO: Get this from config or form
        const cachedData = getCachedMarketHistory(symbol, days);
        
        let data;
        if (cachedData) {
            // Use cached data for simulation
            ui.showStatus('Using cached historical data for simulation...');
            // We need to call the API but with the cached market history
            // Unfortunately, the API doesn't accept pre-fetched market history
            // So we'll proceed with the normal API call but note that ideally
            // we'd want to modify the API to accept cached data
            data = await api.runCurrentConfigSim(days, initialBalance, feePct);
            
            // If the API call succeeded, we could optionally verify it used similar data
            // but for now we'll just proceed with the result
        } else {
            // Fetch new data via normal API call
            data = await api.runCurrentConfigSim(days, initialBalance, feePct);
            
            // If successful, cache the market history for next time
            if (data.status === 'ok' && data.market_history) {
                // Note: runCurrentConfigSim doesn't return full market history in its response
                // We'd need to modify the API to return it, or make a separate call
                // For now, we'll rely on loadHistoricalData to populate the cache
            }
        }

        if (data.status === 'error') {
            ui.showError(data.message || 'Simulation failed');
            ui.hideStatus();
            return;
        }

        ui.hideStatus();
        ui.displayCurrentConfigResult(data, chart.updateHistoryChart, chart.historyChart);
        
        // Plot events for current config result
        if (data.events) {
            chart.plotSimulationEvents(data.events);
            document.getElementById('history-chart-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (err) {
        ui.showError(`Request failed: ${err.message}`);
        ui.hideStatus();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}

// ── Global Exports for legacy/HTML handlers ───────────────────────────────

window.viewSimulationOnChart = async function(event, result) {
    const btn = event.target;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '...';
    btn.classList.add('loading');
    ui.hideError();

    try {
        const formValues = form.getFormValues();
        const replayRequest = {
            mode: formValues.mode,
            historical_days: formValues.historical_days,
            initial_balance: formValues.initial_balance,
            trade_amount_usd: formValues.trade_amount_usd,
            stop_loss_pct: result.stop_loss_pct,
            take_profit_pct: result.take_profit_pct,
            trailing_stop_pct: result.trailing_stop_pct,
            rsi_oversold: result.rsi_oversold,
            rsi_overbought: result.rsi_overbought,
            price_bounce_ticks: formValues.price_bounce_ticks,
            bear_trend_candles: formValues.bear_trend_candles,
            bear_trend_pct: formValues.bear_trend_pct,
            bc_buy_price: result.bc_buy_price,
            bc_sell_price: result.bc_sell_price,
        };

        const data = await api.fetchSimulationTrades(replayRequest);

        if (data.status === 'error') {
            ui.showError(data.message || 'Failed to fetch trade markers');
            return;
        }

        chart.plotSimulationEvents(data.events);
        
        // Also plot the horizontal target lines if BC mode
        if (replayRequest.mode === 'bc') {
            chart.plotTargetPriceLines(replayRequest.bc_buy_price, replayRequest.bc_sell_price);
        } else {
            // For RSI, we could draw lines too, but RSI handles 0-100 well.
            // Clear any old lines
            chart.plotTargetPriceLines(null, null);
        }

        document.getElementById('history-chart-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
        ui.showError(`Request failed: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
        btn.classList.remove('loading');
    }
};

window.applyConfig = async function(result) {
    try {
        const statusData = await api.getBotStatus();
        const position = statusData?.data?.position ?? statusData?.position ?? null;

        if (position && position.entry_price) {
            ui.showApplyModal(position, result, () => doApplyConfig(result));
        } else {
            let confirmMsg;
            if (result.strategy === 'BC') {
                confirmMsg = `Apply BC configuration?\n\nBuy Offset: ${result.bc_buy_offset_pct}% | Sell Offset: ${result.bc_sell_offset_pct}%\nBuy Price: $${ui.fmt(result.bc_buy_price)} | Sell Price: $${ui.fmt(result.bc_sell_price)}\nSL: ${result.stop_loss_pct != null ? result.stop_loss_pct + '%' : '—'} | TP: ${result.take_profit_pct != null ? result.take_profit_pct + '%' : '—'}\n\nNote: BC prices are based on historical median price ($${ui.fmt(result.ref_price)}) and will be set as fixed targets.`;
            } else {
                confirmMsg = `Apply RSI configuration?\n\nRSI OS: ${result.rsi_oversold ?? '—'} | RSI OB: ${result.rsi_overbought ?? '—'}\nSL: ${result.stop_loss_pct != null ? result.stop_loss_pct + '%' : '—'} | TP: ${result.take_profit_pct != null ? result.take_profit_pct + '%' : '—'}${result.trailing_stop_pct != null ? '\nTrail SL: ' + result.trailing_stop_pct + '%' : ''}`;
            }
            if (!confirm(confirmMsg)) return;
            await doApplyConfig(result);
        }
    } catch (err) {
        ui.showError(`Failed to check bot status: ${err.message}`);
    }
};

async function doApplyConfig(result) {
    try {
        const configData = await api.getBotConfig();
        if (configData.status === 'error') {
            ui.showError('Failed to fetch current config');
            return;
        }

        const currentConfig = configData.data;
        let newConfig;

        if (result.strategy === 'BC') {
            newConfig = {
                ...currentConfig,
                active_modes: ['BC'],
                bc_buy_price: result.bc_buy_price,
                bc_sell_price: result.bc_sell_price,
                stop_loss_pct: result.stop_loss_pct,
                take_profit_pct: result.take_profit_pct,
                trailing_stop_pct: result.trailing_stop_pct ?? currentConfig.trailing_stop_pct,
            };
        } else {
            newConfig = {
                ...currentConfig,
                active_modes: ['RSI'],
                rsi_oversold: result.rsi_oversold,
                rsi_overbought: result.rsi_overbought,
                stop_loss_pct: result.stop_loss_pct,
                take_profit_pct: result.take_profit_pct,
                trailing_stop_pct: result.trailing_stop_pct ?? currentConfig.trailing_stop_pct,
            };
        }
        delete newConfig.trading_env;

        const response = await api.updateBotConfig(newConfig);
        const data = await response.json();
        if (data.status === 'error') {
            ui.showError(`Failed to apply config: ${data.message}`);
            return;
        }

        window.location.href = '/';
    } catch (err) {
        ui.showError(`Failed to apply config: ${err.message}`);
    }
}

// ── Bind Form Submission ──────────────────────────────────────────────────

document.getElementById('simulator-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    // Save current params to localStorage before running
    const params = form.getFormValues();
    localStorage.setItem('simulator_params', JSON.stringify(params));
    
    await runSimulation();
});

document.getElementById('btn-run-current')?.addEventListener('click', async () => {
    // Save current params to localStorage before running
    const params = form.getFormValues();
    localStorage.setItem('simulator_params', JSON.stringify(params));
    
    await runWithCurrentConfig();
});

document.getElementById('btn-prefill-config')?.addEventListener('click', async () => {
    ui.showStatus('Fetching active bot configuration...');
    await form.prefillFromCurrentConfig();
    ui.hideStatus();
});

document.getElementById('historical-days')?.addEventListener('change', loadHistoricalData);
document.getElementById('btn-dismiss-error')?.addEventListener('click', ui.hideError);
