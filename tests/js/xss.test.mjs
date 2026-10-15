// Run with: node --test tests/js/xss.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { escapeHtml, safeNumber } from '../../static/js/utils/escape.js';
import { buildAiResultHtml, buildAiErrorHtml } from '../../static/js/dashboard/ai_render.js';
import { renderAgentResult } from '../../static/js/agents/micro_agents.js';

const PAYLOAD = '<img src=x onerror=alert(1)>';
const evil = () => ({
    signal: PAYLOAD, confidence: PAYLOAD, reasoning: PAYLOAD, action_advice: PAYLOAD, agent: PAYLOAD,
    risk_notes: [PAYLOAD],
    config_advice: { should_change: true, changes: [{ field: PAYLOAD, current: PAYLOAD, suggested: PAYLOAD, reason: PAYLOAD }] },
    suggested_tp: PAYLOAD, suggested_sl: PAYLOAD,
});

test('escapeHtml escapes markup and handles null', () => {
    assert.equal(escapeHtml(PAYLOAD), '&lt;img src=x onerror=alert(1)&gt;');
    assert.equal(escapeHtml(`"'&`), '&quot;&#39;&amp;');
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(5), '5');
});

test('safeNumber falls back for non-numeric input', () => {
    assert.equal(safeNumber(PAYLOAD), 0);
    assert.equal(safeNumber('42'), 42);
});

test('dashboard AI result contains no raw tags from LLM text', () => {
    const html = buildAiResultHtml(evil());
    assert.ok(!html.includes('<img'), html);
    assert.ok(html.includes('&lt;img'));
});

test('dashboard AI error is escaped', () => {
    assert.ok(!buildAiErrorHtml(PAYLOAD).includes('<img'));
});

test('every micro-agent renderer escapes agent output', () => {
    const data = {};
    for (const k of ['verdict', 'confidence', 'drawdown_vs_atr', 'reasoning', 'compatibility_score', 'strategy_fit',
        'market_regime', 'key_finding', 'suggestion', 'efficiency_grade', 'fee_ratio_pct', 'fee_drag_usd',
        'recommendation', 'warning', 'tp_realism', 'sl_realism', 'nearest_support', 'nearest_resistance',
        'suggested_tp', 'suggested_sl', 'liquidity_level', 'fill_confidence', 'estimated_slippage_pct', 'spread_pct']) {
        data[k] = PAYLOAD;
    }
    for (const id of ['trade-health', 'config-auditor', 'fee-watchdog', 'sltp-optimizer', 'liquidity-scout', 'unknown']) {
        const html = renderAgentResult(id, data);
        assert.ok(!html.includes('<img'), `${id}: ${html}`);
    }
});
