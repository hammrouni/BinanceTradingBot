/**
 * ui_manager.js — UI updates, formatting, and result rendering for the simulator.
 */

import { state } from './state.js';

export function fmt(n, decimals = 2) {
    if (n == null || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

export function fmtInt(n) {
    if (n == null || isNaN(parseInt(n))) return '—';
    return parseInt(n).toLocaleString('en-US');
}

export function showError(msg) {
    const errorMsg = document.getElementById('error-message');
    const errorBanner = document.getElementById('error-banner');
    if (errorMsg && errorBanner) {
        errorMsg.textContent = msg;
        errorBanner.classList.remove('hidden');
    }
}

export function hideError() {
    document.getElementById('error-banner')?.classList.add('hidden');
}

export function showStatus(msg) {
    const statusText = document.getElementById('sim-status-text');
    const statusDiv = document.getElementById('sim-status');
    if (statusText && statusDiv) {
        statusText.textContent = msg;
        statusDiv.classList.remove('hidden');
    }
}

export function hideStatus() {
    document.getElementById('sim-status')?.classList.add('hidden');
}

export function showApplyModal(position, result, onConfirm) {
    const modal = document.getElementById('apply-modal');
    if (!modal) return;

    document.getElementById('modal-entry-price').textContent = `$${fmt(position.entry_price)}`;
    document.getElementById('modal-current-sl').textContent = position.stop_loss_pct != null ? `${fmt(position.stop_loss_pct, 1)}%` : '—';
    document.getElementById('modal-new-sl').textContent = result.stop_loss_pct != null ? `${fmt(result.stop_loss_pct, 1)}%` : '—';
    
    modal.classList.remove('hidden');
    
    const confirmBtn = document.getElementById('modal-btn-confirm');
    const cancelBtn = document.getElementById('modal-btn-cancel');
    
    // Clear old listeners if any
    const newConfirm = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
    const newCancel = cancelBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);

    newConfirm.addEventListener('click', () => {
        modal.classList.add('hidden');
        onConfirm();
    });
    newCancel.addEventListener('click', () => {
        modal.classList.add('hidden');
    });
}

export function displayResults(data, updateHistoryChart) {
    const { data_points, total_combinations, results, market_history, mode } = data;
    const resultsContainer = document.getElementById('results-table-container');
    const resultsBody = document.getElementById('results-tbody');
    const resultsHead = document.getElementById('results-thead');
    const resultsSummary = document.getElementById('results-summary');

    if (market_history && market_history.length > 0 && typeof updateHistoryChart === 'function') {
        updateHistoryChart(market_history);
    }

    const topResult = results[0];
    let topSummary = '';
    let zeroHint = '';
    if (topResult) {
        const pnlColor = topResult.total_pnl >= 0 ? '#059669' : '#dc2626';
        topSummary = `<p style="margin-top:0.5rem;color:${pnlColor};"><strong>Top Result:</strong> PnL $${fmt(topResult.total_pnl)} (${fmt(topResult.total_pnl_pct)}%) | ${fmt(topResult.win_rate, 1)}% Win Rate | ${topResult.trade_count} trades</p>`;
        
        if (topResult.trade_count === 0) {
            zeroHint = `<p style="color:#b45309;margin-top:0.4rem;font-size:0.8rem;">⚠ No trades triggered for any combination. Try decreasing "Offset %" (BC) or "Oversold" (RSI), or increase "Historical Data" days.</p>`;
        }
    }
    resultsSummary.innerHTML = `
        <p><strong>${fmtInt(data_points)}</strong> data points | <strong>${fmtInt(total_combinations)}</strong> combinations tested | <strong>${data.fee_pct ?? '0.1'}%</strong> fee</p>
        ${topSummary}
        ${zeroHint}
    `;

    const hasTrailing = results.some(r => r.trailing_stop_pct !== null && r.trailing_stop_pct !== undefined);

    if (mode === 'bc') {
        resultsHead.innerHTML = _buildBcTableHeader(hasTrailing);
        resultsBody.innerHTML = results.map(row => _renderBcRow(row, hasTrailing)).join('');
    } else if (mode === 'rsi_ultra') {
        resultsHead.innerHTML = _buildUltraTableHeader(hasTrailing);
        resultsBody.innerHTML = results.map(row => _renderUltraRow(row, hasTrailing)).join('');
    } else {
        resultsHead.innerHTML = _buildRsiTableHeader(hasTrailing);
        resultsBody.innerHTML = results.map(row => _renderRsiRow(row, hasTrailing)).join('');
    }

    resultsContainer.classList.remove('hidden');
}

export function displayCurrentConfigResult(data, updateHistoryChart, historyChart) {
    const resultsSummary = document.getElementById('results-summary');
    const resultsContainer = document.getElementById('results-table-container');
    
    if (data.market_history && data.market_history.length > 0 && typeof updateHistoryChart === 'function') {
        updateHistoryChart(data.market_history);
    }

    const cfg = data.used_config || {};
    const tradeCount = data.trade_count ?? 0;
    const pnlColor = (data.total_pnl ?? 0) >= 0 ? '#059669' : '#dc2626';

    let cfgLine = '';
    if (cfg.mode === 'rsi') {
        cfgLine = `RSI Oversold: <strong>${cfg.rsi_oversold ?? '—'}</strong> | RSI Overbought: <strong>${cfg.rsi_overbought ?? '—'}</strong>`;
    } else if (cfg.mode === 'rsi_ultra') {
        cfgLine = `Ultra Period: <strong>${cfg.rsi_ultra_period ?? '—'}</strong> | Signal: <strong>${cfg.rsi_ultra_signal_period ?? '—'}</strong> | Mid: <strong>${cfg.rsi_ultra_zone_mid ?? '—'}</strong>`;
    } else {
        cfgLine = `BC Buy: <strong>$${fmt(cfg.bc_buy_price ?? 0)}</strong> | BC Sell: <strong>$${fmt(cfg.bc_sell_price ?? 0)}</strong>`;
    }
    cfgLine += ` | SL: <strong>${cfg.stop_loss_pct != null ? cfg.stop_loss_pct + '%' : '—'}</strong>`;
    cfgLine += ` | TP: <strong>${cfg.take_profit_pct != null && cfg.take_profit_pct > 0 ? cfg.take_profit_pct + '%' : '—'}</strong>`;
    cfgLine += ` | Fee: <strong>${data.fee_pct ?? 0.1}%</strong>`;
    cfgLine += ` | Data: <strong>${fmtInt(cfg.data_points ?? 0)}</strong> candles`;

    const zeroHint = tradeCount === 0
        ? `<p style="color:#b45309;margin-top:0.4rem;">⚠ No trades triggered. Try increasing Historical Data days, or check that your RSI/price thresholds match the recent market range.</p>`
        : '';

    resultsSummary.innerHTML = `
        <p style="font-size:0.8rem;color:#64748b;margin-bottom:0.4rem;">${cfgLine}</p>
        <p style="color:${pnlColor};">
            PnL: <strong>$${fmt(data.total_pnl ?? 0)}</strong> (${fmt(data.total_pnl_pct ?? 0)}%) &nbsp;|&nbsp;
            Trades: <strong>${tradeCount}</strong> &nbsp;|&nbsp;
            Win Rate: <strong>${fmt(data.win_rate ?? 0, 1)}%</strong> &nbsp;|&nbsp;
            Max DD: <strong>${fmt(data.max_drawdown_pct ?? 0, 1)}%</strong>
        </p>
        ${zeroHint}
    `;

    resultsContainer.classList.add('hidden');
}

// ── Private row builders ───────────────────────────────────────────────────

function _buildRsiTableHeader(hasTrailing) {
    return `<tr>
        <th>Rank</th>
        <th style="text-align:center;">RSI OS</th>
        <th style="text-align:center;">RSI OB</th>
        <th style="text-align:center;">SL%</th>
        <th style="text-align:center;">TP%</th>
        ${hasTrailing ? '<th style="text-align:center;">Trail%</th>' : ''}
        <th style="text-align:right;">PnL $</th>
        <th style="text-align:right;">PnL %</th>
        <th style="text-align:center;">Trades</th>
        <th style="text-align:center;">Win %</th>
        <th style="text-align:right;">Max DD%</th>
        <th style="text-align:center;">Actions</th>
    </tr>`;
}

function _buildBcTableHeader(hasTrailing) {
    return `<tr>
        <th>Rank</th>
        <th style="text-align:center;">Buy Off%</th>
        <th style="text-align:center;">Sell Off%</th>
        <th style="text-align:right;">Buy $</th>
        <th style="text-align:right;">Sell $</th>
        <th style="text-align:center;">SL%</th>
        <th style="text-align:center;">TP%</th>
        ${hasTrailing ? '<th style="text-align:center;">Trail%</th>' : ''}
        <th style="text-align:right;">PnL $</th>
        <th style="text-align:right;">PnL %</th>
        <th style="text-align:center;">Trades</th>
        <th style="text-align:center;">Win %</th>
        <th style="text-align:right;">Max DD%</th>
        <th style="text-align:center;">Actions</th>
    </tr>`;
}

function _renderRsiRow(row, hasTrailing) {
    const pnlClass = row.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
    const rowJson = JSON.stringify(row).replace(/"/g, '&quot;');
    return `<tr>
        <td>#${row.rank}</td>
        <td style="text-align:center;">${row.rsi_oversold !== null ? row.rsi_oversold : '—'}</td>
        <td style="text-align:center;">${row.rsi_overbought !== null ? row.rsi_overbought : '—'}</td>
        <td style="text-align:center;">${row.stop_loss_pct !== null ? fmt(row.stop_loss_pct, 1) : '—'}</td>
        <td style="text-align:center;">${row.take_profit_pct !== null ? fmt(row.take_profit_pct, 1) : '—'}</td>
        ${hasTrailing ? `<td style="text-align:center;">${row.trailing_stop_pct !== null ? fmt(row.trailing_stop_pct, 1) : '—'}</td>` : ''}
        <td style="text-align:right;" class="${pnlClass}">$${fmt(row.total_pnl)}</td>
        <td style="text-align:right;" class="${pnlClass}">${fmt(row.total_pnl_pct)}%</td>
        <td style="text-align:center;">${row.trade_count}</td>
        <td style="text-align:center;">${fmt(row.win_rate, 1)}%</td>
        <td style="text-align:right;">${fmt(row.max_drawdown_pct, 1)}%</td>
        <td style="text-align:center; white-space:nowrap;">
            <button class="btn-view" onclick="window.viewSimulationOnChart(event, ${rowJson})">Chart</button>
            <button class="btn-apply" onclick="window.applyConfig(${rowJson})">Apply</button>
        </td>
    </tr>`;
}

function _renderBcRow(row, hasTrailing) {
    const pnlClass = row.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
    const rowJson = JSON.stringify(row).replace(/"/g, '&quot;');
    return `<tr>
        <td>#${row.rank}</td>
        <td style="text-align:center;">${fmt(row.bc_buy_offset_pct, 1)}%</td>
        <td style="text-align:center;">${fmt(row.bc_sell_offset_pct, 1)}%</td>
        <td style="text-align:right;">$${fmt(row.bc_buy_price)}</td>
        <td style="text-align:right;">$${fmt(row.bc_sell_price)}</td>
        <td style="text-align:center;">${row.stop_loss_pct !== null ? fmt(row.stop_loss_pct, 1) : '—'}</td>
        <td style="text-align:center;">${row.take_profit_pct !== null ? fmt(row.take_profit_pct, 1) : '—'}</td>
        ${hasTrailing ? `<td style="text-align:center;">${row.trailing_stop_pct !== null ? fmt(row.trailing_stop_pct, 1) : '—'}</td>` : ''}
        <td style="text-align:right;" class="${pnlClass}">$${fmt(row.total_pnl)}</td>
        <td style="text-align:right;" class="${pnlClass}">${fmt(row.total_pnl_pct)}%</td>
        <td style="text-align:center;">${row.trade_count}</td>
        <td style="text-align:center;">${fmt(row.win_rate, 1)}%</td>
        <td style="text-align:right;">${fmt(row.max_drawdown_pct, 1)}%</td>
        <td style="text-align:center; white-space:nowrap;">
            <button class="btn-view" onclick="window.viewSimulationOnChart(event, ${rowJson})">Chart</button>
            <button class="btn-apply" onclick="window.applyConfig(${rowJson})">Apply</button>
        </td>
    </tr>`;
}

function _buildUltraTableHeader(hasTrailing) {
    return `<tr>
        <th>Rank</th>
        <th style="text-align:center;">Period</th>
        <th style="text-align:center;">Signal</th>
        <th style="text-align:center;">Zone Mid</th>
        <th style="text-align:center;">SL%</th>
        <th style="text-align:center;">TP%</th>
        ${hasTrailing ? '<th style="text-align:center;">Trail%</th>' : ''}
        <th style="text-align:right;">PnL $</th>
        <th style="text-align:right;">PnL %</th>
        <th style="text-align:center;">Trades</th>
        <th style="text-align:center;">Win %</th>
        <th style="text-align:right;">Max DD%</th>
        <th style="text-align:center;">Actions</th>
    </tr>`;
}

function _renderUltraRow(row, hasTrailing) {
    const pnlClass = row.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
    const rowJson = JSON.stringify(row).replace(/"/g, '&quot;');
    return `<tr>
        <td>#${row.rank}</td>
        <td style="text-align:center;">${row.rsi_ultra_period ?? '—'}</td>
        <td style="text-align:center;">${row.rsi_ultra_signal_period ?? '—'}</td>
        <td style="text-align:center;">${row.rsi_ultra_zone_mid ?? '—'}</td>
        <td style="text-align:center;">${row.stop_loss_pct !== null ? fmt(row.stop_loss_pct, 1) : '—'}</td>
        <td style="text-align:center;">${row.take_profit_pct !== null ? fmt(row.take_profit_pct, 1) : '—'}</td>
        ${hasTrailing ? `<td style="text-align:center;">${row.trailing_stop_pct !== null ? fmt(row.trailing_stop_pct, 1) : '—'}</td>` : ''}
        <td style="text-align:right;" class="${pnlClass}">$${fmt(row.total_pnl)}</td>
        <td style="text-align:right;" class="${pnlClass}">${fmt(row.total_pnl_pct)}%</td>
        <td style="text-align:center;">${row.trade_count}</td>
        <td style="text-align:center;">${fmt(row.win_rate, 1)}%</td>
        <td style="text-align:right;">${fmt(row.max_drawdown_pct, 1)}%</td>
        <td style="text-align:center; white-space:nowrap;">
            <button class="btn-view" onclick="window.viewSimulationOnChart(event, ${rowJson})">Chart</button>
            <button class="btn-apply" onclick="window.applyConfig(${rowJson})">Apply</button>
        </td>
    </tr>`;
}
