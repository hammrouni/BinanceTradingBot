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

    if (typeof updateRsiChart === 'function') updateRsiChart(rsi, timestamp);
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
    
    if (!prodContainer || !tradingContainer) return;

    const env = _currentConfig?.trading_env || 'testnet';

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

    // 3. Helper to render a specific balance set
    const _render = (container, set) => {
        if (!set || Object.keys(set).length === 0) {
            if (!container.querySelector('.wallet-asset-row')) {
                container.innerHTML = '<div class="wallet-empty">Refreshing...</div>';
            }
            return;
        }

        let html = '';
        for (const [asset, bal] of Object.entries(set)) {
            const total = bal.free + bal.locked;
            html += `
                <div class="wallet-asset-row">
                    <div class="asset-info">
                        <span class="asset-name">${asset}</span>
                        <span class="asset-total">${total.toLocaleString('en-US', { minimumFractionDigits: asset === 'USDT' ? 2 : 6, maximumFractionDigits: asset === 'USDT' ? 2 : 6 })}</span>
                    </div>
                    <div class="asset-details">
                        <span class="asset-free">Available: ${bal.free.toLocaleString('en-US', { minimumFractionDigits: asset === 'USDT' ? 2 : 6, maximumFractionDigits: asset === 'USDT' ? 2 : 6 })}</span>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    };

    // 4. Render both
    if (balances.prod)    _render(prodContainer,    balances.prod);
    if (balances.trading) _render(tradingContainer, balances.trading);
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
                    
                    addTradeRow(t, isTest);
                    updateTradeSummary(t, isTest);

                    if (t.direction === 'buy') {
                        updateOpenPosition({
                            pair: t.pair, quantity: t.quantity,
                            entry_price: t.price, stop_loss_price: null,
                        });
                        if (typeof markBuySignal === 'function') markBuySignal(t.price, isTest);
                    } else if (t.direction === 'sell') {
                        updateOpenPosition(null);
                        if (typeof markSellSignal === 'function') markSellSignal(t.price, isTest);
                    }
                    break;
                }
                case 'rsi_history': {
                    if (typeof setRsiHistory === 'function') {
                        setRsiHistory(msg.payload);
                    }
                    _rsiHistoryLoaded = true;
                    _replayTradeMarkers();
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

// ─── Config panel ─────────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const data = await getConfig();
        _currentConfig = data;
        document.getElementById('trading-pair').value  = data.trading_pair;
        document.getElementById('trade-amount').value  = data.trade_amount_usd;
        document.getElementById('rsi-oversold').value = data.rsi_oversold;
        document.getElementById('rsi-overbought').value = data.rsi_overbought;
        document.getElementById('stop-loss-pct').value = data.stop_loss_pct;
        
        updateLegendLabels(data.rsi_oversold, data.rsi_overbought);

        if (typeof updateChartThresholds === 'function')
            updateChartThresholds(data.rsi_oversold, data.rsi_overbought);
    } catch (e) {
        console.error('Failed to load config:', e);
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

    if (isNaN(data.trade_amount_usd) || data.trade_amount_usd <= 0)
        errors.trade_amount_usd = 'Must be > 0';
    if (isNaN(data.rsi_oversold) || data.rsi_oversold < 1 || data.rsi_oversold > 100)
        errors.rsi_oversold = 'Must be 1–100';
    if (isNaN(data.rsi_overbought) || data.rsi_overbought < 1 || data.rsi_overbought > 100)
        errors.rsi_overbought = 'Must be 1–100';
    if (isNaN(data.stop_loss_pct) || data.stop_loss_pct < 0.1 || data.stop_loss_pct > 50)
        errors.stop_loss_pct = 'Must be 0.1–50';
    return errors;
}

function bindConfigForm() {
    const form = document.getElementById('config-form');
    if (!form) return;

    // Mark inputs dirty on change
    form.querySelectorAll('input').forEach(input =>
        input.addEventListener('input', () => input.classList.add('dirty'))
    );

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = {
            trading_pair:     document.getElementById('trading-pair').value.trim().toUpperCase(),
            trade_amount_usd: parseFloat(document.getElementById('trade-amount').value),
            rsi_oversold:     parseInt(document.getElementById('rsi-oversold').value, 10),
            rsi_overbought:   parseInt(document.getElementById('rsi-overbought').value, 10),
            stop_loss_pct:    parseFloat(document.getElementById('stop-loss-pct').value),
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
            _currentConfig = data;
            form.querySelectorAll('input').forEach(i => i.classList.remove('dirty'));
            statusEl.textContent = '✓ Configuration saved';
            statusEl.className   = 'status-success';
            setTimeout(() => { statusEl.textContent = ''; }, 3500);
            
            updateLegendLabels(data.rsi_oversold, data.rsi_overbought);

            if (typeof updateChartThresholds === 'function')
                updateChartThresholds(data.rsi_oversold, data.rsi_overbought);
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
        const sl = pos.stop_loss_price;
        if (sl != null) {
            stopLossDisplay = `$${Number(sl).toFixed(2)}`;
        } else if (_currentConfig.stop_loss_pct && pos.entry_price) {
            const computed = pos.entry_price * (1 - _currentConfig.stop_loss_pct / 100);
            stopLossDisplay = `$${computed.toFixed(2)}`;
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
    } else {
        _openPosition = null;
        card.classList.add('hidden');
        document.getElementById('header-active-pnl-pill')?.classList.add('hidden');
    }
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

    const dt    = trade.executed_at ? formatTradeTime(new Date(trade.executed_at)) : '—';
    const price = trade.entry_price ?? trade.price;
    const side  = trade.direction === 'buy'
        ? '<span class="side-buy">BUY</span>'
        : '<span class="side-sell">SELL</span>';

    let pnlCell;
    if (trade.direction === 'buy') {
        pnlCell = '<td class="pnl-neutral">—</td>';
    } else if (trade.pnl_usd == null) {
        pnlCell = '<td class="pnl-neutral">—</td>';
    } else {
        const cls  = trade.pnl_usd >= 0 ? 'pnl-positive' : 'pnl-negative';
        const sign = trade.pnl_usd >= 0 ? '+' : '';
        pnlCell = `<td class="${cls}">${sign}$${trade.pnl_usd.toFixed(2)}</td>`;
    }

    tr.innerHTML = `
        <td title="${trade.executed_at || ''}">${dt}</td>
        <td>${side}</td>
        <td>$${trade.amount_usd?.toFixed(2) || '—'}</td>
        <td>$${price?.toFixed(2) || '—'}</td>
        <td>${trade.quantity?.toFixed(6) || '—'}</td>
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
    trades.forEach(t => {
        tbody.appendChild(renderTradeRow(t));
        if (t.direction === 'sell' && t.pnl_usd != null) totalPnl += t.pnl_usd;
    });

    const summaryEl = document.getElementById(summaryId);
    const countEl   = document.getElementById(countId);
    const pnlEl     = document.getElementById(pnlId);
    
    if (summaryEl) summaryEl.classList.remove('hidden');
    if (countEl)   countEl.textContent = `${trades.length} trade${trades.length !== 1 ? 's' : ''}`;
    if (pnlEl) {
        const sign = totalPnl >= 0 ? '+' : '';
        const value = `PnL: ${sign}$${totalPnl.toFixed(2)}`;
        const headerValue = `${sign}$${totalPnl.toFixed(2)}`;
        const className = totalPnl > 0 ? 'pnl-positive' : totalPnl < 0 ? 'pnl-negative' : 'pnl-neutral';

        pnlEl.textContent = value;
        pnlEl.className   = className;

        const headerId = isTest ? 'header-test-pnl' : 'header-prod-pnl';
        const headerPnl = document.getElementById(headerId);
        if (headerPnl) {
            headerPnl.textContent = headerValue;
            headerPnl.className   = className;
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
        if (t.executed_at) markSignalAtTime(t.executed_at, t.direction, t.entry_price || t.price, false);
    });
    _loadedTestTrades.forEach(t => {
        if (t.executed_at) markSignalAtTime(t.executed_at, t.direction, t.entry_price || t.price, true);
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
    
    document.getElementById('btn-refresh-prod')?.addEventListener('click', () => loadTradeHistory());
    document.getElementById('btn-refresh-test')?.addEventListener('click', () => loadTradeHistory());
    
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
