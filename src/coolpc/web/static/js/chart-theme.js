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
