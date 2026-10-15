/**
 * websocket.js — WebSocket communication for the dashboard.
 */

import { updateState, state } from './state.js';
import { 
    updatePrice, updateRsi, updateRsiUltra, updateBcHeader, updateBotStatus, 
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
    const ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/dashboard`);
    let opened = false;

    ws.onopen = () => {
        opened = true;
        setWsStatus('connected');
        // Initial sync is handled in index.js
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            switch (msg.type) {
                case 'market_update': {
                    const { price, rsi, rsi_ultra_raw, rsi_ultra_signal, timestamp, open, high, low } = msg.payload;
                    updatePrice(price);
                    
                    // Always cache latest indicators for agents/UI
                    if (rsi != null) updateState('latestRsi', rsi);
                    if (rsi_ultra_raw != null) updateState('latestRsiUltraRaw', rsi_ultra_raw);
                    if (rsi_ultra_signal != null) updateState('latestRsiUltraSignal', rsi_ultra_signal);

                    const nowMs = timestamp ? new Date(timestamp).getTime() : Date.now();
                    tickToCandle(price, nowMs, open, high, low);
                    
                    const isUltra = (state.currentConfig?.active_modes || []).includes('RSI_ULTRA');
                    const isBc = (state.currentConfig?.active_modes || []).includes('BC');
                    
                    if (isUltra && rsi_ultra_raw != null) {
                        updateRsiUltra(rsi_ultra_raw, rsi_ultra_signal, timestamp);
                    } else if (isBc) {
                        updateBcHeader();
                    } else if (rsi != null) {
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
                    
                    // Sync latest indicators from history so AI advisor works immediately after refresh
                    if (msg.payload && msg.payload.length > 0) {
                        const lastPoint = msg.payload[msg.payload.length - 1];
                        if (lastPoint.rsi !== undefined) updateState('latestRsi', lastPoint.rsi);
                        if (lastPoint.rsi_ultra_raw !== undefined) updateState('latestRsiUltraRaw', lastPoint.rsi_ultra_raw);
                        if (lastPoint.rsi_ultra_signal !== undefined) updateState('latestRsiUltraSignal', lastPoint.rsi_ultra_signal);
                    }
                    
                    // Ensure threshold history is loaded after RSI data arrives
                    // (guards against race where WS fires before init fetch resolves)
                    if (typeof window.getRsiHistory === 'function' && typeof window.setRsiThresholdHistory === 'function') {
                        window.getRsiHistory().then(h => { if (h) window.setRsiThresholdHistory(h); }).catch(() => {});
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
        // A handshake rejected for a missing/wrong token looks like a failed connect:
        // probing a protected REST route lets auth.js prompt for the token.
        if (!opened) fetch('/api/v1/status').catch(() => {});
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => setWsStatus('disconnected');
}
