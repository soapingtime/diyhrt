const priceChartElement = document.getElementById('price-chart');
const priceChartData = JSON.parse(document.getElementById('pricechart-data').textContent);

// Inherit the site's sans-serif font (Source Sans 3) from Bootstrap CSS variables
Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue('--bs-font-sans-serif').trim();

/* ---------- colour helpers ---------- */

// Read Bootstrap CSS variables for theme-aware colours
function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Segment styling: grey out lines where the product was out of stock
function skipped(ctx, value) {
    return !ctx.p0.raw.in_stock ? value : undefined;
}

priceChartData.datasets.forEach(function (dataset) {
    dataset.segment = {
        borderColor: function (ctx) {
            return skipped(ctx, cssVar('--bs-gray-500'));
        }
    };
});

/* ---------- tooltip ---------- */

function tooltipLabel(tooltipItem) {
    var label = tooltipItem.dataset.label || '';
    var price = Number(tooltipItem.raw.y).toFixed(2);
    return label + ': $' + price;
}

function tooltipAfter(tooltipItem) {
    return tooltipItem.raw.state;
}

/* ---------- timeframe ---------- */

function daysAgo(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d;
}

var defaultDays = 90;

/* ---------- chart ---------- */

var priceChart = new Chart(priceChartElement, {
    type: 'line',
    data: priceChartData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        scales: {
            x: {
                type: 'time',
                min: daysAgo(defaultDays),
                max: new Date(),
                grid: {
                    color: cssVar('--bs-border-color')
                },
                ticks: {
                    color: cssVar('--bs-secondary-color'),
                    maxTicksLimit: 10
                },
                time: {
                    tooltipFormat: 'PP'
                }
            },
            y: {
                grid: {
                    color: cssVar('--bs-border-color')
                },
                ticks: {
                    color: cssVar('--bs-secondary-color'),
                    callback: function (value) {
                        return '$' + value.toFixed(2);
                    }
                }
            }
        },
        interaction: {
            intersect: false,
            mode: 'index'
        },
        plugins: {
            legend: {
                display: priceChartData.datasets.length > 1,
                labels: {
                    color: cssVar('--bs-body-color'),
                    usePointStyle: true,
                    pointStyleWidth: 10,
                    padding: 16,
                    font: {
                        size: 13
                    }
                }
            },
            tooltip: {
                backgroundColor: cssVar('--bs-body-bg'),
                titleColor: cssVar('--bs-body-color'),
                bodyColor: cssVar('--bs-body-color'),
                borderColor: cssVar('--bs-border-color'),
                borderWidth: 1,
                callbacks: {
                    label: tooltipLabel,
                    afterLabel: tooltipAfter
                }
            }
        }
    }
});

/* ---------- timeframe buttons ---------- */

var rangeButtons = document.querySelectorAll('[data-chart-range]');
rangeButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
        var days = parseInt(this.getAttribute('data-chart-range'), 10);

        rangeButtons.forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');

        priceChart.options.scales.x.min = days ? daysAgo(days) : undefined;
        priceChart.options.scales.x.max = new Date();
        priceChart.update();
    });
});
