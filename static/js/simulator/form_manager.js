/**
 * form_manager.js — Handles the simulator form, validation, and pre-filling.
 */

import { getBotConfig } from './api.js';

export function getFormValues() {
    const mode = document.getElementById('mode').value;
    const initialBalance = parseFloat(document.getElementById('initial-balance').value);
    const tradeAmount = parseFloat(document.getElementById('trade-amount').value);
    const feePct = parseFloat(document.getElementById('fee-pct').value) || 0;
    const historicalDays = parseInt(document.getElementById('historical-days').value);

    // Shared exit controls
    const tpDisabled = document.getElementById('tp-disable').checked;
    const tpRange = tpDisabled ? null : [
        parseFloat(document.getElementById('tp-min').value),
        parseFloat(document.getElementById('tp-max').value),
        parseFloat(document.getElementById('tp-step').value),
    ];

    const tsDisabled = document.getElementById('ts-disable').checked;
    const tsRange = tsDisabled ? null : [
        parseFloat(document.getElementById('ts-min').value),
        parseFloat(document.getElementById('ts-max').value),
        parseFloat(document.getElementById('ts-step').value),
    ];

    const params = {
        mode,
        initial_balance: initialBalance,
        trade_amount_usd: tradeAmount,
        fee_pct: feePct,
        historical_days: historicalDays,
        stop_loss_range: [
            parseFloat(document.getElementById('sl-min').value),
            parseFloat(document.getElementById('sl-max').value),
            parseFloat(document.getElementById('sl-step').value),
        ],
        take_profit_range: tpRange,
        trailing_stop_range: tsRange,
    };

    if (mode === 'rsi') {
        const rsiOBDisabled = document.getElementById('rsi-ob-disable').checked;
        params.rsi_oversold_range = [
            parseFloat(document.getElementById('rsi-os-min').value),
            parseFloat(document.getElementById('rsi-os-max').value),
            parseFloat(document.getElementById('rsi-os-step').value),
        ];
        params.rsi_overbought_range = rsiOBDisabled ? null : [
            parseFloat(document.getElementById('rsi-ob-min').value),
            parseFloat(document.getElementById('rsi-ob-max').value),
            parseFloat(document.getElementById('rsi-ob-step').value),
        ];

        if (document.getElementById('bounce-enable').checked) {
            params.price_bounce_ticks = parseInt(document.getElementById('price-bounce-ticks').value);
        }
        if (document.getElementById('bear-enable').checked) {
            params.bear_trend_candles = parseInt(document.getElementById('bear-candles').value);
            params.bear_trend_pct = parseFloat(document.getElementById('bear-pct').value);
        }
    } else {
        params.bc_buy_offset_range = [
            parseFloat(document.getElementById('bc-buy-min').value),
            parseFloat(document.getElementById('bc-buy-max').value),
            parseFloat(document.getElementById('bc-buy-step').value),
        ];
        params.bc_sell_offset_range = [
            parseFloat(document.getElementById('bc-sell-min').value),
            parseFloat(document.getElementById('bc-sell-max').value),
            parseFloat(document.getElementById('bc-sell-step').value),
        ];
    }

    return params;
}

export function setFormValues(params) {
    if (!params) return;
    
    const modeEl = document.getElementById('mode');
    if (modeEl && params.mode) modeEl.value = params.mode;
    
    const initialBalanceEl = document.getElementById('initial-balance');
    if (initialBalanceEl && params.initial_balance != null) initialBalanceEl.value = params.initial_balance;
    
    const tradeAmountEl = document.getElementById('trade-amount');
    if (tradeAmountEl && params.trade_amount_usd != null) tradeAmountEl.value = params.trade_amount_usd;
    
    const feePctEl = document.getElementById('fee-pct');
    if (feePctEl && params.fee_pct != null) feePctEl.value = params.fee_pct;
    
    const historicalDaysEl = document.getElementById('historical-days');
    if (historicalDaysEl && params.historical_days != null) historicalDaysEl.value = params.historical_days;

    // Shared exit controls
    if (params.stop_loss_range) {
        const [min, max, step] = params.stop_loss_range;
        const slMinEl = document.getElementById('sl-min');
        const slMaxEl = document.getElementById('sl-max');
        const slStepEl = document.getElementById('sl-step');
        if (slMinEl && min != null) slMinEl.value = min;
        if (slMaxEl && max != null) slMaxEl.value = max;
        if (slStepEl && step != null) slStepEl.value = step;
    }

    if (params.take_profit_range) {
        const [min, max, step] = params.take_profit_range;
        document.getElementById('tp-disable').checked = false;
        const tpMinEl = document.getElementById('tp-min');
        const tpMaxEl = document.getElementById('tp-max');
        const tpStepEl = document.getElementById('tp-step');
        if (tpMinEl && min != null) tpMinEl.value = min;
        if (tpMaxEl && max != null) tpMaxEl.value = max;
        if (tpStepEl && step != null) tpStepEl.value = step;
    } else {
        document.getElementById('tp-disable').checked = true;
    }

    if (params.trailing_stop_range) {
        const [min, max, step] = params.trailing_stop_range;
        document.getElementById('ts-disable').checked = false;
        const tsMinEl = document.getElementById('ts-min');
        const tsMaxEl = document.getElementById('ts-max');
        const tsStepEl = document.getElementById('ts-step');
        if (tsMinEl && min != null) tsMinEl.value = min;
        if (tsMaxEl && max != null) tsMaxEl.value = max;
        if (tsStepEl && step != null) tsStepEl.value = step;
    } else {
        document.getElementById('ts-disable').checked = true;
    }

    if (params.mode === 'rsi' || params.rsi_oversold_range) {
        if (params.rsi_oversold_range) {
            const [min, max, step] = params.rsi_oversold_range;
            const rsiOsMinEl = document.getElementById('rsi-os-min');
            const rsiOsMaxEl = document.getElementById('rsi-os-max');
            const rsiOsStepEl = document.getElementById('rsi-os-step');
            if (rsiOsMinEl && min != null) rsiOsMinEl.value = min;
            if (rsiOsMaxEl && max != null) rsiOsMaxEl.value = max;
            if (rsiOsStepEl && step != null) rsiOsStepEl.value = step;
        }

        if (params.rsi_overbought_range) {
            const [min, max, step] = params.rsi_overbought_range;
            document.getElementById('rsi-ob-disable').checked = false;
            const rsiObMinEl = document.getElementById('rsi-ob-min');
            const rsiObMaxEl = document.getElementById('rsi-ob-max');
            const rsiObStepEl = document.getElementById('rsi-ob-step');
            if (rsiObMinEl && min != null) rsiObMinEl.value = min;
            if (rsiObMaxEl && max != null) rsiObMaxEl.value = max;
            if (rsiObStepEl && step != null) rsiObStepEl.value = step;
        } else {
            document.getElementById('rsi-ob-disable').checked = true;
        }

        if (params.price_bounce_ticks != null) {
            document.getElementById('bounce-enable').checked = true;
            document.getElementById('bounce-inputs')?.classList.remove('hidden');
            document.getElementById('price-bounce-ticks').value = params.price_bounce_ticks;
        } else {
            document.getElementById('bounce-enable').checked = false;
            document.getElementById('bounce-inputs')?.classList.add('hidden');
        }

        if (params.bear_trend_candles != null && params.bear_trend_pct != null) {
            document.getElementById('bear-enable').checked = true;
            const bearInputs = document.getElementById('bear-inputs');
            if (bearInputs) {
                bearInputs.classList.remove('hidden');
                bearInputs.style.display = 'grid';
            }
            document.getElementById('bear-candles').value = params.bear_trend_candles;
            document.getElementById('bear-pct').value = params.bear_trend_pct;
        } else {
            document.getElementById('bear-enable').checked = false;
            const bearInputs = document.getElementById('bear-inputs');
            if (bearInputs) {
                bearInputs.classList.add('hidden');
                bearInputs.style.display = '';
            }
        }
    } else if (params.mode === 'bc' || params.bc_buy_offset_range) {
        if (params.bc_buy_offset_range) {
            const [min, max, step] = params.bc_buy_offset_range;
            const bcBuyMinEl = document.getElementById('bc-buy-min');
            const bcBuyMaxEl = document.getElementById('bc-buy-max');
            const bcBuyStepEl = document.getElementById('bc-buy-step');
            if (bcBuyMinEl && min != null) bcBuyMinEl.value = min;
            if (bcBuyMaxEl && max != null) bcBuyMaxEl.value = max;
            if (bcBuyStepEl && step != null) bcBuyStepEl.value = step;
        }

        if (params.bc_sell_offset_range) {
            const [min, max, step] = params.bc_sell_offset_range;
            const bcSellMinEl = document.getElementById('bc-sell-min');
            const bcSellMaxEl = document.getElementById('bc-sell-max');
            const bcSellStepEl = document.getElementById('bc-sell-step');
            if (bcSellMinEl && min != null) bcSellMinEl.value = min;
            if (bcSellMaxEl && max != null) bcSellMaxEl.value = max;
            if (bcSellStepEl && step != null) bcSellStepEl.value = step;
        }
    }
    
    updateModeVisibility();
}


export function updateModeVisibility() {
    const mode = document.getElementById('mode').value;
    const rsiSection = document.getElementById('rsi-params-section');
    const bcSection = document.getElementById('bc-params-section');
    if (mode === 'rsi') {
        rsiSection?.classList.remove('hidden');
        bcSection?.classList.add('hidden');
    } else {
        rsiSection?.classList.add('hidden');
        bcSection?.classList.remove('hidden');
    }
}

export function setupToggles() {
    document.getElementById('bounce-enable')?.addEventListener('change', function() {
        document.getElementById('bounce-inputs')?.classList.toggle('hidden', !this.checked);
    });

    document.getElementById('bear-enable')?.addEventListener('change', function() {
        const el = document.getElementById('bear-inputs');
        if (!el) return;
        if (this.checked) {
            el.classList.remove('hidden');
            el.style.display = 'grid';
        } else {
            el.classList.add('hidden');
            el.style.display = '';
        }
    });

    document.getElementById('mode')?.addEventListener('change', updateModeVisibility);
}

export async function prefillFromCurrentConfig() {
    try {
        const data = await getBotConfig();
        if (data.status === 'error' || !data.data) return;
        const cfg = data.data;

        document.getElementById('historical-days').value = '7';

        const isBC = Array.isArray(cfg.active_modes) && cfg.active_modes.includes('BC');
        document.getElementById('mode').value = isBC ? 'bc' : 'rsi';

        if (cfg.trade_amount_usd != null) {
            document.getElementById('trade-amount').value = cfg.trade_amount_usd;
            document.getElementById('initial-balance').value = Math.max(1000, cfg.trade_amount_usd * 10);
        }

        if (!isBC) {
            const os = cfg.rsi_oversold;
            const ob = cfg.rsi_overbought;
            if (os != null) {
                document.getElementById('rsi-os-min').value = os;
                document.getElementById('rsi-os-max').value = os;
                document.getElementById('rsi-os-step').value = 1;
            }
            if (ob != null) {
                document.getElementById('rsi-ob-min').value = ob;
                document.getElementById('rsi-ob-max').value = ob;
                document.getElementById('rsi-ob-step').value = 1;
                document.getElementById('rsi-ob-disable').checked = false;
            } else {
                document.getElementById('rsi-ob-disable').checked = true;
            }

            const filters = cfg.active_filters || [];
            const bounceEnabled = filters.includes('BOUNCE');
            const bearEnabled   = filters.includes('BEAR');
            document.getElementById('bounce-enable').checked = bounceEnabled;
            document.getElementById('bear-enable').checked   = bearEnabled;
            document.getElementById('bounce-inputs')?.classList.toggle('hidden', !bounceEnabled);
            const bearInputs = document.getElementById('bear-inputs');
            if (bearInputs) {
                bearInputs.classList.toggle('hidden', !bearEnabled);
                bearInputs.style.display = bearEnabled ? 'grid' : '';
            }

            if (cfg.price_bounce_ticks != null)
                document.getElementById('price-bounce-ticks').value = cfg.price_bounce_ticks;
            if (cfg.bear_trend_candles != null)
                document.getElementById('bear-candles').value = cfg.bear_trend_candles;
            if (cfg.bear_trend_pct != null)
                document.getElementById('bear-pct').value = cfg.bear_trend_pct;
        }

        const sl = cfg.stop_loss_pct;
        if (sl != null) {
            document.getElementById('sl-min').value = sl;
            document.getElementById('sl-max').value = sl;
            document.getElementById('sl-step').value = 0.1;
        }

        const tp = cfg.take_profit_pct;
        if (tp != null && tp > 0) {
            document.getElementById('tp-min').value = tp;
            document.getElementById('tp-max').value = tp;
            document.getElementById('tp-step').value = 0.1;
            document.getElementById('tp-disable').checked = false;
        } else {
            document.getElementById('tp-disable').checked = true;
        }

        const ts = cfg.trailing_stop_pct;
        if (ts != null && ts > 0) {
            document.getElementById('ts-min').value = ts;
            document.getElementById('ts-max').value = ts;
            document.getElementById('ts-step').value = 0.1;
            document.getElementById('ts-disable').checked = false;
        } else {
            document.getElementById('ts-disable').checked = true;
        }

    } catch (e) {
        console.warn('Could not prefill simulator from config:', e);
    }
}
