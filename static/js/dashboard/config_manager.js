/**
 * config_manager.js — Logic for handling the configuration form, presets, and validation.
 */

import { state, updateState } from './state.js';
import { fmtNum, stripFmt, showErrorBanner, applyEnvironmentVisibility } from './ui_manager.js';

export function setupConfigForm() {
    const form = document.getElementById('config-form');
    if (!form) return;

    // If state has no config, try to load from localStorage
    if (!state.currentConfig || Object.keys(state.currentConfig).length === 0) {
        const savedConfig = localStorage.getItem('tradingBotConfig');
        if (savedConfig) {
            try {
                const parsed = JSON.parse(savedConfig);
                updateState('currentConfig', parsed);
            } catch (e) {
                console.error('Failed to parse saved config from localStorage', e);
            }
        }
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('btn-save-config');
        if (btn) btn.disabled = true;

        const formData = new FormData(form);
        const data = {
            ...(state.currentConfig || {})
        };
        
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
        // Unchecked checkboxes are absent from FormData: send an explicit boolean
        data.bc_use_full_balance = formData.has('bc_use_full_balance');

        // Fields that should be numeric (float or int) or null if empty
        const numericFields = [
            'trade_amount_usd', 'rsi_oversold', 'rsi_overbought', 
            'bc_buy_price', 'bc_sell_price', 
            'price_bounce_ticks', 'bear_trend_candles', 'bear_trend_pct',
            'take_profit_pct', 'stop_loss_pct', 'trailing_stop_pct',
            'min_move_pct', 'sl_lookback_candles', 'sl_buffer_pct',
            'rsi_ultra_period', 'rsi_ultra_signal_period', 'rsi_ultra_zone_mid',
            'ma_filter_period', 'ema_fast_period', 'ema_slow_period'
        ];

        numericFields.forEach(key => {
            if (data[key] === undefined) return;
            const val = stripFmt(data[key]);
            if (val === '') {
                data[key] = null;
            } else {
                const n = parseFloat(val);
                data[key] = isNaN(n) ? null : n;
            }
        });

        try {
            const res = await window.updateConfig(data);
            const statusEl = document.getElementById('config-status');
            if (res.ok) {
                if (statusEl) {
                    statusEl.textContent = '✓ Configuration saved successfully!';
                    statusEl.className = 'status-success';
                    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
                }
                // Capture env before state update so we can detect a real change
                const prevEnv = state.currentConfig?.trading_env;
                updateState('currentConfig', data);
                // Save config to localStorage for persistence across reloads
                try {
                    localStorage.setItem('tradingBotConfig', JSON.stringify(data));
                } catch (e) {
                    console.error('Failed to save config to localStorage', e);
                }

                // Keep chart RSI threshold lines in sync
                if (typeof window.recordRsiThresholdChange === 'function')
                    window.recordRsiThresholdChange(data.rsi_oversold ?? null, data.rsi_overbought ?? null);

                // Keep chart BC price lines in sync
                if (typeof window.updateChartBcPrice === 'function')
                    window.updateChartBcPrice(data.bc_buy_price > 0 ? data.bc_buy_price : null);
                if (typeof window.updateChartBcSellPrice === 'function')
                    window.updateChartBcSellPrice(data.bc_sell_price > 0 ? data.bc_sell_price : null);

                // Refresh the mode field panel visibility to reflect the saved mode
                const modeRsi = document.getElementById('mode-rsi');
                const modeBc  = document.getElementById('mode-bc');
                const modeUltra = document.getElementById('mode-rsi-ultra');
                document.getElementById('rsi-mode-fields')?.classList.toggle('hidden', !(modeRsi?.checked));
                document.getElementById('bc-mode-fields')?.classList.toggle('hidden',  !(modeBc?.checked));
                document.getElementById('rsi-ultra-mode-fields')?.classList.toggle('hidden', !(modeUltra?.checked));

                // Notify chart of mode change (BC price lines vs RSI zones)
                const active_modes_saved = data.active_modes || ['RSI'];
                let savedMode = 'RSI';
                if (active_modes_saved.includes('BC')) savedMode = 'BC';
                else if (active_modes_saved.includes('RSI_ULTRA')) savedMode = 'RSI_ULTRA';
                if (typeof window.updateChartModeVisibility === 'function')
                    window.updateChartModeVisibility(savedMode);

                // Only call env visibility if the environment truly changed — prevents test
                // markers from appearing on every config save (trading_env is read-only from .env)
                if (data.trading_env && data.trading_env !== prevEnv) {
                    applyEnvironmentVisibility(data.trading_env);
                }

                if (typeof window.updateWhatBotWillDo === 'function')
                    window.updateWhatBotWillDo(window.state?.botState || state.botState || 'STOPPED');
            } else {
                const body = await res.json();
                let errorMsg = 'Failed to save configuration';
                if (body.error) {
                    errorMsg = body.error;
                } else if (body.detail && Array.isArray(body.detail)) {
                    // FastAPI validation errors (422)
                    const details = body.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join('; ');
                    errorMsg = `Validation failed: ${details}`;
                }
                showErrorBanner(errorMsg);
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
    const modeUltra = document.getElementById('mode-rsi-ultra');

    // Toggle field visibility based on selected mode (radio — only one active)
    const refreshVisibility = () => {
        document.getElementById('rsi-mode-fields')?.classList.toggle('hidden', !modeRsi?.checked);
        document.getElementById('bc-mode-fields')?.classList.toggle('hidden', !modeBc?.checked);
        document.getElementById('rsi-ultra-mode-fields')?.classList.toggle('hidden', !modeUltra?.checked);
    };

    const notifyChartMode = () => {
        const mode = modeBc?.checked ? 'BC' : (modeUltra?.checked ? 'RSI_ULTRA' : 'RSI');
        if (typeof window.updateChartModeVisibility === 'function')
            window.updateChartModeVisibility(mode);
        if (typeof window.updateWhatBotWillDo === 'function')
            window.updateWhatBotWillDo(window.state?.botState || 'STOPPED');
    };

    modeRsi?.addEventListener('change', () => { refreshVisibility(); notifyChartMode(); });
    modeBc?.addEventListener('change',  () => { refreshVisibility(); notifyChartMode(); });
    modeUltra?.addEventListener('change', () => { refreshVisibility(); notifyChartMode(); });

    // Initial visibility refresh
    refreshVisibility();

    // Live preview: refresh "What Bot Will Do" + RSI threshold lines as user types
    const refreshPreview = () => {
        if (typeof window.updateWhatBotWillDo !== 'function') return;
        const draft = _readFormDraft();
        window.updateWhatBotWillDo(window.state?.botState || 'STOPPED', draft);
    };
    const refreshRsiLines = () => {
        if (typeof window.updateChartThresholds !== 'function') return;
        const os = parseInt(document.getElementById('rsi-oversold')?.value);
        const ob = parseInt(document.getElementById('rsi-overbought')?.value);
        window.updateChartThresholds(
            (!isNaN(os) && os >= 1 && os <= 100) ? os : null,
            (!isNaN(ob) && ob >= 1 && ob <= 100) ? ob : null
        );
    };
    document.getElementById('rsi-oversold')?.addEventListener('input', refreshRsiLines);
    document.getElementById('rsi-overbought')?.addEventListener('input', refreshRsiLines);
    form.addEventListener('input', refreshPreview);
    form.addEventListener('change', refreshPreview);

    // Toggle fields for filters
    const setupFilterToggle = (id, fieldsId) => {
        const cb = document.getElementById(id);
        const fields = document.getElementById(fieldsId);
        if (!cb || !fields) return;
        const fn = () => fields.classList.toggle('hidden', !cb.checked);
        cb.addEventListener('change', fn);
        fn();
    };

    setupFilterToggle('filter-bounce', 'filter-bounce-fields');
    setupFilterToggle('filter-bear', 'filter-bear-fields');
    setupFilterToggle('filter-ma', 'filter-ma-fields');
    setupFilterToggle('filter-ema-trend', 'filter-ema-trend-fields');

    // TP/SL Profitability Warning
    const tpEl = document.getElementById('take-profit-pct');
    const slEl = document.getElementById('stop-loss-pct');
    [tpEl, slEl].forEach(el => {
        el?.addEventListener('input', checkTpSlWarning);
        el?.addEventListener('change', checkTpSlWarning);
    });

    // Numerical input formatting
    setupInputFormatting();
}

/** 
 * Bind focus/blur formatting to price text inputs.
 * On focus → strip commas (raw number for editing).
 * On blur  → reformat with commas.
 */
export function setupInputFormatting() {
    const bind = (id, decimals = 2) => {
        const el = document.getElementById(id);
        if (!el) {
            console.warn(`[ConfigManager] Input ID not found for formatting: ${id}`);
            return;
        }
        el.addEventListener('focus', () => {
            const raw = stripFmt(el.value);
            if (raw !== '' && !isNaN(Number(raw))) el.value = raw;
        });
        el.addEventListener('blur', () => {
            const raw = stripFmt(el.value);
            if (raw !== '' && !isNaN(Number(raw))) {
                el.value = fmtNum(Number(raw), decimals);
            }
        });
        console.log(`[ConfigManager] Bound formatting to ${id}`);
    };

    bind('trade-amount', 2);
    bind('bc-buy-price', 2);
    bind('bc-sell-price', 2);
    bind('rsi-oversold', 0);
    bind('rsi-overbought', 0);
    bind('rsi-ultra-period', 0);
    bind('rsi-ultra-signal-period', 0);
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
    f('tp-anchor', config.tp_anchor || 'entry');
    const fullBal = document.getElementById('bc-use-full-balance');
    if (fullBal) fullBal.checked = !!config.bc_use_full_balance;
    f('price-bounce-ticks', config.price_bounce_ticks);
    f('bear-trend-candles', config.bear_trend_candles);
    f('bear-trend-pct', config.bear_trend_pct);
    f('take-profit-pct', config.take_profit_pct);
    f('stop-loss-pct', config.stop_loss_pct);
    f('trailing-stop-pct', config.trailing_stop_pct);
    f('min-move-pct', config.min_move_pct);
    f('sl-lookback-candles', config.sl_lookback_candles);
    f('sl-buffer-pct', config.sl_buffer_pct);
    f('rsi-ultra-period', config.rsi_ultra_period);
    f('rsi-ultra-signal-period', config.rsi_ultra_signal_period);
    f('rsi-ultra-zone-mid', config.rsi_ultra_zone_mid);
    f('ma-filter-period', config.ma_filter_period);
    f('ema-fast-period', config.ema_fast_period);
    f('ema-slow-period', config.ema_slow_period);

    // Header selectors (language and theme)
    f('agent-language', config.agent_language || 'EN');
    f('agent-theme', config.agent_theme || 'technical');

    // Radio — pick the first recognised mode, default to RSI
    const modes = config.active_modes || ['RSI'];
    const activeMode = modes.find(m => m === 'RSI' || m === 'BC' || m === 'RSI_ULTRA') || 'RSI';
    const filters = config.active_filters || [];

    const modeRsi = document.getElementById('mode-rsi');
    const modeBc = document.getElementById('mode-bc');
    const modeUltra = document.getElementById('mode-rsi-ultra');
    if (modeRsi) modeRsi.checked = (activeMode === 'RSI');
    if (modeBc)  modeBc.checked  = (activeMode === 'BC');
    if (modeUltra) modeUltra.checked = (activeMode === 'RSI_ULTRA');

    ['BOUNCE', 'BEAR', 'MA', 'EMA_TREND'].forEach(id => {
        const cb = document.getElementById('filter-' + id.toLowerCase().replace('_', '-'));
        if (cb) cb.checked = filters.includes(id);
    });

    // Manually trigger change events for visibility logic (also notifies chart)
    [modeRsi, modeBc, modeUltra].forEach(cb => cb?.dispatchEvent(new Event('change')));
    // Direct call in case chart is ready but listeners fired before chart init
    if (typeof window.updateChartModeVisibility === 'function')
        window.updateChartModeVisibility(activeMode);
    ['filter-bounce', 'filter-bear', 'filter-ma', 'filter-ema-trend'].forEach(id => {
        document.getElementById(id)?.dispatchEvent(new Event('change'));
    });

    checkTpSlWarning();
}

function _readFormDraft() {
    const g = id => {
        const el = document.getElementById(id);
        if (!el) return null;
        const v = stripFmt(el.value);
        if (v === '') return null;
        const n = parseFloat(v);
        return isNaN(n) ? v : n;
    };
    const modeBc = document.getElementById('mode-bc');
    const modeUltra = document.getElementById('mode-rsi-ultra');
    return {
        ...(state.currentConfig || {}),
        trading_pair:      document.getElementById('trading-pair')?.value || state.currentConfig?.trading_pair,
        active_modes:      modeBc?.checked ? ['BC'] : (modeUltra?.checked ? ['RSI_ULTRA'] : ['RSI']),
        rsi_oversold:      g('rsi-oversold'),
        rsi_overbought:    g('rsi-overbought'),
        bc_buy_price:      g('bc-buy-price'),
        bc_sell_price:     g('bc-sell-price'),
        rsi_ultra_period: g('rsi-ultra-period'),
        rsi_ultra_signal_period: g('rsi-ultra-signal-period'),
        rsi_ultra_zone_mid: g('rsi-ultra-zone-mid'),
        take_profit_pct:   g('take-profit-pct'),
        stop_loss_pct:     g('stop-loss-pct'),
        trailing_stop_pct: g('trailing-stop-pct'),
        min_move_pct:      g('min-move-pct'),
        sl_lookback_candles: g('sl-lookback-candles'),
        sl_buffer_pct:     g('sl-buffer-pct'),
    };
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

function checkTpSlWarning() {
    const tpEl = document.getElementById('take-profit-pct');
    const slEl = document.getElementById('stop-loss-pct');
    const warningEl = document.getElementById('tp-sl-warning');
    if (!tpEl || !slEl || !warningEl) return;

    const tpVal = tpEl.value;
    const slVal = slEl.value;
    
    if (tpVal === '' || slVal === '') {
        warningEl.classList.add('hidden');
        return;
    }

    const tp = parseFloat(tpVal) || 0;
    const sl = parseFloat(slVal) || 0;
    const fee = 0.2; // 0.1% buy + 0.1% sell

    if (tp > 0 && sl > 0 && tp < (sl + fee)) {
        warningEl.textContent = `Warning: Take Profit (${tp.toFixed(1)}%) is less than Stop-Loss (${sl.toFixed(1)}%) + Fees (${fee.toFixed(1)}%). This setup may result in a net loss.`;
        warningEl.classList.remove('hidden');
    } else {
        warningEl.classList.add('hidden');
    }
}
