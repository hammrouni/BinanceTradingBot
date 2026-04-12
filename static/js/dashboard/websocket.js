/**
 * websocket.js — WebSocket communication for the dashboard.
 */

import { updateState, state } from './state.js';
import { 
    updatePrice, updateRsi, updateBotStatus, 
    showErrorBanner, hideErrorBanner, startUptimeTicker,
    tickToCandle, replayTradeMarkers, buildCandlesFromHistory,
    addErrorEntry
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
                    const { price, rsi, timestamp, open, high, low } = msg.payload;
                    updatePrice(price);
                    const nowMs = timestamp ? new Date(timestamp).getTime() : Date.now();
                    tickToCandle(price, nowMs, open, high, low);
                    // Only push to RSI chart buffer when we have an actual RSI value
                    if (rsi != null) {
                        updateRsi(rsi, timestamp);
                    }
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
                        // Immediately show position — bot_status will follow with full details
                        if (window.updateOpenPosition && t.price && t.quantity) {
                            window.updateOpenPosition({
                                pair:             t.pair ?? state.currentConfig?.trading_pair ?? '',
                                entry_price:      t.price,
                                quantity:         t.quantity,
                                stop_loss_price:  null,
                                take_profit_price: null,
                            });
                        }
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
                    if (typeof window.updateCandleChart === 'function') {
                        const candles = buildCandlesFromHistory(msg.payload);
                        if (candles.length) {
                            window.updateCandleChart(candles);
                            // Initialise active candle from the last historical point
                            const last = candles[candles.length - 1];
                            updateState('activeCandleTs', last.x);
                            updateState('activeCandle', { ...last });
                        }
                    }
                    updateState('rsiHistoryLoaded', true);
                    replayTradeMarkers();
                    break;
                }
                case 'error': {
                    showErrorBanner(msg.payload.message || 'An error occurred');
                    addErrorEntry(msg.payload, msg.timestamp);
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
