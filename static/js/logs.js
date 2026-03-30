const API_BASE = '/api/v1';
const PAGE_SIZE = 100;

let currentOffset = 0;
let totalLogs = 0;
let currentLevel = '';
let currentSearch = '';

async function fetchLogs(offset = 0) {
    const params = new URLSearchParams({
        limit: PAGE_SIZE,
        offset: offset,
    });

    if (currentLevel) {
        params.append('level', currentLevel);
    }
    if (currentSearch) {
        params.append('search', currentSearch);
    }

    try {
        const response = await fetch(`${API_BASE}/logs?${params}`);
        const data = await response.json();

        if (data.status === 'ok') {
            totalLogs = data.total;
            currentOffset = data.offset;
            renderLogs(data.logs);
            updatePagination(data);
        } else {
            console.error('API returned error:', data.error);
            const empty = document.getElementById('logs-empty');
            const tbody = document.getElementById('logs-body');
            tbody.innerHTML = '';
            empty.textContent = `Error: ${data.error || 'Unknown error occurred'}`;
            empty.classList.remove('hidden');
            
            const countEl = document.getElementById('logs-count');
            countEl.textContent = 'Error loading logs';
        }
    } catch (error) {
        console.error('Failed to fetch logs:', error);
        const countEl = document.getElementById('logs-count');
        countEl.textContent = 'Network error fetching logs';
    }
}

function renderLogs(logs) {
    const tbody = document.getElementById('logs-body');
    const empty = document.getElementById('logs-empty');

    tbody.innerHTML = '';

    if (logs.length === 0) {
        empty.textContent = 'No logs found.';
        empty.classList.remove('hidden');
        return;
    }

    empty.classList.add('hidden');

    logs.forEach(log => {
        const row = document.createElement('tr');
        const levelClass = `level-${log.level.toLowerCase()}`;

        row.innerHTML = `
            <td class="col-timestamp">${escapeHtml(log.timestamp)}</td>
            <td class="col-level"><span class="${levelClass}">${escapeHtml(log.level)}</span></td>
            <td class="col-logger">${escapeHtml(log.logger)}</td>
            <td class="col-message">${escapeHtml(log.message)}</td>
        `;

        tbody.appendChild(row);
    });
}

function updatePagination(data) {
    const countEl = document.getElementById('logs-count');
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    const infoEl = document.getElementById('pagination-info');

    countEl.textContent = `Showing ${data.logs.length} of ${data.total} logs`;

    const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
    const totalPages = Math.ceil(totalLogs / PAGE_SIZE);
    infoEl.textContent = `Page ${currentPage} of ${totalPages}`;

    prevBtn.disabled = currentOffset === 0;
    nextBtn.disabled = !data.has_more;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.getElementById('level-filter').addEventListener('change', (e) => {
    currentLevel = e.target.value;
    currentOffset = 0;
    fetchLogs(0);
});

document.getElementById('search-filter').addEventListener('input', debounce((e) => {
    currentSearch = e.target.value;
    currentOffset = 0;
    fetchLogs(0);
}, 300));

document.getElementById('btn-refresh-logs').addEventListener('click', () => {
    fetchLogs(currentOffset);
});

document.getElementById('btn-prev').addEventListener('click', () => {
    if (currentOffset > 0) {
        const newOffset = Math.max(0, currentOffset - PAGE_SIZE);
        fetchLogs(newOffset);
    }
});

document.getElementById('btn-next').addEventListener('click', () => {
    const newOffset = currentOffset + PAGE_SIZE;
    if (newOffset < totalLogs) {
        fetchLogs(newOffset);
    }
});

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

fetchLogs(0);