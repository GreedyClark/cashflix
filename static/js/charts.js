var charts = [];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function isDark() {
  return document.documentElement.getAttribute("data-bs-theme") === "dark";
}

function money(value) {
  return new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(value) + " ₴";
}

function short(value) {
  if (value >= 1000) {
    return (Math.round(value / 100) / 10).toString().replace(".", ",") + " тис.";
  }
  return Math.round(value).toString();
}

function baseOptions() {
  return {
    chart: {
      fontFamily: cssVar("--font"),
      foreColor: cssVar("--ink-subtle"),
      toolbar: { show: false },
      zoom: { enabled: false },
      background: "transparent",
      animations: { enabled: !matchMedia("(prefers-reduced-motion: reduce)").matches, speed: 700 },
    },
    theme: { mode: isDark() ? "dark" : "light" },
    grid: { borderColor: cssVar("--hairline"), strokeDashArray: 4, xaxis: { lines: { show: false } } },
    dataLabels: { enabled: false },
    legend: { show: false },
    tooltip: { theme: isDark() ? "dark" : "light" },
  };
}

function axisLabels() {
  return { style: { fontSize: "11px", colors: cssVar("--ink-tertiary") } };
}

function sparkOptions(values, color, type) {
  var options = baseOptions();
  options.chart.type = type || "area";
  options.chart.height = 50;
  options.chart.sparkline = { enabled: true };
  options.series = [{ name: "", data: values }];
  options.colors = [cssVar(color)];
  options.stroke = { width: type === "bar" ? 0 : 2, curve: "smooth" };
  options.fill = type === "bar"
    ? { opacity: 1 }
    : { type: "gradient", gradient: { opacityFrom: 0.28, opacityTo: 0, stops: [0, 100] } };
  options.plotOptions = { bar: { columnWidth: "55%", borderRadius: 2 } };
  options.tooltip = { enabled: false };
  return options;
}

function spendingOptions(data) {
  var days = [];
  for (var day = 1; day <= data.days; day++) days.push(day);

  var options = baseOptions();
  var top = Math.max(data.income, data.forecast[data.forecast.length - 1] || 0, data.previous[data.previous.length - 1] || 0);
  options.chart.type = "area";
  options.chart.height = window.innerWidth >= 992 ? 290 : 230;
  options.series = [
    { name: "Минулий місяць", data: data.previous },
    { name: "Цей місяць", data: data.current },
    { name: "Прогноз", data: data.forecast },
  ];
  options.colors = [cssVar("--ink-tertiary"), cssVar("--cat-1"), cssVar("--cat-1")];
  options.stroke = { width: [1.5, 3, 2], curve: "monotoneCubic", dashArray: [0, 0, 5], lineCap: "round" };
  options.fill = {
    type: ["solid", "gradient", "solid"],
    opacity: [isDark() ? 0.14 : 0.1, 1, 0],
    gradient: { opacityFrom: isDark() ? 0.5 : 0.32, opacityTo: 0, stops: [0, 100] },
  };
  options.markers = {
    size: 0,
    discrete: [{ seriesIndex: 1, dataPointIndex: data.today - 1, size: 6, fillColor: cssVar("--cat-1"), strokeColor: cssVar("--surface-1") }],
  };
  options.yaxis = {
    min: 0,
    max: Math.ceil((top * 1.08) / 10000) * 10000 || 10000,
    tickAmount: 3,
    opposite: true,
    labels: Object.assign(axisLabels(), { formatter: short }),
  };
  options.xaxis = {
    categories: days,
    axisBorder: { show: false },
    axisTicks: { show: false },
    tooltip: { enabled: false },
    labels: Object.assign(axisLabels(), {
      rotate: 0,
      formatter: function (day) {
        if (day == data.today) return "сьогодні";
        if (day == 1 || day == data.days) return day;
        return day % 7 === 0 && Math.abs(day - data.today) > 3 ? day : "";
      },
    }),
  };
  if (data.income) {
    options.annotations = {
      yaxis: [{
        y: data.income,
        borderColor: cssVar("--good"),
        strokeDashArray: 5,
        label: {
          text: "дохід " + short(data.income),
          position: "left",
          textAnchor: "start",
          borderWidth: 0,
          style: { background: "transparent", color: cssVar("--good"), fontSize: "11px" },
        },
      }],
    };
  }
  options.tooltip.shared = true;
  options.tooltip.intersect = false;
  options.tooltip.x = { formatter: function (day) { return day + " " + data.month; } };
  options.tooltip.y = {
    formatter: function (value, point) {
      if (value === null) return undefined;
      if (point && point.seriesIndex === 2 && point.dataPointIndex < data.today) return undefined;
      return money(value);
    },
  };
  return options;
}

function halfYearOptions(data) {
  var options = baseOptions();
  options.chart.type = "bar";
  options.chart.height = window.innerWidth >= 992 ? 290 : 230;
  options.series = [{ name: "Дохід", data: data.earned }, { name: "Витрати", data: data.spent }];
  options.colors = [cssVar("--cat-1"), cssVar("--cat-2")];
  options.plotOptions = { bar: { columnWidth: "58%", borderRadius: 5, borderRadiusApplication: "end" } };
  options.stroke = { show: true, width: 3, colors: [cssVar("--surface-1")] };
  options.xaxis = { categories: data.labels, axisBorder: { show: false }, axisTicks: { show: false }, labels: axisLabels() };
  options.yaxis = { tickAmount: 3, opposite: true, labels: Object.assign(axisLabels(), { formatter: short }) };
  options.tooltip.shared = true;
  options.tooltip.intersect = false;
  options.tooltip.y = { formatter: money };
  return options;
}

function categoriesOptions(data) {
  var options = baseOptions();
  options.chart.type = "donut";
  options.chart.height = 220;
  options.series = data.values;
  options.labels = data.labels;
  options.colors = data.slots.map(function (slot) {
    return cssVar(slot ? "--cat-" + slot : "--cat-other");
  });
  options.stroke = { width: 2, colors: [cssVar("--surface-1")] };
  options.plotOptions = { pie: { expandOnClick: false, donut: { size: "74%", labels: { show: false } } } };
  options.tooltip = { theme: isDark() ? "dark" : "light", fillSeriesColor: false, y: { formatter: money } };
  options.states = { hover: { filter: { type: "none" } }, active: { filter: { type: "none" } } };
  return options;
}

function drawCharts() {
  var source = document.getElementById("overview-data");
  if (!source || typeof ApexCharts === "undefined") return;
  var data = JSON.parse(source.textContent);

  charts.forEach(function (chart) { chart.destroy(); });
  charts = [];

  var builders = {
    balance: function () { return sparkOptions(data.balance, "--accent"); },
    earned: function () { return sparkOptions(data.halfYear.earned, "--cat-3"); },
    spent: function () { return sparkOptions(data.halfYear.spent, "--cat-2"); },
    savings: function () { return sparkOptions(data.halfYear.savings, "--accent", "bar"); },
    spending: function () { return spendingOptions(data.spending); },
    halfYear: function () { return halfYearOptions(data.halfYear); },
    categories: function () { return categoriesOptions(data.categories); },
  };

  document.querySelectorAll("[data-chart]").forEach(function (element) {
    var chart = new ApexCharts(element, builders[element.dataset.chart]());
    chart.render();
    charts.push(chart);
  });
}

document.addEventListener("DOMContentLoaded", drawCharts);
document.addEventListener("cashflix:theme", drawCharts);
document.body.addEventListener("htmx:afterSettle", function (event) {
  if (event.detail.target.id === "overview") drawCharts();
});
