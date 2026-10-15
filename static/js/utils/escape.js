/**
 * Shared HTML escaping for anything that originates from an LLM, an agent or an error message.
 * Always run untrusted text through escapeHtml() before it goes into innerHTML.
 */
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, ch => HTML_ESCAPES[ch]);
}

/** Coerce to a finite number (for style="width:..%" etc.); anything else becomes `fallback`. */
export function safeNumber(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}
