/**
 * config_manager.js — Logic for handling the configuration form, presets, and validation.
 */

import { state, updateState } from './state.js';
import { fmtNum, stripFmt, showErrorBanner, applyEnvironmentVisibility } from './ui_manager.js';

export function setupConfigForm() {
    const form = document.getElementById('config-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('btn-save-config');
        if (btn) btn.disabled = true;

        const formData = new FormData(form);
        const data = {};
        
        // Convert FormData to object, handling checkboxes correctly
        const activeModes = [];
        const activeFilters = [];
        
        for (const [key, value] of formData.entries()) {
            if (key === 'active_modes') {
                activeModes.push(value);
            } else if (key === 'active_filters') {
                activeFilters.push(value);
            } else {
                data[key] = value;
            }
        }
        
        data.active_modes = activeModes;
        data.active_filters = activeFilters;

        // Strip formatting from price/amount fields
        if (data.trade_amount_usd) data.trade_amount_usd = parseFloat(stripFmt(data.trade_amount_usd));
        if (data.bc_buy_price) data.bc_buy_price = parseFloat(stripFmt(data.bc_buy_price));
        if (data.bc_sell_price) data.bc_sell_price = parseFloat(stripFmt(data.bc_sell_price));
        
        // Clean up empty filters
        if (data.rsi_oversold === '') delete data.rsi_oversold;
        if (data.rsi_overbought === '') delete data.rsi_overbought;
        
        try {
            const res = await window.updateConfig(data);
            const statusEl = document.getElementById('config-status');
            if (res.ok) {
                if (statusEl) {
                    statusEl.textContent = '✓ Configuration saved successfully!';
                    statusEl.className = 'status-success';
                    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
                }
                updateState('currentConfig', data);
                applyEnvironmentVisibility(data.trading_env);
                if (typeof window.refreshDashboard === 'function') window.refreshDashboard();
            } else {
                const body = await res.json();
                showErrorBanner(body.error || 'Failed to save configuration');
            }
        } catch (e) {
            showErrorBanner('Error saving configuration: ' + e.message);
        } finally {
            if (btn) btn.disabled = false;
        }
    });

    const presetSelect = document.getElementById('config-preset');
    presetSelect?.addEventListener('change', (e) => {
        const val = e.target.value;
        if (!val) return;
        applyPreset(val);
    });

    const modeRsi = document.getElementById('mode-rsi');
    const modeBc = document.getElementById('mode-bc');
    
    // Toggle field visibility based on active modes
    const refreshVisibility = () => {
        document.getElementById('rsi-mode-fields')?.classList.toggle('hidden', !modeRsi.checked);
        document.getElementById('bc-mode-fields')?.classList.toggle('hidden', !modeBc.checked);
    };

    modeRsi?.addEventListener('change', refreshVisibility);
    modeBc?.addEventListener('change', refreshVisibility);

    // Initial visibility refresh
    refreshVisibility();

    // Toggle fields for filters
    const setupFilterToggle = (id, fieldsId) => {
        const cb = document.getElementById(id);
        const fields = document.getElementById(fieldsId);
        if (!cb || !fields) return;
        const fn = () => fields.classList.toggle('hidden', !cb.checked);
        cb.addEventListener('change', fn);
        fn();
    };

    setupFilterToggle('filter-bb', 'filter-bb-fields');
    setupFilterToggle('filter-bounce', 'filter-bounce-fields');
    setupFilterToggle('filter-bear', 'filter-bear-fields');
}

export function fillConfigForm(config) {
    if (!config) return;
    
    const f = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val ?? '';
    };

    f('trading-pair', config.trading_pair);
    f('trade-amount', config.trade_amount_usd ? fmtNum(config.trade_amount_usd, 2) : '');
    f('rsi-oversold', config.rsi_oversold);
    f('rsi-overbought', config.rsi_overbought);
    f('bc-buy-price', config.bc_buy_price ? fmtNum(config.bc_buy_price, 2) : '');
    f('bc-sell-price', config.bc_sell_price ? fmtNum(config.bc_sell_price, 2) : '');
    f('bb-period', config.bb_period);
    f('price-bounce-ticks', config.price_bounce_ticks);
    f('bear-trend-candles', config.bear_trend_candles);
    f('bear-trend-pct', config.bear_trend_pct);
    f('take-profit-pct', config.take_profit_pct);
    f('stop-loss-pct', config.stop_loss_pct);
    f('trailing-stop-pct', config.trailing_stop_pct);

    // Checkboxes
    const modes = config.active_modes || ['RSI'];
    const filters = config.active_filters || [];

    const modeRsi = document.getElementById('mode-rsi');
    const modeBc = document.getElementById('mode-bc');
    if (modeRsi) modeRsi.checked = modes.includes('RSI');
    if (modeBc) modeBc.checked = modes.includes('BC');

    ['BB', 'BOUNCE', 'BEAR'].forEach(id => {
        const cb = document.getElementById('filter-' + id.toLowerCase());
        if (cb) cb.checked = filters.includes(id);
    });

    // Manually trigger change events for visibility logic
    [modeRsi, modeBc].forEach(cb => cb?.dispatchEvent(new Event('change')));
    ['filter-bb', 'filter-bounce', 'filter-bear'].forEach(id => {
        document.getElementById(id)?.dispatchEvent(new Event('change'));
    });
}

function applyPreset(preset) {
    const presets = {
        aggressive: { rsi_oversold: 35, rsi_overbought: 65, take_profit_pct: 1.5, stop_loss_pct: 1.0, trailing_stop_pct: 0.3 },
        conservative: { rsi_oversold: 28, rsi_overbought: 72, take_profit_pct: 3.5, stop_loss_pct: 1.5, trailing_stop_pct: 0.8 },
        balanced: { rsi_oversold: 30, rsi_overbought: 70, take_profit_pct: 2.5, stop_loss_pct: 1.2, trailing_stop_pct: 0.5 },
        scalper: { rsi_oversold: 40, rsi_overbought: 60, take_profit_pct: 0.8, stop_loss_pct: 0.5, trailing_stop_pct: 0.2 },
        protected: { rsi_oversold: 30, rsi_overbought: 70, take_profit_pct: 3.0, stop_loss_pct: 2.0, trailing_stop_pct: 1.0, active_filters: ['BOUNCE', 'BEAR'] }
    };
    
    const p = presets[preset];
    if (!p) return;
    
    // Fill the form using our fillConfigForm with a partial object – works because it handles nulls
    fillConfigForm({ ...state.currentConfig, ...p });
}
