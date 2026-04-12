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
    fmtNum
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
}

// Ensure updateOpenPosition is available globally so websocket.js can find it
window.updateOpenPosition = updateOpenPosition;

// ─── Event Handlers ──────────────────────────────────────────────────────────

function setupButtonHandlers() {
    const click = (id, fn) => document.getElementById(id)?.addEventListener('click', fn);
    
    click('btn-start',  () => executeCommand(window.startBot));
    click('btn-pause',  () => executeCommand(window.pauseBot));
    click('btn-resume', () => executeCommand(window.resumeBot));
    click('btn-stop',   () => executeCommand(window.stopBot));
    
    click('btn-manual-trade', onManualTradeBuy);
    click('btn-refresh-prod', () => window.loadTradeHistory());
    click('btn-refresh-test', () => window.loadTradeHistory());
    click('btn-dismiss-error', hideErrorBanner);
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
