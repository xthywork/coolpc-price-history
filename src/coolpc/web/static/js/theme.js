// 明暗主題：預設跟隨作業系統，手動切換後記在 localStorage。
// 這段必須在 <head> 同步執行，否則深色使用者會先看到一閃的亮色頁面。
(function () {
  var KEY = 'coolpc_theme';
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) {}
  if (stored === 'light' || stored === 'dark') {
    document.documentElement.setAttribute('data-theme', stored);
  }

  function current() {
    var attr = document.documentElement.getAttribute('data-theme');
    if (attr) return attr;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function paint(btn) {
    var isDark = current() === 'dark';
    btn.textContent = isDark ? '☀' : '☾';
    btn.setAttribute('aria-label', isDark ? '切換到明亮主題' : '切換到深色主題');
    btn.title = btn.getAttribute('aria-label');
  }

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    paint(btn);
    btn.addEventListener('click', function () {
      var next = current() === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(KEY, next); } catch (e) {}
      paint(btn);
      // 走勢圖的軸線與文字顏色是從 CSS 變數讀出來畫進 canvas 的，切換主題
      // 後必須主動通知它們重畫，否則圖表會留在上一個主題的配色。
      document.dispatchEvent(new CustomEvent('coolpc:themechange'));
    });
  });
})();
