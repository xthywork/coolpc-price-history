// 搜尋結果每列的迷你走勢圖與區間漲跌。表格先畫出來，這兩欄再非同步補上，
// 所以慢的查詢不會拖到第一次繪製；圖是直接生成的 inline SVG，不引入任何
// 圖表函式庫。
(function () {
  var W = 88, H = 22, PAD = 2;

  function points(values) {
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var span = max - min;
    var innerH = H - PAD * 2;
    var stepX = values.length > 1 ? (W - PAD * 2) / (values.length - 1) : 0;
    return values.map(function (v, i) {
      var x = PAD + i * stepX;
      // 價格全程沒變動時畫一條置中的水平線，而不是貼在頂端或底部
      var y = span === 0 ? H / 2 : PAD + innerH - ((v - min) / span) * innerH;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
  }

  function direction(values) {
    var first = values[0], last = values[values.length - 1];
    if (last > first) return 'up';
    if (last < first) return 'down';
    return 'flat';
  }

  function drawSpark(cell, values) {
    cell.textContent = '';
    if (!values || values.length < 2) return;
    var dir = direction(values);
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'spark' + (dir === 'flat' ? '' : ' spark--' + dir));
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('aria-hidden', 'true');
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('class', 'spark__line');
    line.setAttribute('points', points(values));
    svg.appendChild(line);
    cell.appendChild(svg);
  }

  function drawChange(cell, values) {
    cell.textContent = '';
    cell.className = 'col-num col-change';
    if (!values || values.length < 2) return;
    var first = values[0], last = values[values.length - 1];
    var delta = last - first;
    var dir = direction(values);
    if (dir === 'flat') {
      cell.classList.add('flat');
      cell.textContent = '─';
      return;
    }
    var percent = first ? (delta / first) * 100 : 0;
    cell.classList.add(dir);
    cell.textContent = (dir === 'up' ? '▲ +' : '▼ −')
      + Math.abs(delta).toLocaleString()
      + '  ' + Math.abs(percent).toFixed(1) + '%';
  }

  function load() {
    var sparkCells = {};
    var changeCells = {};
    document.querySelectorAll('[data-spark-id]').forEach(function (cell) {
      sparkCells[cell.getAttribute('data-spark-id')] = cell;
    });
    document.querySelectorAll('[data-change-id]').forEach(function (cell) {
      changeCells[cell.getAttribute('data-change-id')] = cell;
    });
    var ids = Object.keys(sparkCells).length ? Object.keys(sparkCells) : Object.keys(changeCells);
    if (!ids.length) return;
    // 端點一次最多接受 100 個商品；每頁筆數選得更大時整批跳過，一次要看
    // 幾百條走勢既讀不出東西，也不值得那個查詢成本。
    if (ids.length > 100) {
      ids.forEach(function (id) {
        if (sparkCells[id]) sparkCells[id].textContent = '';
        if (changeCells[id]) changeCells[id].textContent = '';
      });
      return;
    }
    var days = document.body.getAttribute('data-spark-days') || '30';
    fetch('/api/products/sparklines?days=' + days + '&ids=' + ids.join(','))
      .then(function (resp) { return resp.ok ? resp.json() : {}; })
      .then(function (data) {
        ids.forEach(function (id) {
          if (sparkCells[id]) drawSpark(sparkCells[id], data[id]);
          if (changeCells[id]) drawChange(changeCells[id], data[id]);
        });
      })
      .catch(function () {
        // 走勢失敗不該影響整頁：留白就好，商品名與價格都還在
      });
  }

  window.coolpcSparkline = { refresh: load };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
