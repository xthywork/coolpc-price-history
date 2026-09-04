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

    // 每個系列固定佔一列，就算這個時間點還沒有資料也一樣（顯示「—」）。
    // 只列出有值的系列會讓 tooltip 寬度隨游標位置忽寬忽窄。
    var points = model.dataPoints || [];
    var dataIndex = points.length ? points[0].dataIndex : -1;

    var rows = document.createElement('div');
    rows.className = 'chart-tip__rows';
    chart.data.datasets.forEach(function (dataset, i) {
      if (!chart.isDatasetVisible(i)) return;
      var raw = dataIndex < 0 ? null : dataset.data[dataIndex];

      var swatch = document.createElement('span');
      swatch.className = 'chart-tip__swatch';
      swatch.style.background = dataset.borderColor;

      var name = document.createElement('span');
      name.className = 'chart-tip__name';
      name.textContent = dataset.label || '';

      var currency = document.createElement('span');
      currency.className = 'chart-tip__currency';
      currency.textContent = 'NT$';

      var value = document.createElement('span');
      value.className = 'chart-tip__value';
      value.textContent = (raw === null || raw === undefined) ? '—' : Number(raw).toLocaleString();

      rows.append(swatch, name, currency, value);
    });
    el.appendChild(rows);

    // 依游標在「畫面」的哪一半決定展開方向：右半邊往左開，左半邊往右開。
    // 用視窗中線而不是圖表中線，才符合實際看畫面的直覺。
    var rect = chart.canvas.getBoundingClientRect();
    var pointerViewportX = rect.left + model.caretX;
    var flip = pointerViewportX > window.innerWidth / 2;

    el.style.opacity = '1';
    el.style.transform = flip ? 'translate(-100%, -50%)' : 'translate(0, -50%)';
    el.style.marginLeft = flip ? '-14px' : '14px';
    el.style.left = model.caretX + 'px';

    // 垂直方向夾在圖表範圍內，貼近上下緣時才不會被切掉半截
    var half = el.offsetHeight / 2 + 4;
    var top = Math.min(Math.max(model.caretY, half), chart.height - half);
    el.style.top = top + 'px';
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
