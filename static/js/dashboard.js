// dashboard.js — BinanceTradingBot dashboard logic

// ─── State ────────────────────────────────────────────────────────────────────
let _openPosition     = null;
let _prevPrice        = null;
let _currentConfig    = {};
let _uptimeInterval   = null;
let _startedAt        = null;
let _totalPnl         = 0;
let _tradeCount       = 0;
let _rsiHistoryLoaded = false;
let _loadedProdTrades   = [];    // Real trades from Binance
let _loadedTestTrades   = [];    // Test trades from local logs
let _currentBalances    = null;  // Store most recent balances globally

// ─── Candle aggregation ───────────────────────────────────────────────────────
const _CANDLE_MS = 60 * 1000;   // 1-minute candle period
let _activeCandleTs  = null;
let _activeCandle    = null;

/** Aggregate a single price tick into the current 1-min candle. */
function _tickToCandle(price, nowMs) {
    const periodStart = Math.floor(nowMs / _CANDLE_MS) * _CANDLE_MS;
    if (_activeCandleTs !== periodStart) {
        _activeCandleTs = periodStart;
        _activeCandle   = { x: periodStart, o: price, h: price, l: price, c: price };
    } else {
        _activeCandle.h = Math.max(_activeCandle.h, price);
        _activeCandle.l = Math.min(_activeCandle.l, price);
        _activeCandle.c = price;
    }
    if (typeof upsertCandle === 'function') upsertCandle({ ..._activeCandle });
}

/**
 * Build OHLC candle objects from RSI history points.
 * Each point has: { timestamp, rsi, price (close), open?, high?, low? }
 * Falls back to using previous-close as open so candle bodies are visible
 * even when real OHLC fields are not (yet) sent by the backend.
 */
function _buildCandlesFromHistory(points) {
    if (!points || !points.length) return [];
    const sorted = points
        .filter(p => p.timestamp && p.price != null)
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    return sorted.map((p, i) => {
        const close     = p.price;
        const prevClose = i > 0 ? sorted[i - 1].price : close;
        const open      = p.open  ?? prevClose;   // prev-close = open (classic OHLC convention)
        const high      = p.high  ?? Math.max(open, close);
        const low       = p.low   ?? Math.min(open, close);
        return { x: new Date(p.timestamp).getTime(), o: open, h: high, l: low, c: close };
    });
}

// ─── Price display ────────────────────────────────────────────────────────────

function updatePrice(price) {
    const formatted = '$' + Number(price).toLocaleString('en-US', {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
    });

    const el       = document.getElementById('current-price');
    const deltaEl  = document.getElementById('price-delta');
    const headerEl = document.getElementById('header-price');

    if (el)       el.textContent = formatted;
    if (headerEl) headerEl.textContent = formatted;

    if (deltaEl && _prevPrice != null && _prevPrice !== 0) {
        const diff = price - _prevPrice;
        const pct  = diff / _prevPrice * 100;
        const arrow = diff >= 0 ? '▲' : '▼';
        deltaEl.textContent = `${arrow} ${Math.abs(pct).toFixed(2)}%`;
        deltaEl.className   = 'price-delta ' + (diff >= 0 ? 'up' : 'down');
    }

    _prevPrice = price;
    updateUnrealisedPnl(price);
    updateLastUpdated();
}

// ─── RSI display ─────────────────────────────────────────────────────────────
function updateRsi(rsi, timestamp) {
    const el       = document.getElementById('current-rsi');
    const zoneEl   = document.getElementById('rsi-zone-label');
    const headerEl = document.getElementById('header-rsi');
    if (!el) return;

    if (rsi == null) {
        // preserve the last known value during real-time price ticks
        return;
    }

    const value = Number(rsi).toFixed(2);
    if (el)       el.textContent = value;
    if (headerEl) headerEl.textContent = value;

    el.className = '';
    if (zoneEl) {
        if (rsi < 30) {
            el.classList.add('rsi-oversold');
            zoneEl.textContent = 'Oversold';
            zoneEl.className   = 'rsi-zone-label oversold';
        } else if (rsi > 70) {
            el.classList.add('rsi-overbought');
            zoneEl.textContent = 'Overbought';
            zoneEl.className   = 'rsi-zone-label overbought';
        } else {
            el.classList.add('rsi-neutral');
            zoneEl.textContent = 'Neutral';
            zoneEl.className   = 'rsi-zone-label neutral';
        }
    }

    if (typeof updateRsiChart === 'function') updateRsiChart(rsi, timestamp, _prevPrice);
}

// ─── Bot status ───────────────────────────────────────────────────────────────
function updateBotStatus(status, balances) {
    const s     = status.toLowerCase();
    const label = s.charAt(0).toUpperCase() + s.slice(1);

    const indicator = document.getElementById('status-indicator');
    const dot       = document.getElementById('status-dot');
    const headerEl  = document.getElementById('header-status');

    if (indicator) { indicator.textContent = label; indicator.className = 'status-' + s; }
    if (dot)        dot.className = 'status-dot ' + s;
    if (headerEl)  { headerEl.textContent = label; headerEl.className = 'stat-value status-' + s; }

    // Update wallet if provided
    if (balances) updateWallet(balances);

    // Context-aware buttons — show only the valid action
    const btnStart  = document.getElementById('btn-start');
    const btnPause  = document.getElementById('btn-pause');
    const btnResume = document.getElementById('btn-resume');
    const btnStop   = document.getElementById('btn-stop');

    if (btnStart)  btnStart.classList.toggle('hidden',  s === 'running' || s === 'paused');
    if (btnPause)  btnPause.classList.toggle('hidden',  s !== 'running');
    if (btnResume) btnResume.classList.toggle('hidden', s !== 'paused');
    if (btnStop)   btnStop.classList.toggle('hidden',   s !== 'running' && s !== 'paused');

    // Re-enable all after state update
    [btnStart, btnPause, btnResume, btnStop].forEach(b => { if (b) b.disabled = false; });

    // Uptime ticker
    const uptimeDiv = document.getElementById('uptime-display');
    if (s === 'running' || s === 'paused') {
        uptimeDiv?.classList.remove('hidden');
    } else {
        uptimeDiv?.classList.add('hidden');
        clearInterval(_uptimeInterval);
        _startedAt = null;
    }
}

// ─── Wallet display ───────────────────────────────────────────────────────────
function updateWallet(balances) {
    const prodContainer    = document.getElementById('wallet-balances-prod');
    const tradingContainer = document.getElementById('wallet-balances-trading');
    const badge            = document.getElementById('trade-env-badge');
    const walletSection    = document.getElementById('trading-wallet-section');
    const overlay          = document.getElementById('testnet-disabled-overlay');
    
    _currentBalances = balances; // Store globally for "MAX" button
    
    if (!prodContainer || !tradingContainer) return;

    // Detect environment from incoming balances OR persistent config
    const env = balances?.trading_env || _currentConfig?.trading_env || 'testnet';

    // 1. Update Badge
    if (badge) {
        badge.textContent = env.toUpperCase();
        badge.className   = 'trading-env-badge ' + env;
    }

    // 2. Handle "Disabled" state for Trading wallet if in Live mode
    if (env === 'live') {
        walletSection?.classList.add('is-live');
        overlay?.classList.remove('hidden');
    } else {
        walletSection?.classList.remove('is-live');
        overlay?.classList.add('hidden');
    }

    // 3. Update Visibility for Header and History Based on Environment
    if (typeof applyEnvironmentVisibility === 'function') {
        applyEnvironmentVisibility(env);
    }

    // 4. Helper to render a specific balance set
    const _render = (container, data, nwId) => {
        const assets = data?.assets || {};
        const netWorth = data?.total_net_worth || 0;

        // Update Net Worth Display
        const nwEl = document.getElementById(nwId);
        if (nwEl) {
            nwEl.textContent = '$' + Number(netWorth).toLocaleString('en-US', {
                minimumFractionDigits: 2, maximumFractionDigits: 2
            });
        }

        if (Object.keys(assets).length === 0) {
            if (!container.querySelector('.wallet-asset-row')) {
                container.innerHTML = '<div class="wallet-empty">Refreshing...</div>';
            }
            return;
        }

        // Sort assets by value (USDT first, then by alphabetical or estimated value if we had it)
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

    // 5. Render both
    _render(prodContainer,    balances.prod,    'net-worth-prod');
    _render(tradingContainer, balances.trading, 'net-worth-trading');
}

// ─── Uptime ticker ────────────────────────────────────────────────────────────
function startUptimeTicker(isoTimestamp) {
    if (isoTimestamp) _startedAt = new Date(isoTimestamp);
    if (!_startedAt)  _startedAt = new Date();
    clearInterval(_uptimeInterval);
    _uptimeInterval = setInterval(() => {
        const secs = Math.floor((Date.now() - _startedAt.getTime()) / 1000);
        const h = Math.floor(secs / 3600);
        const m = Math.floor((secs % 3600) / 60);
        const s = secs % 60;
        const el = document.getElementById('uptime-value');
        if (el) el.textContent = h > 0 ? `${h}h ${m}m ${s}s`
            : m > 0 ? `${m}m ${s}s` : `${s}s`;
    }, 1000);
}

// ─── Last updated ─────────────────────────────────────────────────────────────
function updateLastUpdated() {
    const el = document.getElementById('last-updated');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
}

// ─── Error banner (top) ───────────────────────────────────────────────────────
function showErrorBanner(msg) {
    const banner = document.getElementById('error-banner');
    const msgEl  = document.getElementById('error-message');
    if (!banner) return;
    if (msgEl) msgEl.textContent = translateError(msg);
    banner.classList.remove('hidden');
}

function hideErrorBanner() {
    document.getElementById('error-banner')?.classList.add('hidden');
}

function translateError(raw) {
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

// ─── Error log ────────────────────────────────────────────────────────────────
const MAX_ERROR_ENTRIES = 20;

function addErrorEntry(payload, timestamp) {
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

function bindClearErrors() {
    document.getElementById('btn-clear-errors')?.addEventListener('click', () => {
        const list    = document.getElementById('error-list');
        const section = document.getElementById('error-log-section');
        if (list) list.innerHTML = '';
        section?.classList.add('hidden');
    });
}

// ─── WebSocket ────────────────────────────────────────────────────────────────
function setWsStatus(state) {
    const el    = document.getElementById('ws-status');
    const label = el?.querySelector('.ws-label');
    if (!el) return;
    el.className = 'ws-indicator ws-' + state;
    if (label) label.textContent =
        state === 'connected'    ? 'Live' :
        state === 'connecting'   ? 'Connecting...' : 'Disconnected';
}

function connectWebSocket() {
    setWsStatus('connecting');
    const ws = new WebSocket(`ws://${window.location.host}/ws/dashboard`);

    ws.onopen = () => setWsStatus('connected');

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            switch (msg.type) {
                case 'market_update': {
                    const { price, rsi, timestamp } = msg.payload;
                    updatePrice(price);
                    updateRsi(rsi, timestamp);
                    // Feed live tick into the candlestick chart
                    _tickToCandle(price, timestamp ? new Date(timestamp).getTime() : Date.now());
                    break;
                }
                case 'bot_status': {
                    updateBotStatus(msg.payload.state, msg.payload.balances);
                    updateOpenPosition(msg.payload.open_position || null);
                    if (msg.payload.state === 'RUNNING') hideErrorBanner();
                    if (msg.payload.state === 'RUNNING' && !_startedAt)
                        startUptimeTicker(msg.timestamp);
                    break;
                }
                case 'trade_executed': {
                    const t = msg.payload;
                    const isTest = t.is_test ?? (_currentConfig.trading_env === 'testnet');
                    
                    // Full refresh from server to ensure all PnL and fee calculations are synced
                    loadTradeHistory();

                    const tradeMs = t.executed_at ? new Date(t.executed_at).getTime() : Date.now();
                    if (t.direction === 'buy') {
                        updateOpenPosition({
                            pair: t.pair, quantity: t.quantity,
                            entry_price: t.price, stop_loss_price: null,
                        });
                        if (typeof markBuySignal === 'function') markBuySignal(t.price, isTest, t.amount_usd, t.reason ?? 'buy_signal');
                        if (!isTest && typeof markCandleBuy === 'function') markCandleBuy(tradeMs, t.price, t.amount_usd, t.reason ?? 'buy_signal');
                    } else if (t.direction === 'sell') {
                        updateOpenPosition(null);
                        if (typeof markSellSignal === 'function') markSellSignal(t.price, isTest, t.amount_usd, t.reason ?? 'signal');
                        if (!isTest && typeof markCandleSell === 'function') markCandleSell(tradeMs, t.price, t.amount_usd, t.reason ?? 'signal');
                    }
                    break;
                }
                case 'rsi_history': {
                    if (typeof setRsiHistory === 'function') {
                        setRsiHistory(msg.payload);
                    }
                    // Build candlestick bars from the same history payload
                    if (typeof updateCandleChart === 'function') {
                        const candles = _buildCandlesFromHistory(msg.payload);
                        if (candles.length) {
                            updateCandleChart(candles);
                            // Seed the live-tick aggregator at the last candle's period
                            const last = candles[candles.length - 1];
                            _activeCandleTs = last.x;
                            _activeCandle   = { x: last.x, o: last.o, h: last.h, l: last.l, c: last.c };
                        }
                    }
                    _rsiHistoryLoaded = true;
                    _replayTradeMarkers();
                    // Update the bot preview with current RSI
                    if (_currentConfig) updateBotPreview(_currentConfig);
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

// ─── Environment Visibility ────────────────────────────────────────────────────
function applyEnvironmentVisibility(env) {
    const isLive = (env === 'live');
    
    // Header
    document.getElementById('test-pnl-pill')?.classList.toggle('hidden', isLive);
    
    // Wallet
    document.getElementById('trading-wallet-section')?.classList.toggle('hidden', isLive);
    document.getElementById('wallet-divider-vertical')?.classList.toggle('hidden', isLive);
    
    // Trade History
    document.getElementById('test-trade-history')?.classList.toggle('hidden', isLive);

    // Chart Signals
    if (typeof setChartEnv === 'function') {
        setChartEnv(isLive);
    } else if (typeof setChartHideTestData === 'function') {
        setChartHideTestData(isLive);
    }
}

// ─── Config panel ─────────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const data = await getConfig();
        _currentConfig = data;
        document.getElementById('trading-pair').value  = data.trading_pair || '';
        document.getElementById('trade-amount').value  = data.trade_amount_usd !== null ? data.trade_amount_usd : '';
        document.getElementById('rsi-oversold').value = data.rsi_oversold !== null ? data.rsi_oversold : '';
        document.getElementById('rsi-overbought').value = data.rsi_overbought !== null ? data.rsi_overbought : '';
        document.getElementById('stop-loss-pct').value   = data.stop_loss_pct !== null ? data.stop_loss_pct : '';
        document.getElementById('take-profit-pct').value = data.take_profit_pct !== null ? data.take_profit_pct : '';
        
        updateLegendLabels(data.rsi_oversold, data.rsi_overbought);

        if (typeof updateChartThresholds === 'function')
            updateChartThresholds(data.rsi_oversold, data.rsi_overbought);
            
        applyEnvironmentVisibility(data.trading_env);
        
        // Refresh open position to update chart SL/TP lines with loaded config
        if (_openPosition) updateOpenPosition(_openPosition);

        // Also load RSI history to populate the stepwise lines
        await loadRsiHistory();
        updateBotPreview(data);
    } catch (e) {
        console.error('Failed to load config:', e);
    }
}

function updateBotPreview(config) {
    const box = document.getElementById('bot-preview');
    if (!box) return;
    
    const latestRsi = typeof getLatestRsi === 'function' ? getLatestRsi() : null;
    
    if (!config.rsi_oversold && !config.rsi_overbought) {
        box.innerHTML = '<div class="preview-item"><span class="preview-value neutral">Configure RSI thresholds to see bot actions</span></div>';
        return;
    }
    
    let html = '';
    
    const os = config.rsi_oversold;
    const ob = config.rsi_overbought;
    const currentRsi = latestRsi;
    
    if (os && currentRsi !== null) {
        const willBuy = currentRsi < os;
        html += `<div class="preview-item">
            <span class="preview-label">BUY if:</span>
            <span class="preview-value ${willBuy ? 'buy' : 'neutral'}">RSI ${currentRsi.toFixed(1)} &lt; ${os}</span>
            <span class="preview-condition">${willBuy ? '✅ WILL BUY' : '❌ No signal'}</span>
        </div>`;
    }
    
    if (ob && currentRsi !== null) {
        const willSell = currentRsi > ob;
        html += `<div class="preview-item">
            <span class="preview-label">SELL if:</span>
            <span class="preview-value ${willSell ? 'sell' : 'neutral'}">RSI ${currentRsi.toFixed(1)} &gt; ${ob}</span>
            <span class="preview-condition">${willSell ? '✅ WILL SELL' : '❌ No signal'}</span>
        </div>`;
    }
    
    if (config.stop_loss_pct) {
        html += `<div class="preview-item">
            <span class="preview-label">Stop-Loss:</span>
            <span class="preview-value active">${config.stop_loss_pct}%</span>
            <span class="preview-condition">${_openPosition ? '🔴 Active' : '⏸ Waiting'}</span>
        </div>`;
    }
    
    if (config.take_profit_pct !== null && config.take_profit_pct !== undefined) {
        html += `<div class="preview-item">
            <span class="preview-label">Take-Profit:</span>
            <span class="preview-value active">${config.take_profit_pct}%</span>
            <span class="preview-condition">${_openPosition ? '🟢 Active' : '⏸ Waiting'}</span>
        </div>`;
    }
    
    if (!html) {
        html = '<div class="preview-item"><span class="preview-value neutral">Configure thresholds above</span></div>';
    }
    
    box.innerHTML = html;
}

async function loadRsiHistory() {
    try {
        const history = await getRsiHistory();
        if (typeof setRsiThresholdHistory === 'function') {
            setRsiThresholdHistory(history);
        }
    } catch (e) {
        console.error('Failed to load RSI history:', e);
    }
}

function updateLegendLabels(oversold, overbought) {
    const labelOversold = document.getElementById('label-oversold');
    const labelOverbought = document.getElementById('label-overbought');
    if (labelOversold) labelOversold.textContent = `Oversold ${oversold}`;
    if (labelOverbought) labelOverbought.textContent = `Overbought ${overbought}`;
}

function validateConfig(data) {
    const errors = {};
    if (!data.trading_pair) {
        errors.trading_pair = 'Required';
    } else if (!/^[A-Z0-9]+$/.test(data.trading_pair)) {
        errors.trading_pair = 'Invalid format (e.g. BTCUSDT)';
    }

    if (data.trade_amount_usd !== null) {
        if (data.trade_amount_usd <= 0) {
            errors.trade_amount_usd = 'Must be > 0';
        }
    }

    if (data.rsi_oversold !== null && (data.rsi_oversold < 1 || data.rsi_oversold > 100))
        errors.rsi_oversold = 'Must be 1–100';
    if (data.rsi_overbought !== null && (data.rsi_overbought < 1 || data.rsi_overbought > 100))
        errors.rsi_overbought = 'Must be 1–100';
    if (data.stop_loss_pct !== null && (data.stop_loss_pct < 0.1 || data.stop_loss_pct > 50))
        errors.stop_loss_pct = 'Must be 0.1–50';
    if (data.take_profit_pct !== null && data.take_profit_pct !== 0 && (data.take_profit_pct < 0.1 || data.take_profit_pct > 100))
        errors.take_profit_pct = 'Must be 0 (off) or 0.1–100';
    return errors;
}

const CONFIG_PRESETS = {
    aggressive:   { rsi_oversold: 40, rsi_overbought: 60, stop_loss_pct: 1.0,  take_profit_pct: 0.5 },
    conservative: { rsi_oversold: 15, rsi_overbought: 85, stop_loss_pct: 3.0,  take_profit_pct: 2.0 },
    balanced:     { rsi_oversold: 30, rsi_overbought: 70, stop_loss_pct: 1.5,  take_profit_pct: 1.0 },
    scalper:      { rsi_oversold: 50, rsi_overbought: 50, stop_loss_pct: 0.5,  take_profit_pct: 0.2 },
};

function bindConfigForm() {
    const form = document.getElementById('config-form');
    if (!form) return;

    // Preset dropdown — fills fields and marks them dirty; does NOT auto-save
    const presetSelect = document.getElementById('config-preset');
    if (presetSelect) {
        presetSelect.addEventListener('change', () => {
            const preset = CONFIG_PRESETS[presetSelect.value];
            if (!preset) return;
            const set = (id, val) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.value = val;
                el.classList.add('dirty');
            };
            set('rsi-oversold',   preset.rsi_oversold);
            set('rsi-overbought', preset.rsi_overbought);
            set('stop-loss-pct',  preset.stop_loss_pct);
            set('take-profit-pct', preset.take_profit_pct);
            // Reset dropdown so it can be re-selected and hint is visible
            presetSelect.value = '';
            document.getElementById('config-status').textContent = '';
        });
    }

    // Mark inputs dirty on change
    form.querySelectorAll('input').forEach(input =>
        input.addEventListener('input', () => {
            input.classList.add('dirty');
            // Live update the bot preview
            const data = {
                rsi_oversold: parseInt(document.getElementById('rsi-oversold').value) || null,
                rsi_overbought: parseInt(document.getElementById('rsi-overbought').value) || null,
                stop_loss_pct: parseFloat(document.getElementById('stop-loss-pct').value) || null,
                take_profit_pct: parseFloat(document.getElementById('take-profit-pct').value) || null,
            };
            updateBotPreview(data);
        })
    );

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const parse = (id, fn) => {
            const el = document.getElementById(id);
            if (!el) return null;
            let v = el.value.trim();
            if (v.includes(',')) v = v.replace(',', '.');
            return v === '' ? null : fn(v);
        };

        const data = {
            trading_pair:     document.getElementById('trading-pair').value.trim().toUpperCase(),
            trade_amount_usd: parse('trade-amount', parseFloat),
            rsi_oversold:     parse('rsi-oversold', v => parseInt(v, 10)),
            rsi_overbought:   parse('rsi-overbought', v => parseInt(v, 10)),
            stop_loss_pct:    parse('stop-loss-pct', parseFloat),
            take_profit_pct:  parse('take-profit-pct', parseFloat),
        };

        document.querySelectorAll('.field-error').forEach(el => el.textContent = '');
        const errors = validateConfig(data);
        if (Object.keys(errors).length) {
            for (const [field, msg] of Object.entries(errors)) {
                const el = document.getElementById(`err-${field.replace(/_/g, '-')}`);
                if (el) el.textContent = msg;
            }
            return;
        }

        const btn = document.getElementById('btn-save-config');
        btn.disabled    = true;
        btn.textContent = 'Saving…';

        const res = await updateConfig(data);

        btn.disabled    = false;
        btn.textContent = 'Save Configuration';

        const statusEl = document.getElementById('config-status');
        if (res.ok) {
            const resp = await res.json();
            const savedData = resp.data;
            _currentConfig = savedData;
            
            document.getElementById('trading-pair').value  = savedData.trading_pair || '';
            document.getElementById('trade-amount').value  = savedData.trade_amount_usd !== null ? savedData.trade_amount_usd : '';
            document.getElementById('rsi-oversold').value = savedData.rsi_oversold !== null ? savedData.rsi_oversold : '';
            document.getElementById('rsi-overbought').value = savedData.rsi_overbought !== null ? savedData.rsi_overbought : '';
            document.getElementById('stop-loss-pct').value   = savedData.stop_loss_pct !== null ? savedData.stop_loss_pct : '';
            document.getElementById('take-profit-pct').value = savedData.take_profit_pct !== null ? savedData.take_profit_pct : '';

            form.querySelectorAll('input').forEach(i => i.classList.remove('dirty'));
            statusEl.textContent = '✓ Configuration saved';
            statusEl.className   = 'status-success';
            setTimeout(() => { statusEl.textContent = ''; }, 3500);
            
            updateLegendLabels(savedData.rsi_oversold, savedData.rsi_overbought);

            if (typeof updateChartThresholds === 'function')
                updateChartThresholds(savedData.rsi_oversold, savedData.rsi_overbought);

            // Refresh open position to update chart SL line with new config
            if (_openPosition) updateOpenPosition(_openPosition);

            // Update the "What Bot Will Do" preview
            updateBotPreview(savedData);
        } else if (res.status === 422) {
            const { detail } = await res.json();
            detail.forEach(err => {
                const field = err.loc[err.loc.length - 1];
                const el = document.getElementById(`err-${field.replace(/_/g, '-')}`);
                if (el) el.textContent = err.msg;
            });
        } else {
            statusEl.textContent = 'Save failed — please try again';
            statusEl.className   = 'status-error-msg';
        }
    });

    // "MAX" button for Trade Amount
    document.getElementById('btn-set-max')?.addEventListener('click', () => {
        if (!_currentBalances) return;
        
        // Use the environment to pick the right wallet (Live = Prod, Testnet = Trading)
        const env = _currentConfig?.trading_env || 'testnet';
        const data = (env === 'live') ? _currentBalances.prod : _currentBalances.trading;
        
        if (!data || !data.assets) return;

        // Specifically look for Spot USDT
        const spotAsset = data.assets['USDT (Spot)'];
        if (spotAsset) {
            const available = spotAsset.free;
            // Apply 0.5% safety margin for fees/slippage
            const finalVal = (available * 0.995).toFixed(2);
            const input = document.getElementById('trade-amount');
            if (input) {
                input.value = finalVal;
                input.classList.add('dirty');
            }
        }
    });

    // Live preview for Stop-Loss line as user types
    document.getElementById('stop-loss-pct')?.addEventListener('input', (e) => {
        const pct = parseFloat(e.target.value);
        if (!isNaN(pct) && pct >= 0.1 && pct <= 50) {
            _currentConfig.stop_loss_pct = pct;
            if (_openPosition) updateOpenPosition(_openPosition);
        }
    });

    // Live preview for Take-Profit line as user types
    document.getElementById('take-profit-pct')?.addEventListener('input', (e) => {
        const pct = parseFloat(e.target.value);
        if (!isNaN(pct) && (pct === 0 || (pct >= 0.1 && pct <= 100))) {
            _currentConfig.take_profit_pct = pct;
            if (_openPosition) updateOpenPosition(_openPosition);
        }
    });
}

// ─── Bot controls ─────────────────────────────────────────────────────────────
function setButtonLoading(btn, html) {
    if (!btn) return;
    btn.disabled  = true;
    btn.innerHTML = '…';
    // Re-enable after timeout as safety fallback (state update via WS will re-enable normally)
    setTimeout(() => {
        btn.disabled  = false;
        btn.innerHTML = html;
    }, 5000);
}

function bindBotControls() {
    document.getElementById('btn-start')?.addEventListener('click', async (e) => {
        setButtonLoading(e.currentTarget, '<span class="control-icon">\u25B6\uFE0E</span> Start');
        await startBot();
    });
    document.getElementById('btn-pause')?.addEventListener('click', async (e) => {
        setButtonLoading(e.currentTarget, '<span class="control-icon">\u23F8\uFE0E</span> Pause');
        await pauseBot();
    });
    document.getElementById('btn-resume')?.addEventListener('click', async (e) => {
        setButtonLoading(e.currentTarget, '<span class="control-icon">\u25B6\uFE0E</span> Resume');
        await resumeBot();
    });
    document.getElementById('btn-stop')?.addEventListener('click', async (e) => {
        setButtonLoading(e.currentTarget, '<span class="control-icon">\u23F9\uFE0E</span> Stop');
        await stopBot();
    });
    document.getElementById('btn-manual-trade')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const isSell = btn.classList.contains('btn-manual-sell');
        const icon = isSell ? '&#x1F4B8;' : '&#x1F4B5;';
        const label = isSell ? 'Manual Sell' : 'Manual Buy';
        
        setButtonLoading(btn, `<span class="control-icon">${icon}</span> ${label}`);
        
        try {
            if (isSell) {
                await manualSell();
            } else {
                await manualBuy();
            }
        } catch (err) {
            console.error('Manual trade failed:', err);
        }
    });
}

// ─── Open position ────────────────────────────────────────────────────────────
function updateOpenPosition(pos) {
    const card    = document.getElementById('open-position-card');
    const content = document.getElementById('open-position-content');
    if (!card || !content) return;

    if (pos) {
        _openPosition = pos;

        // Compute stop-loss if not provided by backend
        let stopLossDisplay = '—';
        let slPrice = pos.stop_loss_price;
        if (slPrice == null && _currentConfig.stop_loss_pct && pos.entry_price) {
            slPrice = pos.entry_price * (1 - _currentConfig.stop_loss_pct / 100);
        }
        if (slPrice != null) {
            const lossUsd = (slPrice - (pos.entry_price || 0)) * (pos.quantity || 0);
            stopLossDisplay = `$${Number(slPrice).toFixed(2)} <span class="pnl-negative">(-$${Math.abs(lossUsd).toFixed(2)})</span>`;
        }
        
        // Compute take-profit if not provided by backend
        let takeProfitDisplay = 'Disabled';
        let tpPrice = pos.take_profit_price;
        if (tpPrice == null && _currentConfig.take_profit_pct && _currentConfig.take_profit_pct > 0 && pos.entry_price) {
            tpPrice = pos.entry_price * (1 + _currentConfig.take_profit_pct / 100);
        }
        if (tpPrice != null) {
            const profitUsd = (tpPrice - (pos.entry_price || 0)) * (pos.quantity || 0);
            takeProfitDisplay = `$${Number(tpPrice).toFixed(2)} <span class="pnl-positive">(+$${profitUsd.toFixed(2)})</span>`;
        }

        content.innerHTML = `
            <div class="position-grid">
                <div class="position-item">
                    <span class="position-label">Pair</span>
                    <span class="position-value">${pos.pair || '—'}</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Quantity</span>
                    <span class="position-value">${pos.quantity?.toFixed(6) || '—'}</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Entry Price</span>
                    <span class="position-value">$${pos.entry_price?.toFixed(2) || '—'}</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Stop-Loss</span>
                    <span class="position-value stop-loss-value">${stopLossDisplay}</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Take Profit</span>
                    <span class="position-value take-profit-value">${takeProfitDisplay}</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Current Price</span>
                    <span class="position-value" id="pos-current-price">—</span>
                </div>
                <div class="position-item">
                    <span class="position-label">Unrealized P&amp;L</span>
                    <span class="position-value" id="pos-pnl">—</span>
                </div>
            </div>`;
        card.classList.remove('hidden');
        document.getElementById('header-active-pnl-pill')?.classList.remove('hidden');

        // Update chart target lines (SL/TP) — Prioritize config % for visual feedback
        if (typeof updateChartSl === 'function') {
            const sl = (pos.entry_price * (1 - (_currentConfig.stop_loss_pct || 0) / 100));
            updateChartSl(sl);
            if (typeof updateCandleChartSl === 'function') updateCandleChartSl(sl);
        }
        if (typeof updateChartTp === 'function') {
            const tp = (pos.entry_price * (1 + (_currentConfig.take_profit_pct || 0) / 100));
            const hasTp = _currentConfig.take_profit_pct > 0;
            updateChartTp(hasTp ? tp : null);
            if (typeof updateCandleChartTp === 'function') updateCandleChartTp(hasTp ? tp : null);
        }
        if (typeof updateChartOpenPositionBuy === 'function') {
            updateChartOpenPositionBuy(pos.entry_price);
        }

        // Immediately update PnL if we have a current price
        if (_prevPrice != null) {
            updateUnrealisedPnl(_prevPrice);
        }
    } else {
        _openPosition = null;
        card.classList.add('hidden');
        document.getElementById('header-active-pnl-pill')?.classList.add('hidden');

        // Hide chart target lines on both charts
        if (typeof updateChartSl === 'function') updateChartSl(null);
        if (typeof updateCandleChartSl === 'function') updateCandleChartSl(null);
        if (typeof updateChartTp === 'function') updateChartTp(null);
        if (typeof updateCandleChartTp === 'function') updateCandleChartTp(null);
        if (typeof updateChartOpenPositionBuy === 'function') updateChartOpenPositionBuy(null);
    }
    updateManualTradeButton(pos);
}

function updateManualTradeButton(pos) {
    const btn = document.getElementById('btn-manual-trade');
    if (!btn) return;

    if (pos) {
        btn.innerHTML = '<span class="control-icon">&#x1F4B8;</span> Manual Sell';
        btn.className = 'btn-manual-sell';
    } else {
        btn.innerHTML = '<span class="control-icon">&#x1F4B5;</span> Manual Buy';
        btn.className = 'btn-manual-buy';
    }
    btn.disabled = false;
}

function updateUnrealisedPnl(currentPrice) {
    if (!_openPosition) return;
    const pnl = (currentPrice - (_openPosition.entry_price || 0)) * (_openPosition.quantity || 0);
    const priceEl = document.getElementById('pos-current-price');
    const pnlEl   = document.getElementById('pos-pnl');
    if (priceEl) priceEl.textContent = `$${currentPrice.toFixed(2)}`;
    if (pnlEl) {
        const sign = pnl >= 0 ? '+' : '';
        const value = `${sign}$${pnl.toFixed(2)}`;
        const className = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        
        pnlEl.textContent = value;
        pnlEl.className   = 'position-value ' + className;

        const headerPnl = document.getElementById('header-active-pnl');
        if (headerPnl) {
            headerPnl.textContent = value;
            headerPnl.className   = className;
        }
    }
}

// ─── Trade history ────────────────────────────────────────────────────────────
function formatTradeTime(date) {
    const diffMins = Math.floor((Date.now() - date.getTime()) / 60000);
    if (diffMins < 1)    return 'Just now';
    if (diffMins < 60)   return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function renderTradeRow(trade) {
    const tr    = document.createElement('tr');
    tr.className = trade.direction === 'buy' ? 'trade-buy' : 'trade-sell';

    const date  = trade.executed_at ? new Date(trade.executed_at) : null;
    const ago   = date ? formatTradeTime(date) : '—';
    const exact = trade.executed_at ? luxon.DateTime.fromISO(trade.executed_at).toFormat('MMM dd, HH:mm:ss') : '—';
    
    const price = trade.entry_price ?? trade.price;
    const side  = trade.direction === 'buy'
        ? '<span class="side-buy">BUY</span>'
        : '<span class="side-sell">SELL</span>';

    const fee = trade.fee_usd ?? 0;
    const feeCell = fee > 0
        ? `<td class="fee-cell">-$${fee.toFixed(4)}</td>`
        : `<td class="fee-cell fee-unknown">—</td>`;

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
        <td>$${trade.amount_usd?.toFixed(2) || '—'}</td>
        <td>$${price?.toFixed(2) || '—'}</td>
        <td>${trade.quantity?.toFixed(6) || '—'}</td>
        ${feeCell}
        ${pnlCell}
    `;
    return tr;
}

function addTradeRow(trade, isTest = false) {
    const bodyId = isTest ? 'test-trades-body' : 'trades-body';
    const emptyId = isTest ? 'test-trades-empty' : 'trades-empty';
    
    const tbody    = document.getElementById(bodyId);
    const emptyMsg = document.getElementById(emptyId);
    if (!tbody) return;
    if (emptyMsg) emptyMsg.style.display = 'none';
    
    tbody.insertBefore(renderTradeRow(trade), tbody.firstChild);
    while (tbody.rows.length > 50) tbody.deleteRow(-1);
}

function updateTradeSummary(trade, isTest = false) {
    // Current UI only shows summary for Prod, let's keep it simple or add both if needed
    // For now, we'll only update the summary of the table the trade belongs to.
    const trades = isTest ? _loadedTestTrades : _loadedProdTrades;
    trades.unshift(trade);
    renderTradeHistoryTable(trades, isTest);
}

function renderTradeHistoryTable(trades, isTest = false) {
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
        tbody.appendChild(renderTradeRow(t));
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
        const value = `${pnlLabel}: ${sign}$${totalPnl.toFixed(4)}`;
        const headerValue = `${sign}$${totalPnl.toFixed(4)}`;
        const className = totalPnl > 0 ? 'pnl-positive' : totalPnl < 0 ? 'pnl-negative' : 'pnl-neutral';
        const tooltip = feesTracked ? 'Net PnL — Binance fees already deducted' : 'PnL — Fees not tracked (old trades)';

        pnlEl.textContent = value;
        pnlEl.className   = className;
        pnlEl.title       = tooltip;

        const headerId = isTest ? 'header-test-pnl' : 'header-prod-pnl';
        const headerPnl = document.getElementById(headerId);
        if (headerPnl) {
            headerPnl.textContent = headerValue;
            headerPnl.className   = className;
            headerPnl.title       = tooltip;
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

async function loadTradeHistory() {
    try {
        // Fetch Prod History
        const prodResponse = await getTrades();
        _loadedProdTrades = Array.isArray(prodResponse) ? prodResponse : (prodResponse.data || []);
        
        const prodBody = document.getElementById('trades-body');
        if (prodBody) prodBody.innerHTML = '';
        renderTradeHistoryTable(_loadedProdTrades, false);

        // Fetch Test History
        const testResponse = await fetch('/api/v1/trades/test').then(r => r.json());
        _loadedTestTrades = Array.isArray(testResponse) ? testResponse : (testResponse.data || []);
        
        const testBody = document.getElementById('test-trades-body');
        if (testBody) testBody.innerHTML = '';
        renderTradeHistoryTable(_loadedTestTrades, true);

        _replayTradeMarkers();
    } catch (e) {
        console.error('Failed to load trade histories:', e);
    }
}

// ─── Replay BUY/SELL markers onto chart after both RSI history and trades are loaded
function _replayTradeMarkers() {
    if (!_rsiHistoryLoaded) return;
    if (typeof markSignalAtTime !== 'function') return;

    _loadedProdTrades.forEach(t => {
        if (t.executed_at) markSignalAtTime(t.executed_at, t.direction, t.entry_price || t.price, false, t.amount_usd, t.reason ?? (t.direction === 'buy' ? 'buy_signal' : 'signal'));
    });
    _loadedTestTrades.forEach(t => {
        if (t.executed_at) markSignalAtTime(t.executed_at, t.direction, t.entry_price || t.price, true, t.amount_usd, t.reason ?? (t.direction === 'buy' ? 'buy_signal' : 'signal'));
    });
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-dismiss-error')?.addEventListener('click', hideErrorBanner);
    connectWebSocket();
    loadConfig();
    bindConfigForm();
    bindBotControls();
    bindClearErrors();
    
    document.getElementById('btn-refresh-prod')?.addEventListener('click', () => {
        loadTradeHistory();
        refreshWallet();
    });
    document.getElementById('btn-refresh-test')?.addEventListener('click', () => {
        loadTradeHistory();
        refreshWallet();
    });
    
    loadTradeHistory();
    // Fetch initial bot status to set correct button states before first WebSocket message
    getStatus().then(data => {
        if (data && data.bot_state) {
            updateBotStatus(data.bot_state);
            updateOpenPosition(data.open_position || null);
            if (data.bot_state === 'RUNNING' && data.uptime_seconds > 0) {
                const startedMs = Date.now() - data.uptime_seconds * 1000;
                startUptimeTicker(new Date(startedMs).toISOString());
            }
        }
    }).catch(() => {});  // Silently ignore - WS will update anyway
});
