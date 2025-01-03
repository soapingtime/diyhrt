const priceChartElement = document.getElementById("price-chart");
const priceChartData = JSON.parse(document.getElementById("pricechart-data").textContent);

function skipped(ctx, value) {
    output = !ctx.p0.raw.in_stock ? value : undefined;
    return output;
}

priceChartData.datasets.forEach(
    function (dataset) {
        dataset.segment = {
            borderColor: ctx => skipped(ctx, "rgba(0, 0, 0, 0)")
        }
    }
);


function afterLabelGen(tooltipItem) {
    return tooltipItem.raw.state;
}


let start_date = new Date();
start_date.setDate(start_date.getDate() - 365);


let priceChart = new Chart(
    priceChartElement,
    {
        type: 'line',
        data: priceChartData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                xAxis: {
                    type: "time",
                    min: start_date,
                    max: new Date(),
                },
                yAxis: {
                }
            },
            interaction: {
                intersect: false,
                axis: 'xAxis'
            },
            plugins: {
                legend: {
                    labels: {
                        // This more specific font property overrides the global property
                        font: {
                            family: '"Nunito Sans", Cambria, "Times New Roman", Times, serif',
                            size: 16
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        afterLabel: afterLabelGen,
                    }
                }
            },

        }
    }
);


const actions = [
    {
        name: 'Step: false (default)',
        handler: (chart) => {
            chart.data.datasets.forEach(dataset => {
                dataset.stepped = false;
            });
            chart.update();
        }
    },
    {
        name: 'Step: true',
        handler: (chart) => {
            chart.data.datasets.forEach(dataset => {
                dataset.stepped = true;
            });
            chart.update();
        }
    },
    {
        name: 'Step: before',
        handler: (chart) => {
            chart.data.datasets.forEach(dataset => {
                dataset.stepped = 'before';
            });
            chart.update();
        }
    },
    {
        name: 'Step: after',
        handler: (chart) => {
            chart.data.datasets.forEach(dataset => {
                dataset.stepped = 'after';
            });
            chart.update();
        }
    },
    {
        name: 'Step: middle',
        handler: (chart) => {
            chart.data.datasets.forEach(dataset => {
                dataset.stepped = 'middle';
            });
            chart.update();
        }
    }
];
