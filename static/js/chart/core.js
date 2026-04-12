/**
 * core.js — Chart.js initialization and base configuration.
 */

export let candleChart = null;
export let rsiChart = null;

export const chartConfig = {
    rsiMaxPoints: 500,
    priceMaxPoints: 1000
};

export function initCharts() {
    const ctxRsi = document.getElementById('rsi-chart').getContext('2d');
    
    rsiChart = new Chart(ctxRsi, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Price',
                    data: [],
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    yAxisID: 'yPrice',
                    tension: 0.1,
                    fill: false
                },
                {
                    label: 'RSI',
                    data: [],
                    borderColor: 'rgba(153, 102, 255, 1)',
                    backgroundColor: 'rgba(153, 102, 255, 0.1)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: 'yRsi',
                    tension: 0.1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'minute' },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: 'rgba(255, 255, 255, 0.5)' }
                },
                yPrice: {
                    position: 'left',
                    title: { display: true, text: 'Price ($)', color: 'rgba(75, 192, 192, 1)' },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: 'rgba(75, 192, 192, 0.8)' }
                },
                yRsi: {
                    position: 'right',
                    min: 0,
                    max: 100,
                    title: { display: true, text: 'RSI', color: 'rgba(153, 102, 255, 1)' },
                    grid: { drawOnChartArea: false },
                    ticks: { stepSize: 10, color: 'rgba(153, 102, 255, 0.8)' }
                }
            },
            plugins: {
                legend: { labels: { color: 'rgba(255, 255, 255, 0.7)' } }
            }
        }
    });

    window.rsiChartInstance = rsiChart;
    return rsiChart;
}

export function updateRsiChart(rsi, timestamp, currentPrice) {
    if (!rsiChart) return;
    
    const time = timestamp ? new Date(timestamp) : new Date();
    const datasets = rsiChart.data.datasets;
    
    datasets[0].data.push({ x: time, y: currentPrice });
    datasets[1].data.push({ x: time, y: rsi });
    
    if (datasets[0].data.length > chartConfig.priceMaxPoints) {
        datasets[0].data.shift();
        datasets[1].data.shift();
    }
    
    rsiChart.update('none');
}

export function setRsiHistory(history) {
    if (!rsiChart || !history) return;
    
    const priceData = [];
    const rsiData = [];
    
    history.forEach(item => {
        const time = new Date(item.timestamp);
        priceData.push({ x: time, y: item.price });
        rsiData.push({ x: time, y: item.rsi });
    });
    
    rsiChart.data.datasets[0].data = priceData;
    rsiChart.data.datasets[1].data = rsiData;
    rsiChart.update();
}

// Global assignment for backward compatibility with existing dashboard code
window.initCharts = initCharts;
window.updateRsiChart = updateRsiChart;
window.setRsiHistory = setRsiHistory;
