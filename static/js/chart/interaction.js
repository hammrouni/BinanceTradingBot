/**
 * interaction.js — Logic for chart-specific interactions like drag-to-adjust targets.
 */

export function setupChartInteractions(rsiChart) {
    const canvas = document.getElementById('rsi-chart');
    if (!canvas || !rsiChart) return;
    
    let isDragging = false;
    let dragTarget = null; // 'tp' | 'sl' | 'bc-buy' | 'bc-sell'

    canvas.addEventListener('mousedown', (e) => {
        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        
        // Logical hit detection for banners
        const tpBanner = document.getElementById('tp-banner');
        const slBanner = document.getElementById('sl-banner');
        
        if (tpBanner && isPointOnBanner(y, tpBanner)) {
            isDragging = true;
            dragTarget = 'tp';
            canvas.style.cursor = 'ns-resize';
        } else if (slBanner && isPointOnBanner(y, slBanner)) {
            isDragging = true;
            dragTarget = 'sl';
            canvas.style.cursor = 'ns-resize';
        }
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging || !dragTarget) return;

        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const price = rsiChart.scales.yPrice.getValueForPixel(y);
        
        if (dragTarget === 'tp') {
            updateBannerPosition('tp-banner', y, price);
        } else if (dragTarget === 'sl') {
            updateBannerPosition('sl-banner', y, price);
        }
    });

    window.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            dragTarget = null;
            canvas.style.cursor = 'default';
        }
    });
}

function isPointOnBanner(y, element) {
    if (element.classList.contains('hidden')) return false;
    const rect = element.getBoundingClientRect();
    const bannerY = element.offsetTop;
    return Math.abs(y - bannerY) < 15;
}

function updateBannerPosition(id, y, price) {
    const el = document.getElementById(id);
    if (el) {
        el.style.top = `${y}px`;
        const label = id.startsWith('tp') ? 'TP' : 'SL';
        el.textContent = `${label}: $${price.toFixed(2)}`;
        
        // Sync with input fields in config form
        const inputId = id.startsWith('tp') ? 'take-profit-pct' : 'stop-loss-pct';
        const input = document.getElementById(inputId);
        if (input && window.state?.openPosition) {
            const entryPrice = window.state.openPosition.entry_price;
            const pct = Math.abs((price - entryPrice) / entryPrice) * 100;
            input.value = pct.toFixed(2);
        }
    }
}

// Global assignment for backward compatibility
window.setupChartInteractions = setupChartInteractions;
