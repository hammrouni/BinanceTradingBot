/**
 * websocket.js — WebSocket communication for the dashboard.
 */

import { updateState, state } from './state.js';
import { 
    updatePrice, updateRsi, updateBotStatus, 
    showErrorBanner, hideErrorBanner, startUptimeTicker,
    tickToCandle
} from './ui_manager.js';

export function setWsStatus(state) {
    const el = document.getElementById('ws-status');
    const label = el?.querySelector('.ws-label');
    if (!el) return;
    el.className = 'ws-indicator ws-' + state;
    if (label) label.textContent =
        state === 'connected' ? 'Live' :
        state === 'connecting' ? 'Connecting...' : 'Disconnected';
}

export function connectWebSocket() {
    setWsStatus('connecting');
    const ws = new WebSocket(`ws://${window.location.host}/ws/dashboard`);

    ws.onopen = () => {
        setWsStatus('connected');
        // Initial sync is handled in index.js
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            switch (msg.type) {
                case 'market_update': {
                    const { price, rsi, timestamp } = msg.payload;
                    updatePrice(price);
                    updateRsi(rsi, timestamp);
                    tickToCandle(price, timestamp ? new Date(timestamp).getTime() : Date.now());
                    break;
                }
                case 'bot_status': {
                    updateBotStatus(msg.payload.state, msg.payload.balances);
                    // Open position update handled by specialized function in ui_manager or index
                    if (window.updateOpenPosition) {
                        window.updateOpenPosition(msg.payload.open_position || null);
                    }
                    if (msg.payload.state === 'RUNNING') hideErrorBanner();
                    if (msg.payload.state === 'RUNNING' && !state.startedAt)
                        startUptimeTicker(msg.timestamp);
                    break;
                }
                case 'trade_executed': {
                    console.log('trade_executed received:', msg.payload);
                    const t = msg.payload;
                    
                    // Signal to reload history and wallet
                    if (window.loadTradeHistory) window.loadTradeHistory();
                    if (window.refreshWallet) window.refreshWallet();
                    
                    const tradeMs = t.executed_at ? new Date(t.executed_at).getTime() : Date.now();
                    const isTest = t.is_test ?? (state.currentConfig.trading_env === 'testnet');

                    if (t.direction === 'buy') {
                        if (typeof window.markBuySignal === 'function') 
                            window.markBuySignal(t.price, isTest, t.amount_usd, t.reason ?? 'buy_signal');
                    } else if (t.direction === 'sell') {
                        if (window.updateOpenPosition) window.updateOpenPosition(null);
                        if (typeof window.markSellSignal === 'function') 
                            window.markSellSignal(t.price, isTest, t.amount_usd, t.reason ?? null);
                    }
                    break;
                }
                case 'rsi_history': {
                    if (typeof window.setRsiHistory === 'function') {
                        window.setRsiHistory(msg.payload);
                    }
                    if (typeof window.updateCandleChartFromHistory === 'function') {
                        window.updateCandleChartFromHistory(msg.payload);
                    }
                    updateState('rsiHistoryLoaded', true);
                    break;
                }
                case 'error': {
                    showErrorBanner(msg.payload.message || 'An error occurred');
                    // Error log entry could be added here
                    break;
                }
            }
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    ws.onclose = () => {
        setWsStatus('disconnected');
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => setWsStatus('disconnected');
}
