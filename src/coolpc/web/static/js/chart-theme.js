// 讓 Chart.js 的軸線、格線與文字跟著網站主題走，而不是用它自己的預設灰。
window.coolpcChartTheme = {
  read: function () {
    var cs = getComputedStyle(document.documentElement);
    function token(name) { return cs.getPropertyValue(name).trim(); }
    return {
      ink: token('--ink'),
      muted: token('--muted'),
      line: token('--line'),
      accent: token('--accent'),
      up: token('--up'),
      down: token('--down'),
      mono: token('--font-mono'),
    };
  },

  applyDefaults: function (Chart) {
    var t = this.read();
    Chart.defaults.color = t.muted;
    Chart.defaults.borderColor = t.line;
    Chart.defaults.font.family = t.mono;
    Chart.defaults.font.size = 11;
    return t;
  },

  // x 軸只顯示日期。完整的日期時間留給 tooltip，軸上重複的時間點只會擠成
  // 一團看不清楚。
  dateOnlyTicks: function (labels) {
    return function (value, index) {
      var label = labels[index];
      return label ? String(label).slice(0, 10) : '';
    };
  },

  // 自訂 tooltip：內建的是一行純文字，沒辦法讓名稱靠左、幣別與數字各自
  // 對齊成欄——而那正是比價時最需要的。
  externalTooltip: function (context) {
    var chart = context.chart;
    var model = context.tooltip;
    var host = chart.canvas.parentNode;
    var el = host.querySelector('.chart-tip');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chart-tip';
      host.style.position = host.style.position || 'relative';
      host.appendChild(el);
    }
    if (!model.opacity) {
      el.style.opacity = '0';
      return;
    }

    el.textContent = '';
    var title = document.createElement('div');
    title.className = 'chart-tip__title';
    title.textContent = (model.title && model.title[0]) || '';
    el.appendChild(title);

    var rows = document.createElement('div');
    rows.className = 'chart-tip__rows';
    (model.dataPoints || []).forEach(function (point) {
      var swatch = document.createElement('span');
      swatch.className = 'chart-tip__swatch';
      swatch.style.background = point.dataset.borderColor;

      var name = document.createElement('span');
      name.className = 'chart-tip__name';
      name.textContent = point.dataset.label || '';

      var currency = document.createElement('span');
      currency.className = 'chart-tip__currency';
      currency.textContent = 'NT$';

      var value = document.createElement('span');
      value.className = 'chart-tip__value';
      value.textContent = point.parsed.y === null || point.parsed.y === undefined
        ? '—' : point.parsed.y.toLocaleString();

      rows.append(swatch, name, currency, value);
    });
    el.appendChild(rows);

    // 貼著游標放，靠近右緣時翻到左側，免得被容器切掉
    var area = chart.chartArea;
    var flip = model.caretX > (area.left + area.right) / 2;
    el.style.opacity = '1';
    el.style.left = model.caretX + 'px';
    el.style.top = model.caretY + 'px';
    el.style.transform = flip ? 'translate(-100%, -50%)' : 'translate(0, -50%)';
    el.style.marginLeft = flip ? '-12px' : '12px';
  },

  // 圖表本身的配色（線色、格線）存在 chart 實例裡，切換主題時要整份換掉
  repaint: function (chart, seriesColors) {
    if (!chart) return;
    var t = this.read();
    chart.options.scales.x.grid.color = t.line;
    chart.options.scales.y.grid.color = t.line;
    chart.options.scales.x.ticks.color = t.muted;
    chart.options.scales.y.ticks.color = t.muted;
    chart.data.datasets.forEach(function (ds, i) {
      ds.borderColor = seriesColors ? seriesColors(t, i) : t.accent;
    });
    chart.update('none');
  },
};
