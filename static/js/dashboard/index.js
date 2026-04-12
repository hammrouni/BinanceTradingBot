/**
 * index.js — Main entry point for the BinanceTradingBot dashboard.
 * 
 * Orchestrates initialization, state synchronization, and global event delegation.
 */

import { state, updateState, resetUptime } from './state.js';
import {
    updatePrice, updateRsi, updateBotStatus,
    showErrorBanner, hideErrorBanner,
    startUptimeTicker, updateWallet,
    fmtNum, updateWhatBotWillDo,
    bindClearErrors
} from './ui_manager.js';
import { connectWebSocket } from './websocket.js';
import { setupConfigForm, fillConfigForm } from './config_manager.js';

// ─── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    console.log('--- Initializing Dashboard (ES Modules) ---');
    
    // 1. Setup UI logic
    setupConfigForm();
    setupButtonHandlers();
    
    // 2. Fetch initial data
    try {
        const config = await window.getConfig();
        updateState('currentConfig', config);
        fillConfigForm(config);

        // Apply RSI threshold lines from loaded config
        if (typeof window.updateChartThresholds === 'function') {
            window.updateChartThresholds(
                config.rsi_oversold  ?? 30,
                config.rsi_overbought ?? 70
            );
        }

        // Load RSI threshold history from the server so the chart shows
        // historical step changes instead of a flat current-value line.
        try {
            const thresholdHistory = await window.getRsiHistory();
            if (thresholdHistory && typeof window.setRsiThresholdHistory === 'function') {
                window.setRsiThresholdHistory(thresholdHistory);
            }
        } catch (e) {
            console.warn('Could not load RSI threshold history:', e);
        }

        // Draw BC price lines on the chart from the loaded config
        if (typeof window.updateChartBcPrice === 'function') {
            const buy = config.bc_buy_price || config.min_bc_price;
            window.updateChartBcPrice(buy > 0 ? buy : null);
        }
        if (typeof window.updateChartBcSellPrice === 'function') {
            window.updateChartBcSellPrice(config.bc_sell_price > 0 ? config.bc_sell_price : null);
        }

        // Sync the chart mode from loaded config
        const active_modes = config.active_modes || ['RSI'];
        let loadedMode = 'RSI';
        if (active_modes.includes('BC')) loadedMode = 'BC';
        else if (active_modes.includes('RSI_ULTRA')) loadedMode = 'RSI_ULTRA';
        if (typeof window.updateChartModeVisibility === 'function') {
            window.updateChartModeVisibility(loadedMode);
        }
        
        const status = await window.getStatus();
        if (status) {
            updateBotStatus(status.bot_state, status.balances);
            updateOpenPosition(status.open_position || null);
            
            if (status.bot_state === 'RUNNING' && status.uptime_seconds > 0) {
                const startedMs = Date.now() - status.uptime_seconds * 1000;
                startUptimeTicker(new Date(startedMs).toISOString());
            }
        }
    } catch (e) {
        console.error('Initialization error:', e);
        showErrorBanner('Bot is starting — please wait.');
    }

    // 3. Connect WebSocket
    connectWebSocket();

    // 4. Load initial trade history
    if (typeof window.loadTradeHistory === 'function') {
        window.loadTradeHistory();
    }
});

// ─── Global Position Update ──────────────────────────────────────────────────

/** Shared function to sync Open Position across modules and chart. */
export function updateOpenPosition(pos) {
    updateState('openPosition', pos);
    const card = document.getElementById('open-position-card');
    const content = document.getElementById('open-position-content');
    const headerPnlPill = document.getElementById('header-active-pnl-pill');

    if (!pos) {
        card?.classList.add('hidden');
        headerPnlPill?.classList.add('hidden');
        if (typeof window.clearOpenPositionFromChart === 'function') {
            window.clearOpenPositionFromChart();
        }
        const btnNo = document.getElementById('btn-manual-trade');
        if (btnNo) {
            btnNo.innerHTML = '<span class="control-icon">&#x1F4B5;</span> Manual Buy';
            btnNo.className = 'btn-manual-buy';
            btnNo.disabled = false;
        }
        updateWhatBotWillDo(state.botState || 'STOPPED');
        return;
    }

    card?.classList.remove('hidden');
    headerPnlPill?.classList.remove('hidden');
    
    if (content) {
        const pnl = (state.prevPrice - pos.entry_price) * pos.quantity;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const sign = pnl >= 0 ? '+' : '';

        content.innerHTML = `
            <div class="pos-grid">
                <div class="pos-item"><label>Entry Price</label><span class="pos-val">$${fmtNum(pos.entry_price, 2)}</span></div>
                <div class="pos-item"><label>Current Price</label><span class="pos-val" id="pos-current-price">$${fmtNum(state.prevPrice, 2)}</span></div>
                <div class="pos-item"><label>Quantity</label><span class="pos-val">${pos.quantity.toFixed(6)} ${pos.pair.replace('USDT', '')}</span></div>
                <div class="pos-item"><label>Unrealised PnL</label><span class="pos-val ${pnlClass}" id="pos-pnl">${sign}$${fmtNum(pnl, 2)}</span></div>
                <div class="pos-item"><label>Stop-Loss</label><span class="pos-val sl-price">${pos.stop_loss_price ? '$' + fmtNum(pos.stop_loss_price, 2) : 'None'}</span></div>
                <div class="pos-item"><label>Take-Profit</label><span class="pos-val tp-price">${pos.take_profit_price ? '$' + fmtNum(pos.take_profit_price, 2) : 'None'}</span></div>
            </div>
            <div class="pos-actions">
                <button id="btn-manual-sell" class="btn-manual-sell">Manual SELL</button>
            </div>
        `;
        
        // Setup the specific manual sell button for this card
        document.getElementById('btn-manual-sell')?.addEventListener('click', onManualTradeSell);
    }

    if (typeof window.updateChartWithPosition === 'function') {
        window.updateChartWithPosition(pos);
    }

    // Update manual trade button label based on position state
    const btn = document.getElementById('btn-manual-trade');
    if (btn) {
        if (pos) {
            btn.innerHTML = '<span class="control-icon">&#x1F4B8;</span> Manual Sell';
            btn.className = 'btn-manual-sell';
        } else {
            btn.innerHTML = '<span class="control-icon">&#x1F4B5;</span> Manual Buy';
            btn.className = 'btn-manual-buy';
        }
        btn.disabled = false;
    }

    // Refresh "What Bot Will Do" to reflect position state
    updateWhatBotWillDo(state.botState || 'RUNNING');
}

// Ensure updateOpenPosition is available globally so websocket.js can find it
window.updateOpenPosition = updateOpenPosition;

// Expose updateWhatBotWillDo globally so config_manager can refresh it on save
window.updateWhatBotWillDo = updateWhatBotWillDo;

// Expose state globally so non-module scripts (chart.js) can read/write it
window.state = state;

// Expose autoSaveConfig globally so chart.js drag handlers can save after drag
window.autoSaveConfig = async function autoSaveConfig() {
    const cfg = state.currentConfig;
    if (!cfg) return;
    try {
        const res = await window.updateConfig(cfg);
        if (res.ok) {
            const body = await res.json();
            updateState('currentConfig', body.data ?? cfg);
            const statusEl = document.getElementById('config-status');
            if (statusEl) {
                statusEl.textContent = '✓ Saved';
                statusEl.className = 'status-success';
                setTimeout(() => { if (statusEl.textContent === '✓ Saved') statusEl.textContent = ''; }, 2000);
            }
        }
    } catch (e) {
        console.error('Auto-save failed:', e);
    }
};

// ─── Event Handlers ──────────────────────────────────────────────────────────

function setupButtonHandlers() {
    const click = (id, fn) => document.getElementById(id)?.addEventListener('click', fn);
    
    click('btn-start',  () => executeCommand(window.startBot));
    click('btn-pause',  () => executeCommand(window.pauseBot));
    click('btn-resume', () => executeCommand(window.resumeBot));
    click('btn-stop',   () => executeCommand(window.stopBot));
    
    document.getElementById('btn-manual-trade')?.addEventListener('click', () => {
        if (state.openPosition) onManualTradeSell();
        else onManualTradeBuy();
    });
    click('btn-refresh-prod', () => window.loadTradeHistory());
    click('btn-refresh-test', () => window.loadTradeHistory());
    click('btn-dismiss-error', hideErrorBanner);
    click('btn-ai-advisor', onAskAiAdvisor);
    click('btn-ai-close', () => {
        document.getElementById('ai-advisor-card')?.classList.add('hidden');
    });
    bindClearErrors();
}

// ─── AI Advisor ──────────────────────────────────────────────────────────────

const AGENT_URL = '/api/v1/agent/trading/analyze';

async function onAskAiAdvisor() {
    const card    = document.getElementById('ai-advisor-card');
    const loading = document.getElementById('ai-loading');
    const result  = document.getElementById('ai-result');

    card?.classList.remove('hidden');
    loading?.classList.remove('hidden');
    result?.classList.add('hidden');

    const cfg = state.currentConfig ?? {};
    const modes = cfg.active_modes ?? ['RSI'];
    const activeMode = modes.includes('BC') ? 'BC' : (modes.includes('RSI_ULTRA') ? 'RSI_ULTRA' : 'RSI');

    const payload = {
        symbol:   cfg.trading_pair  ?? 'BTCUSDT',
        rsi:      window.getLatestRsi?.()   ?? null,
        rsi_ultra_raw:    state.latestRsiUltraRaw    ?? null,
        rsi_ultra_signal: state.latestRsiUltraSignal ?? null,
        price:    window.getLatestPrice?.() ?? null,
        candles:  window.getRecentCandles?.(60) ?? [],
        position: state.openPosition ? {
            side:        'LONG',
            entry_price: state.openPosition.entry_price,
            quantity:    state.openPosition.quantity,
            pnl_pct:     state.openPosition.pnl_pct ?? 0,
        } : null,
        config: {
            mode:          activeMode,
            rsi_buy:       cfg.rsi_oversold   ?? 30,
            rsi_sell:      cfg.rsi_overbought ?? 70,
            tp_pct:        cfg.take_profit_pct ?? 1.5,
            sl_pct:        cfg.stop_loss_pct  ?? 1.0,
            bc_buy_price:  cfg.bc_buy_price   ?? null,
            bc_sell_price: cfg.bc_sell_price  ?? null,
            rsi_ultra_period: cfg.rsi_ultra_period ?? 14,
            rsi_ultra_signal_period: cfg.rsi_ultra_signal_period ?? 9,
            rsi_ultra_zone_mid: cfg.rsi_ultra_zone_mid ?? 50,
        },
        trade_history: (state.loadedProdTrades ?? []).slice(0, 15).map(t => ({
            direction:   t.direction,
            entry_price: t.entry_price,
            pnl_usd:     t.pnl_usd ?? null,
            reason:      t.reason  ?? null,
            executed_at: t.executed_at,
        })),
    };

    try {
        const resp = await fetch(AGENT_URL, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload),
        });

        if (!resp.ok) throw new Error(`Agent service HTTP ${resp.status}`);
        const data = await resp.json();

        if (data.error) throw new Error(data.error);

        renderAiResult(data);
    } catch (e) {
        renderAiError(e.message);
    } finally {
        loading?.classList.add('hidden');
        result?.classList.remove('hidden');
    }
}

function fmtPrice(p) {
    return p ? '$' + Number(p).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
}

function renderAiResult(data) {
    const result = document.getElementById('ai-result');
    if (!result) return;

    const signalClass = { BUY: 'ai-signal-buy', SELL: 'ai-signal-sell', HOLD: 'ai-signal-hold' }[data.signal] ?? 'ai-signal-hold';
    const confBar     = `<div class="ai-conf-bar"><div class="ai-conf-fill" style="width:${data.confidence}%"></div></div>`;

    const risks = (data.risk_notes ?? []).length
        ? `<ul class="ai-risks">${data.risk_notes.map(r => `<li>${r}</li>`).join('')}</ul>`
        : '<p class="ai-no-risks">No significant risks flagged.</p>';

    // Config advice section
    const cfgAdvice = data.config_advice ?? {};
    let cfgHtml = '';
    if (cfgAdvice.should_change && (cfgAdvice.changes ?? []).length) {
        const rows = cfgAdvice.changes.map(c => `
            <div class="ai-cfg-change">
                <span class="ai-cfg-field">${c.field}</span>
                <span class="ai-cfg-arrow">${c.current} → <strong>${c.suggested}</strong></span>
                <span class="ai-cfg-reason">${c.reason}</span>
            </div>`).join('');
        cfgHtml = `
            <div class="ai-section ai-cfg-section">
                <strong class="ai-section-title">⚙ Config Changes Recommended</strong>
                ${rows}
            </div>`;
    } else {
        cfgHtml = `<div class="ai-section"><p class="ai-no-risks">✓ Config looks well-calibrated for current conditions.</p></div>`;
    }

    // Action advice
    const actionHtml = data.action_advice
        ? `<div class="ai-action-box"><span class="ai-action-icon">→</span> ${data.action_advice}</div>`
        : '';

    result.innerHTML = `
        <div class="ai-signal-row">
            <span class="ai-signal-badge ${signalClass}">${data.signal}</span>
            <span class="ai-confidence-label">Confidence: <strong>${data.confidence}%</strong></span>
        </div>
        ${confBar}
        ${actionHtml}
        <p class="ai-reasoning">${data.reasoning}</p>
        <div class="ai-levels">
            <div class="ai-level-item"><label>Suggested TP</label><span class="ai-tp">${fmtPrice(data.suggested_tp)}</span></div>
            <div class="ai-level-item"><label>Suggested SL</label><span class="ai-sl">${fmtPrice(data.suggested_sl)}</span></div>
        </div>
        <div class="ai-section ai-risk-section">
            <strong class="ai-section-title">⚠ Risk Notes</strong>
            ${risks}
        </div>
        ${cfgHtml}
        <p class="ai-footer">Powered by ${data.agent ?? 'AI'} · ${new Date().toLocaleTimeString()}</p>
    `;
}

function renderAiError(msg) {
    const result = document.getElementById('ai-result');
    if (!result) return;
    result.innerHTML = `<p class="ai-error">⚠ ${msg}</p>`;
}

async function executeCommand(cmdFn) {
    try {
        const res = await cmdFn();
        if (!res.ok) {
            const body = await res.json();
            showErrorBanner(body.error || 'Operation failed');
        } else {
            hideErrorBanner();
        }
    } catch (e) {
        showErrorBanner('Network error: ' + e.message);
    }
}

async function onManualTradeBuy() {
    if (confirm('Execute a MANUAL market BUY for ' + (state.currentConfig.trading_pair || 'selected pair') + '?')) {
        await executeCommand(window.manualBuy);
        // Success handled by WS 'trade_executed'
    }
}

async function onManualTradeSell() {
    if (confirm('Execute a MANUAL market SELL for all ' + state.openPosition.pair + '?')) {
        await executeCommand(window.manualSell);
        // Success handled by WS 'trade_executed'
    }
}

// ─── Global Tooltip (JS-positioned to avoid viewport clipping) ───────────────

(function setupGlobalTooltip() {
    const MARGIN = 8; // px from viewport edge
    const tip = document.getElementById('global-tooltip');
    const arrow = document.getElementById('global-tooltip-arrow');
    if (!tip || !arrow) return;

    function showTooltip(icon) {
        const text = icon.getAttribute('data-tooltip');
        if (!text) return;
        tip.textContent = text;
        tip.classList.add('visible');
        arrow.classList.add('visible');
        positionTooltip(icon);
    }

    function hideTooltip() {
        tip.classList.remove('visible');
        arrow.classList.remove('visible');
    }

    function positionTooltip(icon) {
        const r = icon.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const tipW = tip.offsetWidth;
        const tipH = tip.offsetHeight;

        // Ideal: centered above the icon
        let left = r.left + r.width / 2 - tipW / 2;
        let top = r.top - tipH - 10; // 10px gap for arrow

        // Clamp horizontally
        left = Math.max(MARGIN, Math.min(left, vw - tipW - MARGIN));

        // If not enough room above, flip below
        let arrowBelow = false;
        if (top < MARGIN) {
            top = r.bottom + 10;
            arrowBelow = true;
        }

        tip.style.left = left + 'px';
        tip.style.top = top + 'px';

        // Position arrow: centered on icon, just below the tooltip box or above
        const arrowLeft = Math.max(MARGIN, Math.min(r.left + r.width / 2 - 5, vw - 15));
        if (arrowBelow) {
            // Arrow points up (tooltip is below icon)
            arrow.style.borderTopColor = 'transparent';
            arrow.style.borderBottomColor = '#1e293b';
            arrow.style.left = arrowLeft + 'px';
            arrow.style.top = (r.bottom + 1) + 'px';
        } else {
            // Arrow points down (tooltip is above icon)
            arrow.style.borderTopColor = '#1e293b';
            arrow.style.borderBottomColor = 'transparent';
            arrow.style.left = arrowLeft + 'px';
            arrow.style.top = (top + tipH) + 'px';
        }
    }

    // Event delegation on document for all .info-icon elements
    document.addEventListener('mouseover', e => {
        const icon = e.target.closest('.info-icon');
        if (icon) showTooltip(icon);
    });
    document.addEventListener('mouseout', e => {
        const icon = e.target.closest('.info-icon');
        if (icon) hideTooltip();
    });
    document.addEventListener('scroll', hideTooltip, true);
})();
