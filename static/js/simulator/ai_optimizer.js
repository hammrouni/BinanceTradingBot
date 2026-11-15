/**
 * ai_optimizer.js — "AI Optimizer" card: starts the background job, polls it, shows the ranking.
 * Everything that comes from the AI or the web goes through escapeHtml().
 */
import { escapeHtml as esc } from '../utils/escape.js';

const POLL_MS = 3000;
const $ = id => document.getElementById(id);

const MODE_LABEL = { RSI: 'RSI', RSI_ULTRA: 'RSI Ultra', BC: 'BC' };
const VERDICT_STYLE = {
    CANDIDATE: 'background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;',
    NO_EDGE: 'background:#fef2f2;color:#991b1b;border:1px solid #fecaca;',
};

function pct(v) {
    if (v === null || v === undefined) return '—';
    const n = Number(v);
    return `<span style="color:${n > 0 ? '#16a34a' : n < 0 ? '#dc2626' : '#64748b'}">${n > 0 ? '+' : ''}${n.toFixed(2)}%</span>`;
}

function paramsText(r) {
    const parts = [];
    if (r.strategy === 'RSI') parts.push(`RSI ${r.rsi_oversold}/${r.rsi_overbought}`);
    if (r.strategy === 'RSI_ULTRA') parts.push(`Ultra ${r.rsi_ultra_period}/${r.rsi_ultra_signal_period} mid ${r.rsi_ultra_zone_mid}`);
    if (r.strategy === 'BC') parts.push(`BC buy −${r.bc_buy_offset_pct}% / sell +${r.bc_sell_offset_pct}%`);
    parts.push(`SL ${r.stop_loss_pct}%`, `TP ${r.take_profit_pct}%`);
    if (r.trailing_stop_pct != null) parts.push(`trail ${r.trailing_stop_pct}%`);
    if (r.ema_fast_period != null) parts.push(`EMA ${r.ema_fast_period}>${r.ema_slow_period}`);
    if (r.bear_trend_candles != null) parts.push(`no-buy if −${r.bear_trend_pct}%/${r.bear_trend_candles}c`);
    if (r.ma_filter_period != null) parts.push(`below MA${r.ma_filter_period}`);
    if (r.price_bounce_ticks != null) parts.push(`bounce ${r.price_bounce_ticks}`);
    return parts.join(' · ');
}

function renderResult(res) {
    const v = res.verdict;
    const m = res.market || {};
    const ex = res.explanation;
    const rows = (res.top || []).map((r, i) => `
        <tr style="border-top:1px solid #e2e8f0;">
            <td style="padding:0.35rem;">${i + 1}</td>
            <td style="padding:0.35rem;"><b>${esc(MODE_LABEL[r.strategy] || r.strategy)}</b>${r.source === 'web-ai' ? ' <span title="Proposed by the AI" style="font-size:0.7rem;background:#e0f2fe;color:#0369a1;border-radius:4px;padding:0 4px;">AI</span>' : ''}
                <div style="font-size:0.75rem;color:#64748b;">${esc(paramsText(r))}</div>
                ${r.note ? `<div style="font-size:0.7rem;color:#94a3b8;">${esc(r.note)}</div>` : ''}</td>
            <td style="padding:0.35rem;text-align:right;">${pct(r.train_mean_pct)}</td>
            <td style="padding:0.35rem;text-align:right;">${esc(r.train_profitable_pct)}%</td>
            <td style="padding:0.35rem;text-align:right;">${pct(r.holdout_mean_pct)}</td>
            <td style="padding:0.35rem;text-align:right;">${esc(r.train_trades)}/${esc(r.holdout_trades)}</td>
            <td style="padding:0.35rem;text-align:right;"><button class="btn-apply" data-rank="${i}">Apply</button></td>
        </tr>`).join('');

    const risks = ex && Array.isArray(ex.risks) && ex.risks.length
        ? `<ul style="margin:0.25rem 0 0 1rem;padding:0;">${ex.risks.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
    const sources = (res.sources || []).length
        ? `<details style="margin-top:0.5rem;"><summary style="cursor:pointer;color:#64748b;">Web sources used (${res.sources.length})</summary>
            <ul style="margin:0.25rem 0 0 1rem;padding:0;font-size:0.75rem;color:#64748b;">${res.sources.map(s => `<li>${esc(s.title)} <i>(${esc(s.source)})</i></li>`).join('')}</ul></details>` : '';

    $('ai-result').innerHTML = `
        <div style="${VERDICT_STYLE[v] || VERDICT_STYLE.NO_EDGE}border-radius:6px;padding:0.6rem 0.8rem;">
            <b>${v === 'CANDIDATE' ? 'Candidate found' : 'No reliable edge found'}</b> — ${esc(res.verdict_text)}
        </div>
        <div style="margin-top:0.5rem;color:#475569;">
            ${esc(res.pair)}, ${esc(m.days)} days, price ${pct(m.price_change_pct)}, avg daily range ${esc(m.avg_daily_range_pct)}%.
            Tested ${esc(res.tested)} settings (${esc(res.ai_note || 'no AI ideas')}) on ${esc(res.windows)} day-windows, fee ${esc(res.fee_pct)}%/side.
            Average of all settings: ${pct(res.baseline_mean_pct)} per window.
        </div>
        ${ex ? `<div style="margin-top:0.5rem;"><b>AI summary:</b> ${esc(ex.summary)}<br><b>Next step:</b> ${esc(ex.recommendation)}${risks}</div>` : ''}
        ${res.insights ? `<div style="margin-top:0.5rem;color:#475569;"><b>Research notes:</b> ${esc(res.insights)}</div>` : ''}
        ${sources}
        <div style="overflow-x:auto;margin-top:0.75rem;">
            <table style="width:100%;font-size:0.8rem;border-collapse:collapse;">
                <thead style="background:#f8fafc;"><tr>
                    <th style="padding:0.35rem;text-align:left;">#</th><th style="padding:0.35rem;text-align:left;">Setting</th>
                    <th style="padding:0.35rem;text-align:right;" title="Mean return per day-window on the early windows, after fees, as % of the trade size">Early</th>
                    <th style="padding:0.35rem;text-align:right;" title="Share of early windows with a profit">Win days</th>
                    <th style="padding:0.35rem;text-align:right;" title="Mean return on later windows the ranking never saw">Unseen</th>
                    <th style="padding:0.35rem;text-align:right;" title="Trades early / unseen">Trades</th><th></th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
        <div style="font-size:0.72rem;color:#94a3b8;margin-top:0.5rem;">Returns are % of the trade size per day-window, after fees. Past results do not guarantee future profit; forward-test on testnet before using real money.</div>`;

    $('ai-result').querySelectorAll('button[data-rank]').forEach(btn => {
        btn.addEventListener('click', () => window.applyConfig(res.top[Number(btn.dataset.rank)]));
    });
    $('ai-result').classList.remove('hidden');
}

function setStatus(html, error = false) {
    const el = $('ai-status');
    el.innerHTML = html;
    el.style.color = error ? '#b91c1c' : '#334155';
    el.classList.remove('hidden');
}

async function poll(jobId) {
    for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const resp = await fetch(`/api/v1/simulator/ai-optimize/${encodeURIComponent(jobId)}`);
        const body = await resp.json();
        if (body.status !== 'ok') throw new Error(body.message || 'Job lost');
        const job = body.data;
        if (job.state === 'running') {
            setStatus(`⏳ ${esc(job.phase)}${job.progress ? ` (${esc(job.progress)}%)` : ''}…`);
        } else if (job.state === 'error') {
            throw new Error(job.error || 'Optimizer failed');
        } else {
            const warn = (job.warnings || []).map(w => `<div style="color:#b45309;">⚠ ${esc(w)}</div>`).join('');
            setStatus(`✔ Done.${warn}`);
            renderResult(job.result);
            return;
        }
    }
}

async function run() {
    const btn = $('btn-ai-run');
    const modes = [['ai-mode-rsi', 'rsi'], ['ai-mode-ultra', 'rsi_ultra'], ['ai-mode-bc', 'bc']]
        .filter(([id]) => $(id).checked).map(([, m]) => m);
    if (!modes.length) { setStatus('Pick at least one strategy.', true); return; }

    btn.disabled = true;
    $('ai-result').classList.add('hidden');
    setStatus('⏳ Starting…');
    try {
        const resp = await fetch('/api/v1/simulator/ai-optimize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                days: Number($('ai-days').value),
                fee_pct: Number($('fee-pct').value),
                trade_amount_usd: Number($('trade-amount').value),
                modes,
                use_web: $('ai-web').checked,
                use_llm: $('ai-llm').checked,
            }),
        });
        const body = await resp.json();
        if (!resp.ok || body.status !== 'ok') {
            throw new Error(body.message || (body.detail && JSON.stringify(body.detail)) || `HTTP ${resp.status}`);
        }
        await poll(body.job_id);
    } catch (e) {
        setStatus(`✖ ${esc(e.message)}`, true);
    } finally {
        btn.disabled = false;
    }
}

$('btn-ai-run')?.addEventListener('click', run);
