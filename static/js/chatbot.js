/**
 * chatbot.js — Floating chat widget for BinanceTradingBot.
 * Communicates with POST /api/v1/chat/message (Claude + MCP tools).
 */
(function () {
    'use strict';

    const toggle   = document.getElementById('chatbot-toggle');
    const panel    = document.getElementById('chatbot-panel');
    const closeBtn = document.getElementById('chatbot-close');
    const messages = document.getElementById('chatbot-messages');
    const input    = document.getElementById('chatbot-input');
    const sendBtn  = document.getElementById('chatbot-send');
    const badge    = document.getElementById('chatbot-badge');

    // Conversation history sent to the API (excludes the initial welcome message)
    let history = [];
    let busy = false;

    // ── Panel open / close ────────────────────────────────────────────────────

    function openPanel() {
        panel.classList.remove('hidden');
        panel.classList.add('open');
        badge.classList.add('hidden');
        input.focus();
    }

    function closePanel() {
        panel.classList.remove('open');
        panel.classList.add('hidden');
    }

    toggle.addEventListener('click', () => {
        panel.classList.contains('hidden') ? openPanel() : closePanel();
    });

    closeBtn.addEventListener('click', closePanel);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !panel.classList.contains('hidden')) closePanel();
    });

    // ── Auto-resize textarea ──────────────────────────────────────────────────

    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    // ── Message rendering ─────────────────────────────────────────────────────

    function addMessage(role, text) {
        const wrap = document.createElement('div');
        wrap.className = `chatbot-msg ${role}`;

        const bubble = document.createElement('div');
        bubble.className = 'chatbot-bubble';
        bubble.innerHTML = formatText(text);

        wrap.appendChild(bubble);
        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
    }

    function addTypingIndicator() {
        const wrap = document.createElement('div');
        wrap.className = 'chatbot-msg assistant typing-wrap';
        wrap.id = 'typing-indicator';
        wrap.innerHTML = '<div class="chatbot-bubble chatbot-typing"><span></span><span></span><span></span></div>';
        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    function removeTypingIndicator() {
        const el = document.getElementById('typing-indicator');
        if (el) el.remove();
    }

    // Basic markdown-lite: bold, inline code, line breaks
    function formatText(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    }

    // ── API call ──────────────────────────────────────────────────────────────

    async function sendMessage() {
        const text = input.value.trim();
        if (!text || busy) return;

        busy = true;
        input.value = '';
        input.style.height = 'auto';
        sendBtn.disabled = true;

        addMessage('user', text);
        addTypingIndicator();

        try {
            const resp = await fetch('/api/v1/chat/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, history }),
            });

            removeTypingIndicator();

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                addMessage('assistant', `Error ${resp.status}: ${err.detail || 'Request failed'}`);
            } else {
                const data = await resp.json();
                const reply = data.response || '(no response)';
                addMessage('assistant', reply);

                // Append to history for multi-turn context
                history.push({ role: 'user', content: text });
                history.push({ role: 'assistant', content: reply });

                // Keep history bounded (last 20 turns = 10 exchanges)
                if (history.length > 20) history = history.slice(-20);

                // If panel is closed, show badge
                if (panel.classList.contains('hidden')) {
                    badge.classList.remove('hidden');
                }
            }
        } catch (err) {
            removeTypingIndicator();
            addMessage('assistant', `Network error: ${err.message}`);
        } finally {
            busy = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }
})();
