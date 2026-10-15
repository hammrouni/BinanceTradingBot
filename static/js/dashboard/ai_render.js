import { escapeHtml as esc, safeNumber } from '../utils/escape.js';

export function fmtPrice(p) {
    return p ? '$' + Number(p).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
}

export function buildAiResultHtml(data) {
    const signalClass = { BUY: 'ai-signal-buy', SELL: 'ai-signal-sell', HOLD: 'ai-signal-hold' }[data.signal] ?? 'ai-signal-hold';
    const confBar     = `<div class="ai-conf-bar"><div class="ai-conf-fill" style="width:${safeNumber(data.confidence)}%"></div></div>`;

    const risks = (data.risk_notes ?? []).length
        ? `<ul class="ai-risks">${data.risk_notes.map(r => `<li>${esc(r)}</li>`).join('')}</ul>`
        : '<p class="ai-no-risks">No significant risks flagged.</p>';

    // Config advice section
    const cfgAdvice = data.config_advice ?? {};
    let cfgHtml = '';
    if (cfgAdvice.should_change && (cfgAdvice.changes ?? []).length) {
        const rows = cfgAdvice.changes.map(c => `
            <div class="ai-cfg-change">
                <span class="ai-cfg-field">${esc(c.field)}</span>
                <span class="ai-cfg-arrow">${esc(c.current)} → <strong>${esc(c.suggested)}</strong></span>
                <span class="ai-cfg-reason">${esc(c.reason)}</span>
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
        ? `<div class="ai-action-box"><span class="ai-action-icon">→</span> ${esc(data.action_advice)}</div>`
        : '';

    return `
        <div class="ai-signal-row">
            <span class="ai-signal-badge ${signalClass}">${esc(data.signal)}</span>
            <span class="ai-confidence-label">Confidence: <strong>${safeNumber(data.confidence)}%</strong></span>
        </div>
        ${confBar}
        ${actionHtml}
        <p class="ai-reasoning">${esc(data.reasoning)}</p>
        <div class="ai-levels">
            <div class="ai-level-item"><label>Suggested TP</label><span class="ai-tp">${fmtPrice(data.suggested_tp)}</span></div>
            <div class="ai-level-item"><label>Suggested SL</label><span class="ai-sl">${fmtPrice(data.suggested_sl)}</span></div>
        </div>
        <div class="ai-section ai-risk-section">
            <strong class="ai-section-title">⚠ Risk Notes</strong>
            ${risks}
        </div>
        ${cfgHtml}
        <p class="ai-footer">Powered by ${esc(data.agent ?? 'AI')} · ${new Date().toLocaleTimeString()}</p>
    `;
}

export function buildAiErrorHtml(msg) {
    return `<p class="ai-error">⚠ ${esc(msg)}</p>`;
}

