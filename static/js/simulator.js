/**
 * Simulator page: run parameter backtests and apply best config
 */

const form = document.getElementById('simulator-form');
const statusDiv = document.getElementById('sim-status');
const statusText = document.getElementById('sim-status-text');
const resultsContainer = document.getElementById('results-table-container');
const resultsSummary = document.getElementById('results-summary');
const resultsBody = document.getElementById('results-tbody');
const dismissErrorBtn = document.getElementById('btn-dismiss-error');
const errorBanner = document.getElementById('error-banner');
const errorMsg = document.getElementById('error-message');

// Error banner handling
function showError(msg) {
    errorMsg.textContent = msg;
    errorBanner.classList.remove('hidden');
}

function hideError() {
    errorBanner.classList.add('hidden');
}

dismissErrorBtn.addEventListener('click', hideError);

// Show status message
function showStatus(msg) {
    statusText.textContent = msg;
    statusDiv.classList.remove('hidden');
}

function hideStatus() {
    statusDiv.classList.add('hidden');
}

// Format numbers
function fmt(n, decimals = 2) {
    return parseFloat(n).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

function fmtInt(n) {
    return parseInt(n).toLocaleString('en-US');
}

// Get form values
function getFormValues() {
    const mode = document.getElementById('mode').value;
    const initialBalance = parseFloat(document.getElementById('initial-balance').value);
    const tradeAmount = parseFloat(document.getElementById('trade-amount').value);
    const historicalDays = parseInt(document.getElementById('historical-days').value);

    const rsiOBDisabled = document.getElementById('rsi-ob-disable').checked;
    const rsiObRange = rsiOBDisabled ? null : [
        parseFloat(document.getElementById('rsi-ob-min').value),
        parseFloat(document.getElementById('rsi-ob-max').value),
        parseFloat(document.getElementById('rsi-ob-step').value),
    ];

    const tpDisabled = document.getElementById('tp-disable').checked;
    const tpRange = tpDisabled ? null : [
        parseFloat(document.getElementById('tp-min').value),
        parseFloat(document.getElementById('tp-max').value),
        parseFloat(document.getElementById('tp-step').value),
    ];

    return {
        mode,
        initial_balance: initialBalance,
        trade_amount_usd: tradeAmount,
        historical_days: historicalDays,
        rsi_oversold_range: [
            parseFloat(document.getElementById('rsi-os-min').value),
            parseFloat(document.getElementById('rsi-os-max').value),
            parseFloat(document.getElementById('rsi-os-step').value),
        ],
        rsi_overbought_range: rsiObRange,
        stop_loss_range: [
            parseFloat(document.getElementById('sl-min').value),
            parseFloat(document.getElementById('sl-max').value),
            parseFloat(document.getElementById('sl-step').value),
        ],
        take_profit_range: tpRange,
    };
}

// Load historical data only (for chart display)
async function loadHistoricalData() {
    hideError();
    const btn = document.getElementById('btn-run-simulation');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    showStatus('Loading historical data...');

    try {
        const params = getFormValues();
        const response = await fetch('/api/v1/simulator/data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });

        const data = await response.json();

        if (data.status === 'error') {
            showError(data.message || 'Failed to load data');
            hideStatus();
            return;
        }

        hideStatus();
        
        // Update chart with historical data
        if (data.market_history && data.market_history.length > 0) {
            if (typeof updateHistoryChart === 'function') {
                updateHistoryChart(data.market_history);
            }
        }
        
        // Update summary info
        const summaryDiv = document.getElementById('results-summary');
        if (summaryDiv && data.data_points) {
            summaryDiv.innerHTML = '<p><strong>' + fmtInt(data.data_points) + '</strong> data points loaded. Click "Run Simulation" to test parameters.</p>';
        }
    } catch (err) {
        showError(`Request failed: ${err.message}`);
        hideStatus();
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Run simulation (full backtest)
async function runSimulation() {
    hideError();
    resultsContainer.classList.add('hidden');
    resultsBody.innerHTML = '';

    const btn = document.getElementById('btn-run-simulation');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    showStatus('Running simulation...');

    try {
        const params = getFormValues();
        const response = await fetch('/api/v1/simulator/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });

        const data = await response.json();

        if (data.status === 'error') {
            showError(data.message || 'Simulation failed');
            hideStatus();
            return;
        }

        // Display results
        hideStatus();
        displayResults(data);
    } catch (err) {
        showError(`Request failed: ${err.message}`);
        hideStatus();
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await runSimulation();
});

// Load data on page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadHistoricalData();
});

// Re-load data when historical days dropdown changes (but don't run simulation)
const historicalDaysSelect = document.getElementById('historical-days');
if (historicalDaysSelect) {
    historicalDaysSelect.addEventListener('change', async () => {
        await loadHistoricalData();
    });
}

function displayResults(data) {
    const { data_points, total_combinations, results, market_history } = data;

    // Update chart with market history
    if (market_history && market_history.length > 0) {
        if (typeof updateHistoryChart === 'function') {
            updateHistoryChart(market_history);
        }
    }

    // Update summary
    resultsSummary.innerHTML = `
        <p><strong>${fmtInt(data_points)}</strong> data points | <strong>${fmtInt(total_combinations)}</strong> combinations tested</p>
        ${results.length > 0 ? `<p style="margin-top: 0.5rem; color: #059669;"><strong>Top Result:</strong> PnL $${fmt(results[0].total_pnl)} (${fmt(results[0].total_pnl_pct)}%) | ${fmt(results[0].win_rate)}% Win Rate | ${results[0].trade_count} trades</p>` : ''}
    `;

    // Render table
    resultsBody.innerHTML = results.map((row) => {
        const pnlClass = row.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        return `
            <tr>
                <td>#${row.rank}</td>
                <td style="text-align: center;">${row.rsi_oversold !== null ? row.rsi_oversold : '—'}</td>
                <td style="text-align: center;">${row.rsi_overbought !== null ? row.rsi_overbought : '—'}</td>
                <td style="text-align: center;">${row.stop_loss_pct !== null ? fmt(row.stop_loss_pct, 1) : '—'}</td>
                <td style="text-align: center;">${row.take_profit_pct !== null ? fmt(row.take_profit_pct, 1) : '—'}</td>
                <td style="text-align: right;" class="${pnlClass}">$${fmt(row.total_pnl)}</td>
                <td style="text-align: right;" class="${pnlClass}">${fmt(row.total_pnl_pct)}%</td>
                <td style="text-align: center;">${row.trade_count}</td>
                <td style="text-align: center;">${fmt(row.win_rate, 1)}%</td>
                <td style="text-align: right;">${fmt(row.max_drawdown_pct, 1)}%</td>
                <td style="text-align: center;">
                    <button class="btn-apply" onclick="applyConfig(${JSON.stringify(row).replace(/"/g, '&quot;')})">Apply</button>
                </td>
            </tr>
        `;
    }).join('');

    resultsContainer.classList.remove('hidden');
}

// D1: Check for open position before applying config, then show confirmation modal (C3)
async function applyConfig(result) {
    try {
        // D1: fetch bot status to detect open position
        const statusResp = await fetch('/api/v1/status');
        const statusData = await statusResp.json();

        const position = statusData?.data?.position ?? statusData?.position ?? null;

        if (position && position.entry_price) {
            // Show open-position warning modal
            document.getElementById('modal-entry-price').textContent = `$${fmt(position.entry_price)}`;

            const currentSL = position.stop_loss_pct != null
                ? `${fmt(position.stop_loss_pct, 1)}%`
                : '—';
            const newSL = result.stop_loss_pct != null
                ? `${fmt(result.stop_loss_pct, 1)}%`
                : '—';
            document.getElementById('modal-current-sl').textContent = currentSL;
            document.getElementById('modal-new-sl').textContent = newSL;

            document.getElementById('apply-modal').classList.remove('hidden');

            // Store result for deferred apply on confirm
            window._pendingApplyResult = result;
        } else {
            // C3: no open position — show simple confirmation dialog
            const confirmed = confirm(
                `Apply this configuration?\n\nRSI OS: ${result.rsi_oversold ?? '—'} | RSI OB: ${result.rsi_overbought ?? '—'}\nSL: ${result.stop_loss_pct != null ? result.stop_loss_pct + '%' : '—'} | TP: ${result.take_profit_pct != null ? result.take_profit_pct + '%' : '—'}`
            );
            if (!confirmed) return;
            await doApplyConfig(result);
        }
    } catch (err) {
        showError(`Failed to check bot status: ${err.message}`);
    }
}

// Modal confirm/cancel handlers
document.getElementById('modal-btn-confirm').addEventListener('click', async () => {
    document.getElementById('apply-modal').classList.add('hidden');
    if (window._pendingApplyResult) {
        await doApplyConfig(window._pendingApplyResult);
        window._pendingApplyResult = null;
    }
});

document.getElementById('modal-btn-cancel').addEventListener('click', () => {
    document.getElementById('apply-modal').classList.add('hidden');
    window._pendingApplyResult = null;
});

async function doApplyConfig(result) {
    try {
        // Fetch current config to preserve unchanged fields
        const configResp = await fetch('/api/v1/config');
        const configData = await configResp.json();

        if (configData.status === 'error') {
            showError('Failed to fetch current config');
            return;
        }

        const currentConfig = configData.data;

        // H5: spread-merge current config, overwrite only simulator fields, drop trading_env
        const newConfig = {
            ...currentConfig,
            rsi_oversold: result.rsi_oversold,
            rsi_overbought: result.rsi_overbought,
            stop_loss_pct: result.stop_loss_pct,
            take_profit_pct: result.take_profit_pct,
        };
        delete newConfig.trading_env;

        const response = await fetch('/api/v1/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newConfig),
        });

        const data = await response.json();

        if (data.status === 'error') {
            showError(`Failed to apply config: ${data.message}`);
            return;
        }

        // Redirect to dashboard
        window.location.href = '/';
    } catch (err) {
        showError(`Failed to apply config: ${err.message}`);
    }
}
