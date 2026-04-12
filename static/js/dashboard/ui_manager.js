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

/** Aggregate a single price tick into the current 1-min candle.
 *  Accepts optional open/high/low from the live market_update payload
 *  so candles have real bodies instead of flat invisible lines.
 */
export function tickToCandle(price, nowMs, open, high, low) {
    const CANDLE_MS = 60 * 1000;
    const periodStart = Math.floor(nowMs / CANDLE_MS) * CANDLE_MS;

    // Use the tick's own OHLC if provided, otherwise fall back to close price
    const tickOpen  = open  ?? price;
    const tickHigh  = high  ?? price;
    const tickLow   = low   ?? price;

    if (state.activeCandleTs !== periodStart) {
        // New minute → start fresh candle
        updateState('activeCandleTs', periodStart);
        const candle = { x: periodStart, o: tickOpen, h: tickHigh, l: tickLow, c: price };
        updateState('activeCandle', candle);
    } else {
        // Same minute → update running OHLC
        const candle = state.activeCandle;
        candle.h = Math.max(candle.h, tickHigh);
        candle.l = Math.min(candle.l, tickLow);
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
    
    // Persist bot state for other callers
    updateState('botState', status);

    // Update the "What Bot Will Do" section
    updateWhatBotWillDo(status);
}

/** 
 * Build a human-readable summary of the current bot strategy and its 
 * triggers/targets based on the active config and current position. 
 */
export function updateWhatBotWillDo(statusState, configOverride = null) {
    const el = document.getElementById('bot-preview');
    if (!el) return;

    if (statusState === 'STOPPED') {
        el.innerHTML = '<p class="status-msg paused">Bot is stopped. Click Start to begin trading.</p>';
        return;
    }

    const config = configOverride || state.currentConfig;
    if (!config) return;

    const latestRsi   = typeof window.getLatestRsi   === 'function' ? window.getLatestRsi()   : null;
    const latestPrice = typeof window.getLatestPrice === 'function' ? window.getLatestPrice() : state.prevPrice;

    // ── Position is OPEN → show sell / exit conditions only ──────────────────
    if (state.openPosition) {
        let html = '';
        const pos = state.openPosition;
        const entry = pos.entry_price;

        const tpPrice = pos.take_profit_price ?? 
            (config.take_profit_pct && entry ? entry * (1 + config.take_profit_pct / 100) : null);
        if (tpPrice) {
            const reached = latestPrice && latestPrice >= tpPrice;
            html += `<div class="preview-item">
                <span class="preview-label">SELL at TP:</span>
                <span class="preview-value ${reached ? 'sell' : 'active'}">$${fmtNum(tpPrice, 2)}</span>
                <span class="preview-condition">${reached ? '✅ SELLING' : '⏳ Waiting'}</span>
            </div>`;
        }

        const slPrice = pos.stop_loss_price ??
            (config.stop_loss_pct && entry ? entry * (1 - config.stop_loss_pct / 100) : null);
        if (slPrice) {
            const hit = latestPrice && latestPrice <= slPrice;
            html += `<div class="preview-item">
                <span class="preview-label">SELL at SL:</span>
                <span class="preview-value ${hit ? 'sell' : 'neutral'}">$${fmtNum(slPrice, 2)}</span>
                <span class="preview-condition">${hit ? '⚠️ TRIGGERED' : '🛡 Active'}</span>
            </div>`;
        }

        const ob = config.rsi_overbought;
        if (ob && latestRsi !== null && !config.take_profit_pct) {
            const willSell = latestRsi > ob;
            html += `<div class="preview-item">
                <span class="preview-label">SELL if RSI:</span>
                <span class="preview-value ${willSell ? 'sell' : 'neutral'}">RSI ${latestRsi.toFixed(1)} &gt; ${ob}</span>
                <span class="preview-condition">${willSell ? '✅ WILL SELL' : '❌ No signal'}</span>
            </div>`;
        }

        if (!html) html = '<div class="preview-item"><span class="preview-value neutral">Holding position — waiting for exit signal</span></div>';
        el.innerHTML = html;
        return;
    }

    // ── No position → show buy conditions ────────────────────────────────────
    let html = '';
    const modes = config.active_modes || ['RSI'];
    const bcModeActive = modes.includes('BC') && (config.bc_buy_price || config.min_bc_price) > 0;

    if (bcModeActive) {
        const bcBuyTarget = config.bc_buy_price || config.min_bc_price;
        const willBcBuy = latestPrice && latestPrice < bcBuyTarget;
        html += `<div class="preview-item">
            <span class="preview-label">BC BUY if:</span>
            <span class="preview-value ${willBcBuy ? 'buy' : 'neutral'}">Price &lt; $${fmtNum(bcBuyTarget, 2)}</span>
            <span class="preview-condition">${willBcBuy ? '✅ SIGNAL' : '❌ No signal'}</span>
        </div>`;
        if (config.bc_sell_price) {
            html += `<div class="preview-item">
                <span class="preview-label">BC SELL at:</span>
                <span class="preview-value neutral">$${fmtNum(config.bc_sell_price, 2)}</span>
                <span class="preview-condition">⏳ Watching</span>
            </div>`;
        }
    }

    const os = config.rsi_oversold;
    if (modes.includes('RSI') && os && latestRsi !== null) {
        const willBuy = latestRsi < os;
        html += `<div class="preview-item">
            <span class="preview-label">BUY if RSI:</span>
            <span class="preview-value ${willBuy ? 'buy' : 'neutral'}">RSI ${latestRsi.toFixed(1)} &lt; ${os}</span>
            <span class="preview-condition">${willBuy ? '✅ WILL BUY' : '❌ No signal'}</span>
        </div>`;
    }

    if (config.take_profit_pct > 0) {
        html += `<div class="preview-item">
            <span class="preview-label">TAKE-PROFIT:</span>
            <span class="preview-value active">${config.take_profit_pct}%</span>
            <span class="preview-condition">⏸ Waiting</span>
        </div>`;
    }

    if (config.stop_loss_pct > 0) {
        html += `<div class="preview-item">
            <span class="preview-label">STOP-LOSS:</span>
            <span class="preview-value active">${config.stop_loss_pct}%</span>
            <span class="preview-condition">⏸ Waiting</span>
        </div>`;
    }

    if (config.trailing_stop_pct > 0) {
        html += `<div class="preview-item">
            <span class="preview-label">Trail-Stop:</span>
            <span class="preview-value active">${config.trailing_stop_pct}%</span>
            <span class="preview-condition">⏸ Waiting</span>
        </div>`;
    }

    if (config.price_bounce_ticks > 0) {
        html += `<div class="preview-item">
            <span class="preview-label">Bounce-Buy:</span>
            <span class="preview-value neutral">${config.price_bounce_ticks} ticks</span>
            <span class="preview-condition">🛡️ Guarding</span>
        </div>`;
    }

    if (config.bear_trend_candles && config.bear_trend_pct) {
        html += `<div class="preview-item">
            <span class="preview-label">Bear-Filter:</span>
            <span class="preview-value neutral">-${config.bear_trend_pct}% in ${config.bear_trend_candles}</span>
            <span class="preview-condition">🛡️ VIP Guard</span>
        </div>`;
    }

    if (!html) html = '<div class="preview-item"><span class="preview-value neutral">Configure thresholds above</span></div>';
    
    // Profitability Fee Warning (0.1% Buy + 0.1% Sell)
    const FEE = 0.2;
    if (config.take_profit_pct > 0 && config.stop_loss_pct > 0 && config.take_profit_pct < (config.stop_loss_pct + FEE)) {
        html += `<div class="config-warning" style="margin-top:0.5rem; font-size:0.8rem;">
            Take Profit (${config.take_profit_pct.toFixed(1)}%) ≤ Stop-Loss (${config.stop_loss_pct.toFixed(1)}%) + Fees (${FEE}%). Trade will be a net loss.
        </div>`;
    }
    
    el.innerHTML = html;
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
    if (r.indexOf('-2014') >= 0 || r.indexOf('api-key') >= 0 || r.indexOf('invalid api') >= 0)
        return 'Invalid API credentials — please check your .env file.';
    if (r.indexOf('-1021') >= 0 || r.indexOf('timestamp') >= 0)
        return 'Clock sync error — your system time may be off.';
    if (r.indexOf('connection') >= 0 || r.indexOf('network') >= 0)
        return 'Connection to Binance failed — check your network.';
    if (r.indexOf('-1100') >= 0 || r.indexOf('illegal characters') >= 0) {
        if (r.indexOf('quantity') >= 0) return 'Order quantity precision error — fixed automatically.';
        return 'Invalid format — check trading pair (e.g. BTCUSDT) or quantity.';
    }
    return raw;
}

const MAX_ERROR_ENTRIES = 20;

export function addErrorEntry(payload, timestamp) {
    const section = document.getElementById('error-log-section');
    const list    = document.getElementById('error-list');
    if (!list || !section) return;

    section.classList.remove('hidden');

    const entry = document.createElement('div');
    entry.className = 'error-entry';
    const localTime = timestamp ? new Date(timestamp).toLocaleTimeString() : '—';
    entry.innerHTML = `
        <div class="error-entry-header">
            <span class="error-time">${localTime}</span>
            <span class="error-code">${payload.code || 'ERROR'}</span>
        </div>
        <div class="error-msg">${translateError(payload.message || '')}</div>
    `;
    list.insertBefore(entry, list.firstChild);

    const entries = list.querySelectorAll('.error-entry');
    if (entries.length > MAX_ERROR_ENTRIES) entries[entries.length - 1].remove();
}

export function bindClearErrors() {
    document.getElementById('btn-clear-errors')?.addEventListener('click', () => {
        const list    = document.getElementById('error-list');
        const section = document.getElementById('error-log-section');
        if (list) list.innerHTML = '';
        section?.classList.add('hidden');
    });
}

export function applyEnvironmentVisibility(env) {
    const isLive = (env === 'live');
    document.getElementById('test-pnl-pill')?.classList.toggle('hidden', isLive);
    document.getElementById('trading-wallet-section')?.classList.toggle('hidden', isLive);
    document.getElementById('wallet-divider-vertical')?.classList.toggle('hidden', isLive);
    document.getElementById('test-trade-history')?.classList.toggle('hidden', isLive);
    document.getElementById('trade-history')?.classList.toggle('hidden', !isLive);
    document.getElementById('prod-wallet-section')?.classList.toggle('hidden', !isLive);

    // Sync chart marker visibility
    if (typeof window.setMarkerVisibility === 'function') {
        window.setMarkerVisibility(env);
    }
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

// ─── Trade history ────────────────────────────────────────────────────────────

const _REASON_LABEL = {
    'buy_signal':  'RSI Oversold',
    'stop_loss':   'Stop Loss',
    'take_profit': 'Take Profit',
    'signal':      'RSI Overbought',
    'manual':      'Manual',
    'bc_signal':   'BC Price',
};
const _REASON_CLASS = {
    'buy_signal':  'reason-buy',
    'stop_loss':   'reason-stoploss',
    'take_profit': 'reason-takeprofit',
    'signal':      'reason-sell',
    'manual':      'reason-manual',
    'bc_signal':   'reason-bc',
};

function _formatTradeTime(date) {
    const diffMins = Math.floor((Date.now() - date.getTime()) / 60000);
    if (diffMins < 1)    return 'Just now';
    if (diffMins < 60)   return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function _renderTradeRow(trade) {
    const tr = document.createElement('tr');
    tr.className = trade.direction === 'buy' ? 'trade-buy' : 'trade-sell';

    const date  = trade.executed_at ? new Date(trade.executed_at) : null;
    const ago   = date ? _formatTradeTime(date) : '—';
    const exact = trade.executed_at
        ? (window.luxon
            ? window.luxon.DateTime.fromISO(trade.executed_at).toFormat('MMM dd, HH:mm:ss')
            : new Date(trade.executed_at).toLocaleString())
        : '—';

    const price = trade.entry_price ?? trade.price;
    const side  = trade.direction === 'buy'
        ? '<span class="side-buy">BUY</span>'
        : '<span class="side-sell">SELL</span>';

    const fee = trade.fee_usd ?? 0;
    const feeCell = fee > 0
        ? `<td class="fee-cell">-$${fee.toFixed(4)}</td>`
        : `<td class="fee-cell fee-unknown">—</td>`;

    const reasonKey  = trade.reason ?? (trade.direction === 'buy' ? 'buy_signal' : null);
    const reasonText = reasonKey ? (_REASON_LABEL[reasonKey] ?? reasonKey) : '—';
    const reasonCls  = reasonKey ? (_REASON_CLASS[reasonKey] ?? '') : '';
    const reasonCell = `<td class="reason-cell ${reasonCls}">${reasonText}</td>`;

    let pnlCell;
    if (trade.direction === 'buy') {
        pnlCell = '<td class="pnl-neutral">—</td>';
    } else if (trade.pnl_usd == null) {
        pnlCell = '<td class="pnl-neutral">—</td>';
    } else {
        const cls  = trade.pnl_usd >= 0 ? 'pnl-positive' : 'pnl-negative';
        const sign = trade.pnl_usd >= 0 ? '+' : '';
        const feeNote = fee > 0 ? ' title="Net (fees deducted)"' : ' title="Fees not tracked"';
        pnlCell = `<td class="${cls}"${feeNote}>${sign}$${trade.pnl_usd.toFixed(4)}</td>`;
    }

    tr.innerHTML = `
        <td title="${trade.executed_at || ''}">${ago}</td>
        <td class="exact-time-cell">${exact}</td>
        <td>${side}</td>
        ${reasonCell}
        <td>$${trade.amount_usd?.toFixed(2) || '—'}</td>
        <td>$${price?.toFixed(2) || '—'}</td>
        <td>${trade.quantity?.toFixed(6) || '—'}</td>
        ${feeCell}
        ${pnlCell}
    `;
    return tr;
}

function _renderTradeHistoryTable(trades, isTest = false) {
    const bodyId    = isTest ? 'test-trades-body' : 'trades-body';
    const emptyId   = isTest ? 'test-trades-empty' : 'trades-empty';
    const summaryId = isTest ? 'test-trade-summary' : 'trade-summary';
    const countId   = isTest ? 'test-summary-trades' : 'summary-trades';
    const pnlId     = isTest ? 'test-summary-pnl' : 'summary-pnl';
    const feesId    = isTest ? 'test-summary-fees' : 'summary-fees';

    const tbody    = document.getElementById(bodyId);
    const emptyMsg = document.getElementById(emptyId);
    if (!tbody) return;

    tbody.innerHTML = '';
    if (trades.length === 0) {
        if (emptyMsg) emptyMsg.style.display = 'block';
        document.getElementById(summaryId)?.classList.add('hidden');
        return;
    }

    if (emptyMsg) emptyMsg.style.display = 'none';

    let totalPnl = 0;
    let totalFees = 0;
    trades.forEach(t => {
        tbody.appendChild(_renderTradeRow(t));
        if (t.direction === 'sell' && t.pnl_usd != null) totalPnl += t.pnl_usd;
        if (t.fee_usd) totalFees += t.fee_usd;
    });

    const summaryEl = document.getElementById(summaryId);
    const countEl   = document.getElementById(countId);
    const pnlEl     = document.getElementById(pnlId);
    const feesEl    = document.getElementById(feesId);

    if (summaryEl) summaryEl.classList.remove('hidden');
    if (countEl)   countEl.textContent = `${trades.length} trade${trades.length !== 1 ? 's' : ''}`;
    if (pnlEl) {
        const sign = totalPnl >= 0 ? '+' : '';
        const feesTracked = totalFees > 0;
        const pnlLabel = feesTracked ? 'Net P&L' : 'P&L';
        pnlEl.textContent = `${pnlLabel}: ${sign}$${totalPnl.toFixed(4)}`;
        pnlEl.className   = totalPnl > 0 ? 'pnl-positive' : totalPnl < 0 ? 'pnl-negative' : 'pnl-neutral';
        pnlEl.title       = feesTracked ? 'Net PnL — Binance fees already deducted' : 'PnL — Fees not tracked (old trades)';

        const headerId  = isTest ? 'header-test-pnl' : 'header-prod-pnl';
        const headerPnl = document.getElementById(headerId);
        if (headerPnl) {
            headerPnl.textContent = `${sign}$${totalPnl.toFixed(4)}`;
            headerPnl.className   = pnlEl.className;
            headerPnl.title       = pnlEl.title;
        }
    }
    if (feesEl) {
        if (totalFees > 0) {
            feesEl.textContent = `Fees: -$${totalFees.toFixed(4)}`;
            feesEl.className   = 'summary-fees fees-tracked';
            feesEl.title       = 'Total Binance trading fees paid (buy + sell)';
        } else {
            feesEl.textContent = 'Fees: not tracked';
            feesEl.className   = 'summary-fees fees-unknown';
            feesEl.title       = 'Fee data unavailable for these trades (recorded before fee tracking)';
        }
    }
}

export function replayTradeMarkers() {
    if (!state.rsiHistoryLoaded) return;
    if (typeof window.markSignalAtTime !== 'function') return;

    state.loadedProdTrades.forEach(t => {
        if (t.executed_at) {
            window.markSignalAtTime(
                t.executed_at, 
                t.direction, 
                t.entry_price || t.price, 
                false, 
                t.amount_usd, 
                t.reason ?? (t.direction === 'buy' ? 'buy_signal' : null)
            );
        }
    });

    state.loadedTestTrades.forEach(t => {
        if (t.executed_at) {
            window.markSignalAtTime(
                t.executed_at, 
                t.direction, 
                t.entry_price || t.price, 
                true, 
                t.amount_usd, 
                t.reason ?? (t.direction === 'buy' ? 'buy_signal' : null)
            );
        }
    });
}

/**
 * Build OHLC candle objects from RSI history points.
 */
export function buildCandlesFromHistory(points) {
    if (!points || !points.length) return [];
    const sorted = [...points]
        .filter(p => p.timestamp && p.price != null)
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    return sorted.map((p, i) => {
        const close     = p.price;
        const prevClose = i > 0 ? sorted[i - 1].price : close;
        const open      = p.open  ?? prevClose;
        const high      = p.high  ?? Math.max(open, close);
        const low       = p.low   ?? Math.min(open, close);
        return { x: new Date(p.timestamp).getTime(), o: open, h: high, l: low, c: close };
    });
}

export async function loadTradeHistory() {
    try {
        const prodResponse = await window.getTrades();
        const prodTrades = Array.isArray(prodResponse) ? prodResponse : (prodResponse?.data || []);
        updateState('loadedProdTrades', prodTrades);
        
        const prodBody = document.getElementById('trades-body');
        if (prodBody) prodBody.innerHTML = '';
        _renderTradeHistoryTable(prodTrades, false);

        const testResponse = await fetch('/api/v1/trades/test').then(r => r.json());
        const testTrades = Array.isArray(testResponse) ? testResponse : (testResponse?.data || []);
        updateState('loadedTestTrades', testTrades);
        
        const testBody = document.getElementById('test-trades-body');
        if (testBody) testBody.innerHTML = '';
        _renderTradeHistoryTable(testTrades, true);

        replayTradeMarkers();
    } catch (e) {
        console.error('Failed to load trade histories:', e);
    }
}

window.loadTradeHistory = loadTradeHistory;
window.replayTradeMarkers = replayTradeMarkers;
