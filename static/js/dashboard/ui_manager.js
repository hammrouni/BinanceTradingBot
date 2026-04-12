/**
 * ui_manager.js — DOM update logic for the dashboard.
 * 
 * Handles price updates, RSI status, bot status, and wallet rendering.
 */

import { state, updateState, resetUptime } from './state.js';

// ─── Number formatting ────────────────────────────────────────────────────────

/** Format a number for display: commas + fixed decimals. */
export function fmtNum(val, decimals = 2) {
    if (val == null || val === '' || isNaN(Number(val))) return '';
    return Number(val).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/** Strip formatting from a price input value before parsing. */
export function stripFmt(str) {
    return String(str).trim().replace(/,/g, '').replace(/\s/g, '');
}

/** Aggregate a single price tick into the current 1-min candle. */
export function tickToCandle(price, nowMs) {
    const CANDLE_MS = 60 * 1000;
    const periodStart = Math.floor(nowMs / CANDLE_MS) * CANDLE_MS;
    
    if (state.activeCandleTs !== periodStart) {
        updateState('activeCandleTs', periodStart);
        const candle = { x: periodStart, o: price, h: price, l: price, c: price };
        updateState('activeCandle', candle);
    } else {
        const candle = state.activeCandle;
        candle.h = Math.max(candle.h, price);
        candle.l = Math.min(candle.l, price);
        candle.c = price;
    }
    
    if (typeof window.upsertCandle === 'function') {
        window.upsertCandle({ ...state.activeCandle });
    }
}

// ─── Price display ────────────────────────────────────────────────────────────

export function updatePrice(price) {
    const formatted = '$' + fmtNum(price, 2);
    const el = document.getElementById('current-price');
    const deltaEl = document.getElementById('price-delta');
    const headerEl = document.getElementById('header-price');

    if (el) el.textContent = formatted;
    if (headerEl) headerEl.textContent = formatted;

    if (deltaEl && state.prevPrice != null && state.prevPrice !== 0) {
        const diff = price - state.prevPrice;
        const pct = (diff / state.prevPrice) * 100;
        const arrow = diff >= 0 ? '▲' : '▼';
        deltaEl.textContent = `${arrow} ${Math.abs(pct).toFixed(2)}%`;
        deltaEl.className = 'price-delta ' + (diff >= 0 ? 'up' : 'down');
    }

    updateState('prevPrice', price);
    updateUnrealisedPnl(price);
    updateLastUpdated();
}

// ─── RSI display ─────────────────────────────────────────────────────────────

export function updateRsi(rsi, timestamp) {
    const el = document.getElementById('current-rsi');
    const zoneEl = document.getElementById('rsi-zone-label');
    const headerEl = document.getElementById('header-rsi');
    if (!el) return;

    if (rsi == null) return;

    const value = Number(rsi).toFixed(2);
    if (el) el.textContent = value;
    if (headerEl) headerEl.textContent = value;

    el.className = '';
    if (zoneEl) {
        if (rsi < 30) {
            el.classList.add('rsi-oversold');
            zoneEl.textContent = 'Oversold';
            zoneEl.className = 'rsi-zone-label oversold';
        } else if (rsi > 70) {
            el.classList.add('rsi-overbought');
            zoneEl.textContent = 'Overbought';
            zoneEl.className = 'rsi-zone-label overbought';
        } else {
            el.classList.add('rsi-neutral');
            zoneEl.textContent = 'Neutral';
            zoneEl.className = 'rsi-zone-label neutral';
        }
    }

    if (typeof window.updateRsiChart === 'function') {
        window.updateRsiChart(rsi, timestamp, state.prevPrice);
    }
}

// ─── Bot status ───────────────────────────────────────────────────────────────

export function updateBotStatus(status, balances) {
    const s = status.toLowerCase();
    const label = s.charAt(0).toUpperCase() + s.slice(1);

    const indicator = document.getElementById('status-indicator');
    const dot = document.getElementById('status-dot');
    const headerEl = document.getElementById('header-status');

    if (indicator) { indicator.textContent = label; indicator.className = 'status-' + s; }
    if (dot) dot.className = 'status-dot ' + s;
    if (headerEl) { headerEl.textContent = label; headerEl.className = 'stat-value status-' + s; }

    if (balances) updateWallet(balances);

    const btnStart = document.getElementById('btn-start');
    const btnPause = document.getElementById('btn-pause');
    const btnResume = document.getElementById('btn-resume');
    const btnStop = document.getElementById('btn-stop');

    if (btnStart) btnStart.classList.toggle('hidden', s === 'running' || s === 'paused');
    if (btnPause) btnPause.classList.toggle('hidden', s !== 'running');
    if (btnResume) btnResume.classList.toggle('hidden', s !== 'paused');
    if (btnStop) btnStop.classList.toggle('hidden', s !== 'running' && s !== 'paused');

    [btnStart, btnPause, btnResume, btnStop].forEach(b => { if (b) b.disabled = false; });

    const uptimeDiv = document.getElementById('uptime-display');
    if (s === 'running' || s === 'paused') {
        uptimeDiv?.classList.remove('hidden');
    } else {
        uptimeDiv?.classList.add('hidden');
        resetUptime();
    }
}

// ─── Wallet display ───────────────────────────────────────────────────────────

export function updateWallet(balances) {
    const prodContainer = document.getElementById('wallet-balances-prod');
    const tradingContainer = document.getElementById('wallet-balances-trading');
    const badge = document.getElementById('trade-env-badge');
    const walletSection = document.getElementById('trading-wallet-section');
    const overlay = document.getElementById('testnet-disabled-overlay');
    
    updateState('currentBalances', balances);
    
    if (!prodContainer || !tradingContainer) return;

    const env = balances?.trading_env || state.currentConfig?.trading_env || 'testnet';

    if (badge) {
        badge.textContent = env.toUpperCase();
        badge.className = 'trading-env-badge ' + env;
    }

    if (env === 'live') {
        walletSection?.classList.add('is-live');
        overlay?.classList.remove('hidden');
    } else {
        walletSection?.classList.remove('is-live');
        overlay?.classList.add('hidden');
    }

    applyEnvironmentVisibility(env);

    const _render = (container, data, nwId) => {
        const assets = data?.assets || {};
        const netWorth = data?.total_net_worth || 0;

        const nwEl = document.getElementById(nwId);
        if (nwEl) {
            nwEl.textContent = '$' + fmtNum(netWorth, 2);
        }

        if (Object.keys(assets).length === 0) {
            if (!container.querySelector('.wallet-asset-row')) {
                container.innerHTML = '<div class="wallet-empty">Refreshing...</div>';
            }
            return;
        }

        const sortedAssets = Object.entries(assets).sort((a, b) => {
            const aName = a[0];
            const bName = b[0];
            if (aName.startsWith('USDT')) return -1;
            if (bName.startsWith('USDT')) return 1;
            return aName.localeCompare(bName);
        });

        let html = '';
        for (const [asset, bal] of sortedAssets) {
            const total = bal.free + bal.locked;
            html += `
                <div class="wallet-asset-row">
                    <div class="asset-info">
                        <span class="asset-name">${asset}</span>
                        <span class="asset-total">${total.toLocaleString('en-US', { 
                            minimumFractionDigits: asset === 'USDT' ? 2 : 6, 
                            maximumFractionDigits: asset === 'USDT' ? 2 : 6 
                        })}</span>
                    </div>
                    <div class="asset-details">
                        <span class="asset-free">Available: ${bal.free.toLocaleString('en-US', { 
                            minimumFractionDigits: asset === 'USDT' ? 2 : 6, 
                            maximumFractionDigits: asset === 'USDT' ? 2 : 6 
                        })}</span>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    };

    _render(prodContainer, balances.prod, 'net-worth-prod');
    _render(tradingContainer, balances.trading, 'net-worth-trading');
}

// ─── Uptime ticker ────────────────────────────────────────────────────────────

export function startUptimeTicker(isoTimestamp) {
    if (isoTimestamp) updateState('startedAt', new Date(isoTimestamp));
    if (!state.startedAt) updateState('startedAt', new Date());
    
    if (state.uptimeInterval) clearInterval(state.uptimeInterval);
    
    const interval = setInterval(() => {
        const secs = Math.floor((Date.now() - state.startedAt.getTime()) / 1000);
        const h = Math.floor(secs / 3600);
        const m = Math.floor((secs % 3600) / 60);
        const s = secs % 60;
        const el = document.getElementById('uptime-value');
        if (el) el.textContent = h > 0 ? `${h}h ${m}m ${s}s`
            : m > 0 ? `${m}m ${s}s` : `${s}s`;
    }, 1000);
    
    updateState('uptimeInterval', interval);
}

// ─── Last updated ─────────────────────────────────────────────────────────────

function updateLastUpdated() {
    const el = document.getElementById('last-updated');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
}

// ─── Error handling ───────────────────────────────────────────────────────

export function showErrorBanner(msg) {
    const banner = document.getElementById('error-banner');
    const msgEl = document.getElementById('error-message');
    if (!banner) return;
    if (msgEl) msgEl.textContent = translateError(msg);
    banner.classList.remove('hidden');
}

export function hideErrorBanner() {
    document.getElementById('error-banner')?.classList.add('hidden');
}

export function translateError(raw) {
    if (!raw) return 'An unknown error occurred.';
    const r = raw.toLowerCase();
    if (r.includes('-2014') || r.includes('api-key') || r.includes('invalid api'))
        return 'Invalid API credentials — please check your .env file.';
    if (r.includes('-1021') || r.includes('timestamp'))
        return 'Clock sync error — your system time may be off.';
    if (r.includes('connection') || r.includes('network'))
        return 'Connection to Binance failed — check your network.';
    if (r.includes('-1100') || r.includes('illegal characters')) {
        if (r.includes('quantity')) return 'Order quantity precision error — fixed automatically.';
        return 'Invalid format — check trading pair (e.g. BTCUSDT) or quantity.';
    }
    return raw;
}

export function applyEnvironmentVisibility(env) {
    const isLive = (env === 'live');
    document.getElementById('test-pnl-pill')?.classList.toggle('hidden', isLive);
    document.getElementById('trading-wallet-section')?.classList.toggle('hidden', isLive);
    document.getElementById('wallet-divider-vertical')?.classList.toggle('hidden', isLive);
    document.getElementById('test-trade-history')?.classList.toggle('hidden', isLive);
}

function updateUnrealisedPnl(currentPrice) {
    if (!state.openPosition) return;
    const pnl = (currentPrice - (state.openPosition.entry_price || 0)) * (state.openPosition.quantity || 0);
    const priceEl = document.getElementById('pos-current-price');
    const pnlEl = document.getElementById('pos-pnl');
    if (priceEl) priceEl.textContent = `$${currentPrice.toFixed(2)}`;
    if (pnlEl) {
        const sign = pnl >= 0 ? '+' : '';
        const value = `${sign}$${pnl.toFixed(2)}`;
        const className = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        
        pnlEl.textContent = value;
        pnlEl.className = 'position-value ' + className;

        const headerPnl = document.getElementById('header-active-pnl');
        if (headerPnl) {
            headerPnl.textContent = value;
            headerPnl.className = className;
        }
    }
}
