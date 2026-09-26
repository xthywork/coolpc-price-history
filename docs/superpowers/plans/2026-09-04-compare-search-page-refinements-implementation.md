# 商品比較與搜尋頁面調整 Implementation Plan

> **歷史文件／非現行待辦：**本文保留當時的實作規劃；文內狀態與核取清單
> 不代表目前實作進度或待辦。查現況請看 [文件索引](../../README.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 調整既有的商品比較頁面（`/compare`）與搜尋頁面（`/`）的介面細節，依使用者本次對話中確認的規格逐項改造。不新增資料庫欄位、不變更核心資料模型、不影響上一輪（2026-09-03）剛完成的合併/搜尋/商品詳情調整的其他部分。

**Architecture:** 純介面調整，落在既有 `src/coolpc/public_api/templates/compare.html`、`base.html`、`search.html` 與 `src/coolpc/public_api/routers/pages.py` 之內，沿用既有 FastAPI + Jinja2 + 純 JS（無框架）架構。`window.coolpcCompare`（2026-09-03 那一輪加入的 localStorage 比較清單）繼續作為唯一的跨頁面比較清單狀態來源，本計畫只調整它的 UI 進入點，不改它的資料結構或 API。

**Tech Stack:** 沿用既有：FastAPI、Jinja2、SQLAlchemy 2.0、pytest、原生 JS、Chart.js（CDN）。

**Spec:** 本計畫沒有獨立 spec 文件——需求已在本次對話中由使用者直接列出。以下 Global Constraints 逐條對應使用者原始訊息的每一句話，並標註兩處我做出的明確假設（使用者原話有歧義，已依最保守、與既有機制一致的方式詮釋，若理解錯誤請直接告知即可調整）。

## Global Constraints

- **商品比較頁圖表日期範圍可調整**：比照商品詳情頁既有的圖表控制項模式（7天/30天/90天/全部按鈕 + 自訂日期區間 `<input type="date">`，`change` 事件觸發即自動重新載入，不要「套用」按鈕），套用到比較頁的多商品疊圖圖表。初始載入維持現況（不帶任何區間參數，等同「全部」）。
- **清空比較清單按鈕搬到商品比較頁面內**：從 `base.html` 的 `<header>`（目前是 `#compareClearLink`）移除，改成放在 `compare.html` 頁面內容裡（例如標題下方）。呼叫的仍是既有的 `window.coolpcCompare.clear()`。
- **點擊導覽列「商品比較」要維持已選好的比較清單**：這是既有行為（`_updateNav()` 每次 `add()`/`remove()`/`clear()` 都會重新把 `href` 設成 `/compare?ids=<目前清單>`），只需確保搬移清空按鈕的過程中不要動到 `_updateNav()` 的邏輯，不需要新增程式碼；本計畫的驗收測試會明確斷言這條路徑沒有被破壞。
- **商品比較表格精簡**：移除「7天最低」「30天最低」「30天最高」「最近漲跌」欄位，只保留「商品」「現價」「歷史最低」「歷史最高」。
- **圖表顏色標示移到商品名稱左邊**：目前 Chart.js 會在圖表上方自動顯示一個「商品 1」「商品 2」這種預設圖例（`legend`），使用者要的是把「哪個顏色對應哪個商品」這件事移到表格每一列「商品」欄位、商品名稱的左邊（一個跟該商品折線同色的小色塊），因此要關閉 Chart.js 預設圖例（`plugins.legend.display: false`），並在表格裡加上色塊。色塊顏色與圖表折線顏色必須是同一份色票、同一個索引順序（用同一個 `colors` 陣列，經由後端 context 傳給樣板，前端 JS 用 `{{ colors|tojson }}` 讀出，避免前後端各自維護一份色票造成不同步）。
- **搜尋頁結果表格只保留 4 個欄位**：商品名稱、分類、價格（即「現價」）、狀態。移除「上次價格」「漲跌」「30天最低」「30天最高」「最後更新」這幾欄。
- **搜尋頁最右側新增核取方塊，可勾選加入比較**：欄位最右側加一欄核取方塊。**明確假設**（使用者原話「可以勾選起來直接去比較」有歧義，可能指「勾選=直接跳轉比較頁」，也可能只是「可以用來比較」的口語說法）：本計畫採用與商品詳情頁核取方塊完全一致的行為——勾選只會呼叫既有的 `window.coolpcCompare.add(id)` 把商品加進清單（不會自動跳轉），取消勾選呼叫 `remove(id)`；達到清單上限 5 個時沿用既有的 `add()` 內建 alert 提示並自動取消勾選狀態。之後仍是透過導覽列「商品比較」連結（已有即時筆數顯示）前往比較頁。理由：與 2026-09-03 那一輪對「加入比較不可自動跳轉」的明確決定（「都不跳轉，等到使用者自己想要比較後才點過去那個分頁」）保持一致的使用者體驗，且完全重用既有的 `window.coolpcCompare` 機制，不需要新設計一套跳轉邏輯。若這個假設不符合你的原意，事後只要把 `add()` 呼叫後面加一行 `window.location.href = ...` 即可調整，改動範圍很小。
- **最後更新時間搬到「共 N 筆結果」後面**：**明確假設**（使用者原話「最後更新時間改道放在幾筆結果的資訊後面」，但「最後更新」原本是逐列、每個商品各自的時間，不可能變成頁面層級單一一行還保留「逐列」意義）：本計畫的詮釋是——不再逐列顯示每個商品各自的最後更新時間，改成在「共 N 筆結果」文字後面，加一個「最後更新：YYYY-MM-DD HH:MM」，顯示這次列出的商品裡最新的一筆更新時間（`MAX(Product.last_seen_at)`，只計算符合目前篩選條件、本頁列出的這批商品）。這樣使用者仍然可以知道資料新鮮度，但不用每一列都重複幾乎相同的時間戳。若你要的其實是別的意思（例如維持逐列顯示、只是想調整這一欄在表格中的欄位順序），請告知，這是本計畫改動最小的一項，之後調整不影響其他部分。
- **搜尋頁欄位寬度可調整**：搜尋結果表格（不是上面的篩選表單）的每個 `<th>` 欄寬要能用滑鼠拖曳調整。這個專案沒有前端框架、也不能載入額外 CDN 函式庫做這件事（依專案既有慣例，所有 JS 都是原生 vanilla JS），要用純 CSS + 原生 JS（`mousedown`/`mousemove`/`mouseup` 監聽 + 直接設定 `th.style.width`）實作一個輕量的欄寬拖曳調整功能，只套用在搜尋頁這個表格，不影響其他頁面的表格。
- 沿用 2026-09-03 那一輪的既有不可違反限制：系統執行期間不使用 AI/LLM/Agent 做任何商品判斷；下架商品不可被刪除、只能標記；本計畫不涉及合併/Undo/抓取邏輯，純粹是這兩個公開頁面的顯示調整。
- 每個任務都要跑 `uv run pytest -q` 確認全數通過（含既有測試，目前基準是 167 個）。

---

### Task 1: 商品比較頁面改版（圖表區間控制、清空清單搬移、表格精簡、顏色色塊）

**Files:**
- Modify: `src/coolpc/public_api/routers/pages.py`（只改 `compare_page` 函式）
- Modify: `src/coolpc/public_api/templates/compare.html`
- Modify: `src/coolpc/public_api/templates/base.html`（只移除 `#compareClearLink` 那一行，其餘不動）
- Test: `tests/public_api/test_compare_page.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: 既有 `window.coolpcCompare.clear()`（定義在 `base.html`，本任務不修改其實作，只改呼叫它的位置）；既有 `GET /api/products/{id}/prices?days=&start=&end=`（`src/coolpc/public_api/routers/api.py`，本任務不修改，只是比照 `product_detail.html` 的既有呼叫模式在 `compare.html` 裡對每個商品都多帶這些參數）。
- Produces: 無新介面，`compare_page` 新增 context key `"colors": [...]`，只有 `compare.html` 自己使用。

- [ ] **Step 1: 寫失敗測試**

先讀 `tests/public_api/test_compare_page.py` 現有內容，確認既有的 `_make_client`／fixture 寫法（沿用既有寫法，不要另建一套）。在檔案尾端新增：

```python
def test_compare_page_table_only_has_four_columns():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較精簡A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較精簡B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "7天最低" not in resp.text
    assert "30天最低" not in resp.text
    assert "30天最高" not in resp.text
    assert "最近漲跌" not in resp.text
    assert "歷史最低" in resp.text
    assert "歷史最高" in resp.text
    assert "現價" in resp.text


def test_compare_page_has_color_dot_before_product_name_and_no_default_legend():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較顏色A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較顏色B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "legend" in resp.text and "display: false" in resp.text.replace('"', '').replace("'", "")
    assert "colors[loop.index0" not in resp.text  # 不應該有殘留的 Jinja 語法字面文字
    assert resp.text.count("background:") >= 2 or resp.text.count("background-color:") >= 2


def test_compare_page_chart_has_range_controls_and_no_apply_button():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較區間A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較區間B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert 'data-range="7"' in resp.text
    assert 'data-range="30"' in resp.text
    assert 'data-range="90"' in resp.text
    assert 'data-range="all"' in resp.text
    assert 'id="rangeStart"' in resp.text
    assert 'id="rangeEnd"' in resp.text
    assert ">套用<" not in resp.text
    assert "'change'" in resp.text


def test_compare_page_has_clear_link_and_base_html_no_longer_does():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較清空A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較清空B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "coolpcCompare.clear()" in resp.text
    assert "清空比較清單" in resp.text

    home = client.get("/")
    assert 'id="compareClearLink"' not in home.text
    # _updateNav 的邏輯（維持已選清單的關鍵）必須還在 base.html 裡，只是清空按鈕搬走
    assert "_updateNav" in home.text
    assert "coolpcCompare" in home.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_compare_page.py -v`
Expected: 四個新測試都 FAIL（目前表格還有 7天/30天欄位；沒有 legend:false 也沒有色塊；沒有 `data-range`/`rangeStart`/`rangeEnd`；`compareClearLink` 還在 `base.html`、`compare.html` 裡沒有清空連結）

- [ ] **Step 3: 實作**

修改 `src/coolpc/public_api/routers/pages.py` 的 `compare_page` 函式，在 `return templates.TemplateResponse(...)` 的 context dict 加入 `colors`：

```python
COMPARE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"]


@router.get("/compare")
def compare_page(request: Request, ids: str | None = None, session: Session = Depends(get_session)):
    items = []
    error = None
    if ids:
        try:
            product_ids = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            product_ids = []
            error = "ids 格式錯誤，請輸入逗號分隔的商品 ID"
        if error is None and not (2 <= len(product_ids) <= 5):
            error = "請選擇 2 到 5 個商品進行比較"
        if error is None:
            for pid in product_ids:
                product = session.get(Product, pid)
                if not _is_visible(product):
                    error = f"商品不存在: {pid}"
                    items = []
                    break
                items.append({"product": product, "stats": compute_product_stats(session, pid)})

    return templates.TemplateResponse(request, "compare.html", {
        "items": items, "ids": ids or "", "error": error, "colors": COMPARE_COLORS,
    })
```

`COMPARE_COLORS` 定義在檔案裡 import 區塊之後、`router = APIRouter()` 之前即可（模組層級常數）。

修改 `src/coolpc/public_api/templates/compare.html` 全檔內容為：

```html
{% extends "base.html" %}
{% block title %}商品比較 - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<h1>商品比較</h1>
<p><a href="#" onclick="window.coolpcCompare.clear(); window.location.href='/compare'; return false;">清空比較清單</a></p>
<form method="get" action="/compare">
  <input type="text" name="ids" placeholder="輸入商品 ID，以逗號分隔，如 1,2,3" value="{{ ids }}">
  <button type="submit">比較</button>
</form>

{% if error %}<p style="color:#b91c1c">{{ error }}</p>{% endif %}

{% if items %}
<table>
  <thead>
    <tr>
      <th>商品</th><th>現價</th><th>歷史最低</th><th>歷史最高</th>
    </tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td>
        <span style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:{{ colors[loop.index0 % colors|length] }};"></span>
        <a href="/products/{{ item.product.id }}">{{ item.product.current_name }}</a>
      </td>
      <td>${{ "{:,}".format(item.product.current_price) }}</td>
      <td>${{ "{:,}".format(item.stats.all_time_low) }}</td>
      <td>${{ "{:,}".format(item.stats.all_time_high) }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<h2>價格走勢</h2>
<div>
  <button data-range="7">7天</button>
  <button data-range="30">30天</button>
  <button data-range="90">90天</button>
  <button data-range="all">全部</button>
  自訂：<input type="date" id="rangeStart"> ~ <input type="date" id="rangeEnd">
</div>
<canvas id="compareChart" height="100"></canvas>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
const productIds = [{% for item in items %}{{ item.product.id }}{% if not loop.last %},{% endif %}{% endfor %}];
const colors = {{ colors|tojson }};
let compareChart;

async function loadCompareChart(params) {
  const seriesList = [];
  for (const pid of productIds) {
    const url = new URL(`/api/products/${pid}/prices`, window.location.origin);
    for (const [k, v] of Object.entries(params || {})) {
      if (v) url.searchParams.set(k, v);
    }
    const resp = await fetch(url);
    seriesList.push(await resp.json());
  }
  const labelSet = new Set();
  seriesList.forEach(series => series.forEach(pt => labelSet.add(pt.scraped_at)));
  const labels = Array.from(labelSet).sort();

  const datasets = seriesList.map((series, i) => {
    const priceByTime = Object.fromEntries(series.map(pt => [pt.scraped_at, pt.price]));
    return {
      label: `商品 ${productIds[i]}`,
      data: labels.map(l => (l in priceByTime ? priceByTime[l] : null)),
      borderColor: colors[i % colors.length],
      spanGaps: true,
      fill: false,
    };
  });

  if (compareChart) {
    compareChart.data.labels = labels;
    compareChart.data.datasets = datasets;
    compareChart.update();
  } else {
    const ctx = document.getElementById('compareChart').getContext('2d');
    compareChart = new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { title: { display: true, text: '日期 / 時間' } },
          y: { title: { display: true, text: '價格 TWD' } },
        },
      },
    });
  }
}

document.querySelectorAll('button[data-range]').forEach(btn => {
  btn.addEventListener('click', () => {
    const range = btn.dataset.range;
    loadCompareChart(range === 'all' ? {} : { days: range });
  });
});

function loadCustomRange() {
  const startVal = document.getElementById('rangeStart').value;
  const endVal = document.getElementById('rangeEnd').value;
  if (!startVal && !endVal) return;
  loadCompareChart({
    start: startVal ? `${startVal}T00:00:00` : '',
    end: endVal ? `${endVal}T23:59:59` : '',
  });
}
document.getElementById('rangeStart').addEventListener('change', loadCustomRange);
document.getElementById('rangeEnd').addEventListener('change', loadCustomRange);

loadCompareChart({});
</script>
{% endif %}
{% endblock %}
```

修改 `src/coolpc/public_api/templates/base.html`，把 `<header>` 區塊裡的這一行整行刪除：

```html
  <a href="#" id="compareClearLink" onclick="window.coolpcCompare.clear(); return false;">清空比較清單</a>
```

`<header>` 改完後只剩：

```html
<header>
  <a href="/">商品搜尋</a>
  <a href="/compare" id="compareNavLink">商品比較</a>
</header>
```

`base.html` 其餘部分（`window.coolpcCompare` 物件本身的定義、`_updateNav()`）完全不動。

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_compare_page.py tests/public_api/test_search_page.py tests/public_api/test_product_detail_page.py -v`
Expected: 全部 PASS（也順便跑一次其他兩個受 `base.html` 影響的頁面測試，確認沒有破壞）

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/public_api/routers/pages.py src/coolpc/public_api/templates/compare.html src/coolpc/public_api/templates/base.html tests/public_api/test_compare_page.py
git commit -m "feat(public): compare page chart range controls, table simplification, color dots, relocate clear-list button"
```

---

### Task 2: 搜尋頁面改版（表格欄位精簡、加入比較核取方塊、最後更新搬移、欄寬可調整）

**Files:**
- Modify: `src/coolpc/public_api/routers/pages.py`（只改 `search_page` 函式）
- Modify: `src/coolpc/public_api/templates/search.html`
- Test: `tests/public_api/test_search_page.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: 既有 `window.coolpcCompare.add(id)` / `.remove(id)` / `.has(id)`（定義在 `base.html`，本任務不修改）。
- Produces: 無新介面。

- [ ] **Step 1: 寫失敗測試**

在 `tests/public_api/test_search_page.py` 尾端新增：

```python
def test_search_page_results_table_only_has_four_columns_plus_checkbox():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="表格精簡測試",
                   current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get("/")
    assert resp.status_code == 200
    assert "上次價格" not in resp.text
    assert "漲跌</th>" not in resp.text
    assert "30天最低" not in resp.text
    assert "30天最高" not in resp.text
    assert "<th>最後更新</th>" not in resp.text
    assert "商品名稱" in resp.text
    assert "分類" in resp.text
    assert "狀態" in resp.text
    assert f'data-id="{product_id}"' in resp.text
    assert 'class="compareCheckbox"' in resp.text


def test_search_page_shows_global_last_updated_after_result_count():
    client, Session_ = _make_client()
    t1 = datetime.datetime(2026, 1, 1, 12, 0)
    t2 = datetime.datetime(2026, 2, 1, 18, 0)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="更新時間A",
                    current_price=1000, is_active=True, first_seen_at=t1, last_seen_at=t1, created_at=t1)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="更新時間B",
                    current_price=2000, is_active=True, first_seen_at=t2, last_seen_at=t2, created_at=t2)
        session.add_all([p1, p2])
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    count_pos = resp.text.find("共 2 筆結果")
    updated_pos = resp.text.find("最後更新")
    assert count_pos != -1
    assert updated_pos != -1
    assert updated_pos > count_pos
    assert "2026-02-01 18:00" in resp.text  # 兩者取較新的 t2


def test_search_page_table_is_resizable():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "col-resizer" in resp.text
    assert "mousedown" in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_search_page.py -v -k "four_columns or last_updated or resizable"`
Expected: 三個新測試都 FAIL（目前表格還有 9 欄且沒有核取方塊；沒有全域「最後更新」文字；沒有 `col-resizer`/`mousedown` 欄寬調整邏輯）

- [ ] **Step 3: 實作**

修改 `src/coolpc/public_api/routers/pages.py`，在檔案頂部 import 區塊加入 `func`：

```python
from sqlalchemy import func
```

（加在 `from sqlalchemy.orm import Session` 這行附近即可）

在 `search_page` 函式裡，`products, total = search_products(session, filters)` 這行之後，新增全域最後更新時間查詢——**注意**：這裡刻意用「符合目前篩選條件（`filters`）」的最新更新時間，跟本頁實際列出的商品一致，而不是全站最新時間，用同一個 `search_products` 但改成不限筆數只取最大值的作法太浪費，改成對同樣的 filter 條件單獨查 `MAX(last_seen_at)`：

```python
    last_updated_query = session.query(func.max(Product.last_seen_at)).filter(Product.merged_into_id.is_(None))
    if filters.subcategory_id is not None:
        last_updated_query = last_updated_query.filter(Product.subcategory_id == filters.subcategory_id)
    if filters.is_active is not None:
        last_updated_query = last_updated_query.filter(Product.is_active == filters.is_active)
    last_updated = last_updated_query.scalar()
```

（只套用 `subcategory_id` 與 `is_active` 這兩個目前搜尋頁 UI 還看得到的篩選條件即可，不需要重新實作 `search_products` 全部的篩選邏輯——這是給使用者一個「資料新鮮度」的粗略指標，不是逐商品精確值，稍微寬鬆的篩選範圍是可接受的。)

在 `return templates.TemplateResponse(request, "search.html", {...})` 的 context dict 裡新增一個 key：`"last_updated": last_updated,`（放在 `"total": total,` 那一行之後）。

修改 `src/coolpc/public_api/templates/search.html` 全檔內容為：

```html
{% extends "base.html" %}
{% block title %}商品搜尋 - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<form class="filters" method="get" action="/">
  <input type="text" name="q" placeholder="搜尋商品名稱/舊名稱/關鍵字" value="{{ query.q }}">
  <select name="subcategory_id">
    <option value="">全部分類</option>
    {% for sc in subcategories %}
    <option value="{{ sc.id }}" {% if query.subcategory_id == sc.id %}selected{% endif %}>{{ sc.label }}</option>
    {% endfor %}
  </select>
  <select name="brand">
    <option value="">全部品牌</option>
    {% for b in brands %}
    <option value="{{ b }}" {% if query.brand == b %}selected{% endif %}>{{ b }}</option>
    {% endfor %}
  </select>
  <input type="number" name="min_price" placeholder="最低價格" value="{{ query.min_price or '' }}">
  <input type="number" name="max_price" placeholder="最高價格" value="{{ query.max_price or '' }}">
  <select name="is_active">
    <option value="">在售/下架</option>
    <option value="true" {% if query.is_active == True %}selected{% endif %}>僅在售</option>
    <option value="false" {% if query.is_active == False %}selected{% endif %}>僅下架</option>
  </select>
  <select name="recent_change">
    <option value="">漲跌</option>
    <option value="up" {% if query.recent_change == "up" %}selected{% endif %}>最近漲價</option>
    <option value="down" {% if query.recent_change == "down" %}selected{% endif %}>最近降價</option>
  </select>
  <select name="sort">
    <option value="last_seen_desc" {% if query.sort == "last_seen_desc" %}selected{% endif %}>最近更新</option>
    <option value="price_asc" {% if query.sort == "price_asc" %}selected{% endif %}>價格低到高</option>
    <option value="price_desc" {% if query.sort == "price_desc" %}selected{% endif %}>價格高到低</option>
    <option value="name_asc" {% if query.sort == "name_asc" %}selected{% endif %}>名稱排序</option>
  </select>
  <button type="submit">搜尋</button>
</form>

<p>共 {{ total }} 筆結果{% if last_updated %}　最後更新：{{ last_updated.strftime("%Y-%m-%d %H:%M") }}{% endif %}</p>

<style>
  #resultsTable { table-layout: fixed; }
  #resultsTable th { position: relative; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  #resultsTable th .col-resizer {
    position: absolute; right: 0; top: 0; width: 6px; height: 100%; cursor: col-resize; user-select: none;
  }
</style>

<table id="resultsTable">
  <thead>
    <tr>
      <th>商品名稱</th><th>分類</th><th>價格</th><th>狀態</th><th></th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr class="{% if not row.product.is_active %}inactive{% endif %}">
      <td><a href="/products/{{ row.product.id }}">{{ row.product.current_name }}</a></td>
      <td>{{ row.category.name }}</td>
      <td>${{ "{:,}".format(row.product.current_price) }}</td>
      <td>{{ "在售" if row.product.is_active else "已下架" }}</td>
      <td><input type="checkbox" class="compareCheckbox" data-id="{{ row.product.id }}"></td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<div class="pagination">
  {% if page > 1 %}<a href="/?{{ query_string }}&page={{ page - 1 }}">上一頁</a>{% endif %}
  <span>第 {{ page }} / {{ total_pages }} 頁</span>
  {% if page < total_pages %}<a href="/?{{ query_string }}&page={{ page + 1 }}">下一頁</a>{% endif %}
</div>

<script>
document.querySelectorAll('.compareCheckbox').forEach(cb => {
  const id = parseInt(cb.dataset.id, 10);
  cb.checked = window.coolpcCompare.has(id);
  cb.addEventListener('change', () => {
    if (cb.checked) {
      const ok = window.coolpcCompare.add(id);
      if (!ok) cb.checked = false;
    } else {
      window.coolpcCompare.remove(id);
    }
  });
});

function makeColumnsResizable(table) {
  table.querySelectorAll('th').forEach(th => {
    const resizer = document.createElement('div');
    resizer.className = 'col-resizer';
    th.appendChild(resizer);
    resizer.addEventListener('mousedown', (e) => {
      const startX = e.pageX;
      const startWidth = th.offsetWidth;
      const onMouseMove = (e2) => {
        th.style.width = Math.max(40, startWidth + (e2.pageX - startX)) + 'px';
      };
      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
      e.preventDefault();
    });
  });
}
const resultsTable = document.getElementById('resultsTable');
if (resultsTable) makeColumnsResizable(resultsTable);
</script>
{% endblock %}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_search_page.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/public_api/routers/pages.py src/coolpc/public_api/templates/search.html tests/public_api/test_search_page.py
git commit -m "feat(public): search results table simplification, compare checkbox column, global last-updated line, resizable columns"
```

---

### Task 3: 全套驗證、重啟服務、收尾

**Files:** 無程式碼變更（純驗證與部署動作）。

**Interfaces:** 無。

- [ ] **Step 1: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過（167 + Task 1/2 新增的測試）

- [ ] **Step 2: 用真實資料庫手動驗證**

先確認目前是否已有 uvicorn 進程在跑，若有先停掉再用修改後的程式碼重啟：

```bash
pkill -f "uvicorn coolpc.public_api" || true
pkill -f "uvicorn coolpc.admin_api" || true
sleep 1
cd /home/xthybot/coolpc-price-history
nohup uv run uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690 > /tmp/public_api.log 2>&1 &
nohup uv run uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691 > /tmp/admin_api.log 2>&1 &
sleep 3
```

用 `curl` 逐項確認（用資料庫裡實際存在的商品 id）：

- `curl -s http://127.0.0.1:33690/ | grep -c '上次價格'` → 應為 `0`
- `curl -s http://127.0.0.1:33690/ | grep -c 'compareCheckbox'` → 應 ≥ `1`
- `curl -s http://127.0.0.1:33690/ | grep -c 'col-resizer'` → 應為 `1`
- `curl -s http://127.0.0.1:33690/ | grep -c '最後更新'` → 應 ≥ `1`
- 取兩個真實商品 id（例如 `1,3`），`curl -s "http://127.0.0.1:33690/compare?ids=1,3" | grep -c '7天最低'` → 應為 `0`
- 同一個請求 `grep -c 'data-range="7"'` → 應為 `1`
- `curl -s http://127.0.0.1:33690/ | grep -c 'compareClearLink'` → 應為 `0`（已搬到 compare 頁）
- `curl -s "http://127.0.0.1:33690/compare?ids=1,3" | grep -c '清空比較清單'` → 應為 `1`

若有任何一項不符預期，回頭檢查對應 Task 的檔案是否漏改，修正後重新整個重啟服務再驗證一次。

- [ ] **Step 3: Push**

```bash
git log --oneline -5
git push
```

- [ ] **Step 4: 回報使用者**

服務保持在 `0.0.0.0:33690`（公開查詢）與 `0.0.0.0:33691`（管理介面）運行，供使用者實際點擊測試。回報時明確提醒使用者確認本計畫 Global Constraints 裡的兩個「明確假設」（核取方塊是否要自動跳轉、最後更新是否要改成單一彙總時間）是否符合原意。
