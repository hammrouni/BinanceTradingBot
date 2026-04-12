/**
 * Micro-Agents Frontend Module
 * 
 * Handles the lifecycle of the small "on-demand" AI agents.
 */

let activePopover = null;

export function initMicroAgents() {
    console.log("Initializing Micro-Agents...");
    document.querySelectorAll('.micro-agent-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const agentId = btn.dataset.agent;
            triggerAgent(agentId, btn);
        });
    });

    // Auto-dismiss on outside click
    document.addEventListener('click', (e) => {
        if (activePopover && !activePopover.contains(e.target)) {
            dismissPopover();
        }
    });

    // Handle escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activePopover) {
            dismissPopover();
        }
    });
}

export async function triggerAgent(agentId, anchorEl) {
    if (activePopover) dismissPopover();

    // Show loading state
    anchorEl.classList.add('loading');
    
    try {
        const response = await fetch(`/api/v1/agent/${agentId}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.error || data.detail) {
            showPopover(anchorEl, `<div style="color: #feb2b2;">⚠ ${data.error ?? data.detail}</div>`);
        } else {
            const html = renderAgentResult(agentId, data);
            showPopover(anchorEl, html);
        }
    } catch (err) {
        console.error(`Agent ${agentId} failed:`, err);
        showPopover(anchorEl, `<div style="color: #feb2b2;">Failed to contact agent service.</div>`);
    } finally {
        anchorEl.classList.remove('loading');
    }
}

function showPopover(anchorEl, html) {
    const popover = document.createElement('div');
    popover.className = 'micro-agent-popover';
    popover.innerHTML = html;
    
    // Stop propagation within popover to prevent dismiss on internal clicks
    popover.addEventListener('click', (e) => e.stopPropagation());
    
    document.body.appendChild(popover);
    
    // Position it
    const rect = anchorEl.getBoundingClientRect();
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    
    // Default position: below and aligned left
    popover.style.left = `${rect.left + scrollX}px`;
    popover.style.top = `${rect.bottom + scrollY + 8}px`;
    
    // Final check for positioning
    requestAnimationFrame(() => {
        const popoverRect = popover.getBoundingClientRect();
        
        // Horizontal adjustment
        if (popoverRect.right > window.innerWidth) {
            popover.style.left = `${window.innerWidth - popoverRect.width - 20}px`;
        }
        
        // Vertical adjustment if it goes off bottom
        if (popoverRect.bottom > window.innerHeight) {
            popover.style.top = `${rect.top + scrollY - popoverRect.height - 8}px`;
        }
    });
    
    activePopover = popover;
}

function dismissPopover() {
    if (activePopover) {
        activePopover.remove();
        activePopover = null;
    }
}

function renderAgentResult(agentId, data) {
    switch (agentId) {
        case 'trade-health':
            const verdict = data.verdict || 'NONE';
            const badgeClass = verdict === 'HOLD' ? 'green' : (verdict === 'CAUTION' ? 'yellow' : 'red');
            return `
                <div class="verdict-badge ${badgeClass}">${verdict}</div>
                <div class="agent-detail"><strong>Confidence:</strong> ${(data.confidence * 100).toFixed(0)}%</div>
                <div class="agent-detail">${data.drawdown_vs_atr || 'N/A'}</div>
                <hr style="border: 0; border-top: 1px solid #2d3748; margin: 8px 0;">
                <div class="agent-reasoning">${data.reasoning}</div>
            `;
            
        case 'config-auditor':
            const score = data.compatibility_score || 0;
            const scoreColor = score > 70 ? '#48bb78' : (score > 40 ? '#ecc94b' : '#f56565');
            return `
                <div style="font-weight: bold; margin-bottom: 8px;">Strategy Compatibility</div>
                <div style="height: 6px; background: #2d3748; border-radius: 3px; margin-bottom: 8px; overflow: hidden;">
                    <div style="width: ${score}%; height: 100%; background: ${scoreColor}; border-radius: 3px;"></div>
                </div>
                <div class="agent-detail"><strong>Score:</strong> ${score}% (${data.strategy_fit || 'unknown'})</div>
                <div class="agent-detail"><strong>Regime:</strong> ${data.market_regime || 'calculating...'}</div>
                <div class="agent-reasoning">${data.key_finding || 'No analysis available.'}</div>
                ${data.suggestion ? `<div style="margin-top: 8px; font-size: 11px; opacity: 0.8; font-style: italic;">💡 ${data.suggestion}</div>` : ''}
            `;
            
        case 'fee-watchdog':
            const grade = data.efficiency_grade || '-';
            const gradeColor = grade === 'A' ? '#48bb78' : (grade === 'B' ? '#ecc94b' : (grade === 'C' ? '#ed8936' : '#f56565'));
            return `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-weight: bold;">Fee Efficiency</span>
                    <span style="font-size: 24px; font-weight: 800; color: ${gradeColor};">${grade}</span>
                </div>
                <div class="agent-detail"><strong>Fee Ratio:</strong> ${data.fee_ratio_pct || 0}%</div>
                <div class="agent-detail"><strong>Total Drag:</strong> $${data.fee_drag_usd || 0}</div>
                <div class="agent-reasoning">${data.recommendation || 'No recommendation found.'}</div>
                ${data.warning ? `<div style="color: #f6ad55; font-size: 11px; margin-top: 4px;">⚠️ ${data.warning}</div>` : ''}
            `;
            
        case 'sltp-optimizer':
            return `
                <div style="font-weight: bold; margin-bottom: 8px;">TP/SL Realism Check</div>
                <div class="agent-detail"><strong>TP:</strong> ${data.tp_realism || 'unknown'}</div>
                <div class="agent-detail"><strong>SL:</strong> ${data.sl_realism || 'unknown'}</div>
                <div class="agent-detail"><strong>Nearest S/R:</strong> S: ${data.nearest_support || '?'} / R: ${data.nearest_resistance || '?'}</div>
                <div class="agent-reasoning" style="background: #2d3748; padding: 6px; border-radius: 4px; margin-top: 8px;">
                    <strong>Recommendation:</strong><br>
                    Suggest TP: ${data.suggested_tp || 'N/A'}<br>
                    Suggest SL: ${data.suggested_sl || 'N/A'}
                </div>
                <div class="agent-reasoning" style="margin-top: 8px; font-size: 11px;">${data.reasoning || 'Analyzing...'}</div>
            `;
            
        case 'liquidity-scout':
            const level = data.liquidity_level || 'UNKNOWN';
            const lightColor = level === 'GREEN' ? '#48bb78' : (level === 'YELLOW' ? '#ecc94b' : '#f56565');
            return `
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <div style="width: 12px; height: 12px; border-radius: 50%; background: ${lightColor}; margin-right: 8px; box-shadow: 0 0 8px ${lightColor}; scale: 1.2;"></div>
                    <span style="font-weight: bold;">Liquidity: ${level}</span>
                </div>
                <div class="agent-detail"><strong>Confidence:</strong> ${data.fill_confidence || 'N/A'}</div>
                <div class="agent-detail"><strong>Est. Slippage:</strong> ${data.estimated_slippage_pct || 0}%</div>
                <div class="agent-detail"><strong>Spread:</strong> ${data.spread_pct || 0}%</div>
                <div class="agent-reasoning">${data.reasoning || 'Evaluating order book...'}</div>
            `;

        default:
            return `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    }
}
