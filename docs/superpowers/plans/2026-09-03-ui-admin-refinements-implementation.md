# UI/Admin 介面調整 Implementation Plan

> **歷史文件／非現行待辦：**本文保留當時的實作規劃；文內狀態與核取清單
> 不代表目前實作進度或待辦。查現況請看 [文件索引](../../README.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 調整原價屋歷史價格查詢系統既有的管理介面（合併商品流程）與公開查詢介面（搜尋、商品詳情、比較），依使用者確認過的規格逐項改造，不新增資料庫欄位、不變更核心資料模型。

**Architecture:** 這是對既有已上線系統的介面/行為調整，不是新子系統。所有改動落在既有的 `src/coolpc/admin_api/`、`src/coolpc/public_api/`、`src/coolpc/search/`、`src/coolpc/merging/` 之內，沿用既有的 FastAPI + Jinja2 + 純 SQLAlchemy ORM 架構與既有測試風格（`TestClient` + in-memory SQLite `StaticPool`）。

**Tech Stack:** 沿用既有：FastAPI、Jinja2、SQLAlchemy 2.0、pytest、原生 JS（無前端框架）、Chart.js（CDN，已引入不動）。

**Spec:** 本計畫沒有獨立的 spec 文件——需求細節已在本次對話中與使用者逐項確認完畢（詳見下方 Global Constraints，逐條對應使用者的 5 項需求與追問後的最終決定）。

## Global Constraints

- 這是既有生產系統的調整，工作直接在 `main` 分支進行（沿用專案既有慣例，使用者已同意）。
- **合併商品（項目1）：**
  - 「可能需要合併的商品」頁面（`/similarity-hints`）保留候選清單，移除每列的「操作」欄，改成每列左側一個核取方塊；頁面上方兩個提交按鈕：「批量合併」「批量忽略」。
  - 批量合併時，一組候選（商品 A、商品 B）誰是保留的「目標」、誰是被合併的「來源」，規則固定為：兩者只有一個仍在上架中 → 該商品當目標；否則（都上架或都下架）→ `last_seen_at` 較新者當目標；完全同分 → `id` 較小者當目標。此規則實作為 `choose_merge_direction(a, b) -> (source, target)`。
  - 保留一個獨立的手動合併頁面（`/merge`），但欄位改為「先搜尋商品名稱、點選結果」為主，數字 ID 輸入框保留為備用/後備手段（不是必填的唯一途徑，但表單最終送出的仍是數字 ID）。
  - 合併紀錄表格＋Undo 按鈕保留在 `/merge` 頁面，不搬移、不刪除——這是原始需求「Undo Merge 必須完全可逆」的既有實作，批量合併與手動合併都會寫入同一份 `MergeLog`，因此都能在這裡復原。
- **搜尋頁面（項目2）：**
  - 分類（`category_id`）與子分類（`subcategory_id`）兩個下拉選單合併成一個，只保留子分類層級（選項文字已經是「分類 / 子分類」格式），不需要「只選分類、不挑子分類」的篩選層級。
  - 品牌欄位從文字輸入框改成下拉選單，選項來自資料庫目前實際存在的 `Product.brand` 相異值。
  - 移除型號（`model`）搜尋欄位（僅從搜尋頁面 UI 移除；後端 `SearchFilters.model` 與 JSON API 維持原樣，不動，因為原始需求的 API 清單未要求移除）。
  - 移除最大/最小漲跌幅（`min_change_percent` / `max_change_percent`）搜尋欄位（同樣僅從搜尋頁面 UI 移除，後端與 API 不動）。
  - 商品名稱/關鍵字搜尋：輸入的字串若包含空白，除了整段字串本身要能比對到「名稱本來就含空白」的商品（例如 `RTX 5070`）之外，用空白分隔出的每個片段也要各自視為「或」（OR）的比對條件（例如輸入 `RTX 5070 IEC` 應該比對到名稱含 `RTX 5070` 或 `RTX` 或 `5070` 或 `IEC` 的商品）。這是後端 `search_products()` 的邏輯改動，會同時影響搜尋頁面與 `/api/products`。
- **商品詳情頁（項目3）：** 頁面最上方的價格表格只顯示：目前價格、歷史最高／最低、漲跌（金額+百分比）。移除「上次價格」列與 7/30/90 天最低/最高列（7/30/90 天的資訊已經可以透過下方價格走勢圖的區間按鈕看到，不需要在表格重複）。
- **價格走勢圖（項目4）：** 移除「套用」按鈕；自訂日期區間的兩個 `<input type="date">` 改成 `change` 事件觸發時就自動重新載入圖表，不需要額外按鈕確認。
- **加入比較（項目5）：**
  - 「加入比較」核取方塊搬到商品詳情頁標題（`<h1>`）旁邊/下方。
  - 勾選只會把目前商品加進一份用瀏覽器 `localStorage`保存的比較清單（不需要登入、不用後端存狀態），**不會自動跳轉頁面**——使用者確認過：「都不跳轉，等到使用者自己想要比較後才點過去那個分頁」。
  - 移除頁面下方原本「選擇同分類商品加入比較」的下拉選單＋按鈕區塊（含對應的 `same_category_products` 後端查詢）。
  - 導覽列（`base.html`）的「商品比較」連結要即時反映目前清單筆數，並把連結導向組好 `ids` 查詢字串的 `/compare?ids=...`（清單為空時導向純 `/compare`）。這個 localStorage 邏輯共用給 `product_detail.html` 的核取方塊使用。
- **既有不可違反的系統限制（沿用專案既有 Global Constraints，本次改動不得破壞）：** 系統執行期間不使用 AI/LLM/Agent 做任何商品判斷或比對；商品身份比對只能用確定性規則（本計畫新增的 `choose_merge_direction` 純粹是「在售優先＋時間新舊＋id 大小」的確定性規則，不是相似度判斷，相似度判斷本身沿用既有的 `SimilarityHint`／`refresh_similarity_hints`，本計畫不改動）；下架商品不可被刪除、只能標記；Undo Merge 必須完全可逆。
- 每個任務都要跑 `uv run pytest -q` 確認全數通過（含既有測試），每個任務各自 commit。

---

### Task 1: 合併方向規則 `choose_merge_direction`

**Files:**
- Modify: `src/coolpc/merging/service.py`
- Test: `tests/merging/test_choose_merge_direction.py`（新檔案）

**Interfaces:**
- Consumes: 無（純函式，只讀 `Product.is_active` / `Product.last_seen_at` / `Product.id`，不觸資料庫）。
- Produces: `choose_merge_direction(a: Product, b: Product) -> tuple[Product, Product]`，回傳 `(source, target)`。Task 3 的批量合併端點會呼叫這個函式決定要把哪個商品當 `merge_products()` 的 `source_id`/`target_id`。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/merging/test_choose_merge_direction.py`：

```python
import datetime
from coolpc.db.models import Product
from coolpc.merging.service import choose_merge_direction


def _product(id_, is_active, last_seen_at):
    p = Product(
        current_name=f"p{id_}", category_id=1, subcategory_id=1, current_price=100,
        is_active=is_active, first_seen_at=last_seen_at, last_seen_at=last_seen_at,
        created_at=last_seen_at,
    )
    p.id = id_
    return p


def test_choose_merge_direction_prefers_active_as_target():
    t = datetime.datetime(2026, 2, 1)
    a = _product(1, is_active=False, last_seen_at=t)
    b = _product(2, is_active=True, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is a
    assert target is b


def test_choose_merge_direction_prefers_active_as_target_reversed_args():
    t = datetime.datetime(2026, 2, 1)
    a = _product(1, is_active=True, last_seen_at=t)
    b = _product(2, is_active=False, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a


def test_choose_merge_direction_prefers_newer_last_seen_when_both_active():
    a = _product(1, is_active=True, last_seen_at=datetime.datetime(2026, 2, 1))
    b = _product(2, is_active=True, last_seen_at=datetime.datetime(2026, 2, 5))
    source, target = choose_merge_direction(a, b)
    assert source is a
    assert target is b


def test_choose_merge_direction_prefers_newer_last_seen_when_both_inactive():
    a = _product(1, is_active=False, last_seen_at=datetime.datetime(2026, 2, 5))
    b = _product(2, is_active=False, last_seen_at=datetime.datetime(2026, 2, 1))
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a


def test_choose_merge_direction_tie_break_by_smaller_id():
    t = datetime.datetime(2026, 2, 1)
    a = _product(5, is_active=True, last_seen_at=t)
    b = _product(9, is_active=True, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/merging/test_choose_merge_direction.py -v`
Expected: `ImportError: cannot import name 'choose_merge_direction'`

- [ ] **Step 3: 實作**

在 `src/coolpc/merging/service.py`，於既有的 `class MergeError(Exception): pass` 之後、`merge_products` 之前，新增：

```python
def choose_merge_direction(a: Product, b: Product) -> tuple[Product, Product]:
    """回傳 (source, target)。這是決定性規則，不做任何名稱/相似度判斷：
    兩商品只有一個仍在上架中，該商品當 target；否則（都上架或都下架）
    以 last_seen_at 較新者當 target；完全同分以 id 較小者當 target。"""
    if a.is_active and not b.is_active:
        target, source = a, b
    elif b.is_active and not a.is_active:
        target, source = b, a
    elif a.last_seen_at != b.last_seen_at:
        target, source = (a, b) if a.last_seen_at > b.last_seen_at else (b, a)
    else:
        target, source = (a, b) if a.id < b.id else (b, a)
    return source, target
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/merging/test_choose_merge_direction.py -v`
Expected: 5 個測試全部 PASS

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過（既有 141 個 + 新增 5 個）

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/merging/service.py tests/merging/test_choose_merge_direction.py
git commit -m "feat(merging): add choose_merge_direction for batch-merge target selection"
```

---

### Task 2: 搜尋關鍵字空白 OR 語意

**Files:**
- Modify: `src/coolpc/search/service.py`
- Test: `tests/search/test_search.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: 無新介面，`SearchFilters.q` 型別不變（`str | None`）。
- Produces: `search_products()` 的比對邏輯改變，供 Task 5（搜尋頁）與既有 `/api/products`（`src/coolpc/public_api/routers/api.py`，本任務不用修改它，它已經呼叫 `search_products`）共用。

- [ ] **Step 1: 寫失敗測試**

在 `tests/search/test_search.py` 尾端新增：

```python
def test_search_by_keyword_with_space_matches_literal_space_in_name():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat, sub, "Synology HAT3300 4TB【限搭NAS主機】", 6890, True, t)
    session.commit()

    # 名稱本身就含空白，"RTX 5070" 整段仍要能比對到；另一個商品的名稱完全
    # 不含 "RTX"、"5070" 這兩個 token（也不含 "RTX 5070" 整段），確保這裡
    # 驗證的是「整段比對」本身有效，不會被下面測試的 OR token 語意混淆。
    results, total = search_products(session, SearchFilters(q="RTX 5070"))
    assert total == 1
    assert "5070" in results[0].current_name


def test_search_by_keyword_with_space_also_means_or():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat, sub, "MSI RTX 5080 GAMING 16G", 28990, True, t)
    _add(session, cat, sub, "Synology DS923+", 15990, True, t)
    session.commit()

    # "RTX 5090" 不是任何商品的完整子字串，但拆成 "RTX" / "5090" 後
    # "RTX" 應該用 OR 語意比對到兩張顯卡（5090 本身查無結果不影響 OR）
    results, total = search_products(session, SearchFilters(q="RTX 5090"))
    names = {p.current_name for p in results}
    assert total == 2
    assert "ASUS RTX 5070 PRIME 12G" in names
    assert "MSI RTX 5080 GAMING 16G" in names
    assert "Synology DS923+" not in names
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/search/test_search.py -v -k space`
Expected: `test_search_by_keyword_with_space_also_means_or` FAIL（`total == 0`，因為目前是單一 LIKE `%RTX 5090%` 整段比對，查無結果）；`test_search_by_keyword_with_space_matches_literal_space_in_name` 這一個原本就會 PASS（現有邏輯本來就是整段 LIKE），先確認另一個真的紅了即可。

- [ ] **Step 3: 實作**

修改 `src/coolpc/search/service.py`：

```python
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import or_
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName
```

（新增 `from sqlalchemy import or_` 這一行）

把 `search_products` 裡的這段：

```python
    if filters.q:
        matched_ids = [
            row[0] for row in
            session.query(ProductName.product_id)
            .filter(ProductName.name.like(f"%{filters.q}%"))
            .distinct()
            .all()
        ]
        if not matched_ids:
            return [], 0
        query = query.filter(Product.id.in_(matched_ids))
```

改成：

```python
    if filters.q:
        # 空白分隔的每個片段各自視為 OR 條件，同時保留整段字串本身的比對
        # （名稱本來就含空白時，例如「RTX 5070」，仍要能整段比對到）。
        tokens = filters.q.split()
        patterns = {filters.q, *tokens}
        matched_ids = [
            row[0] for row in
            session.query(ProductName.product_id)
            .filter(or_(*[ProductName.name.like(f"%{p}%") for p in patterns]))
            .distinct()
            .all()
        ]
        if not matched_ids:
            return [], 0
        query = query.filter(Product.id.in_(matched_ids))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/search/test_search.py -v`
Expected: 全部 PASS（含既有的中文子字串測試，確認沒有 regression）

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/search/service.py tests/search/test_search.py
git commit -m "feat(search): whitespace in keyword query means OR across tokens"
```

---

### Task 3: 合併商品候選頁——核取方塊 + 批量合併/批量忽略

**Files:**
- Modify: `src/coolpc/admin_api/routers/similarity.py`
- Modify: `src/coolpc/admin_api/templates/similarity_hints.html`
- Test: `tests/admin_api/test_similarity_hints.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: `choose_merge_direction(a, b) -> (source, target)`（Task 1，`from coolpc.merging.service import choose_merge_direction, merge_products, MergeError`）。
- Produces: `POST /similarity-hints/batch-merge`、`POST /similarity-hints/batch-dismiss`（both 303 redirect 回 `/similarity-hints`），供 Task 9 的手動驗證使用。

- [ ] **Step 1: 寫失敗測試**

`tests/admin_api/test_similarity_hints.py` 檔頭目前是：
`from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint`
——新測試會用到 `MergeLog`，請把這行改成：
`from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint, MergeLog`

然後在檔案尾端新增：

```python
def test_batch_merge_hints_merges_selected_pairs_and_dismisses_their_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="舊名稱下架商品",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="新名稱在售商品",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.9,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id, a_id, b_id = hint.id, a.id, b.id

    resp = client.post("/similarity-hints/batch-merge", data={"hint_ids": [hint_id]},
                        follow_redirects=False)
    assert resp.status_code == 303

    with Session_() as session:
        a_after = session.get(Product, a_id)
        b_after = session.get(Product, b_id)
        # a 已下架、b 仍在售 -> a 是 source（被合併掉）、b 是 target（保留）
        assert a_after.merged_into_id == b_id
        assert b_after.merged_into_id is None
        hint_after = session.get(SimilarityHint, hint_id)
        assert hint_after.dismissed is True
        logs = session.query(MergeLog).filter_by(source_product_id=a_id, target_product_id=b_id).all()
        assert len(logs) == 1


def test_batch_dismiss_hints_dismisses_selected_without_merging():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品A獨特字串批量忽略",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串批量忽略",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id, a_id, b_id = hint.id, a.id, b.id

    resp = client.post("/similarity-hints/batch-dismiss", data={"hint_ids": [hint_id]},
                        follow_redirects=False)
    assert resp.status_code == 303

    with Session_() as session:
        a_after = session.get(Product, a_id)
        b_after = session.get(Product, b_id)
        assert a_after.merged_into_id is None
        assert b_after.merged_into_id is None

    after = client.get("/similarity-hints")
    assert "商品A獨特字串批量忽略" not in after.text


def test_similarity_hints_page_has_checkbox_and_no_per_row_action_column():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試A",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試B",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id = hint.id

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert f'name="hint_ids" value="{hint_id}"' in resp.text
    assert "批量合併" in resp.text
    assert "批量忽略" in resp.text
    # 舊版每列一個「不是同一商品，忽略」的獨立表單已移除
    assert "不是同一商品，忽略" not in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/admin_api/test_similarity_hints.py -v`
Expected: 三個新測試都 FAIL（`404 Not Found`，因為 `/similarity-hints/batch-merge`、`/similarity-hints/batch-dismiss` 路由還不存在；第三個測試因為 `hint_ids` checkbox 和「批量」字樣還不存在而 FAIL）

- [ ] **Step 3: 實作**

修改 `src/coolpc/admin_api/routers/similarity.py`：

```python
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.db.models import Product, SimilarityHint
from coolpc.matching.similarity import refresh_similarity_hints
from coolpc.merging.service import choose_merge_direction, merge_products, MergeError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/similarity-hints")
def similarity_hints_page(request: Request, message: str | None = None,
                           session: Session = Depends(get_session)):
    hints = (
        session.query(SimilarityHint)
        .filter(SimilarityHint.dismissed.is_(False))
        .order_by(SimilarityHint.score.desc())
        .limit(100)
        .all()
    )
    rows = []
    for h in hints:
        pa = session.get(Product, h.product_a_id)
        pb = session.get(Product, h.product_b_id)
        if pa is None or pb is None or pa.merged_into_id is not None or pb.merged_into_id is not None:
            continue
        rows.append({"hint": h, "a": pa, "b": pb})
    return templates.TemplateResponse(request, "similarity_hints.html", {"rows": rows, "message": message})


@router.post("/similarity-hints/refresh")
def refresh_hints(session: Session = Depends(get_session)):
    refresh_similarity_hints(session)
    session.commit()
    return RedirectResponse(url="/similarity-hints", status_code=303)


@router.post("/similarity-hints/{hint_id}/dismiss")
def dismiss_hint(hint_id: int, session: Session = Depends(get_session)):
    hint = session.get(SimilarityHint, hint_id)
    if hint is not None:
        hint.dismissed = True
        session.commit()
    return RedirectResponse(url="/similarity-hints", status_code=303)


@router.post("/similarity-hints/batch-merge")
async def batch_merge_hints(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    hint_ids = [int(v) for v in form.getlist("hint_ids")]
    merged = 0
    skipped = 0
    for hint_id in hint_ids:
        hint = session.get(SimilarityHint, hint_id)
        if hint is None:
            skipped += 1
            continue
        pa = session.get(Product, hint.product_a_id)
        pb = session.get(Product, hint.product_b_id)
        if pa is None or pb is None or pa.merged_into_id is not None or pb.merged_into_id is not None:
            skipped += 1
            continue
        source, target = choose_merge_direction(pa, pb)
        try:
            merge_products(session, source.id, target.id)
            hint.dismissed = True
            merged += 1
        except MergeError:
            skipped += 1
    session.commit()
    qs = urlencode({"message": f"已合併 {merged} 組，略過 {skipped} 組"})
    return RedirectResponse(url=f"/similarity-hints?{qs}", status_code=303)


@router.post("/similarity-hints/batch-dismiss")
async def batch_dismiss_hints(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    hint_ids = [int(v) for v in form.getlist("hint_ids")]
    count = 0
    for hint_id in hint_ids:
        hint = session.get(SimilarityHint, hint_id)
        if hint is not None:
            hint.dismissed = True
            count += 1
    session.commit()
    qs = urlencode({"message": f"已忽略 {count} 組"})
    return RedirectResponse(url=f"/similarity-hints?{qs}", status_code=303)
```

修改 `src/coolpc/admin_api/templates/similarity_hints.html` 全檔內容為：

```html
{% extends "base.html" %}
{% block title %}合併商品 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>合併商品</h1>
{% if message %}<p style="color:#15803d">{{ message }}</p>{% endif %}
<form method="post" action="/similarity-hints/refresh">
  <button type="submit">重新計算相似度候選</button>
</form>
<p>以下為系統依名稱相似度找出的候選。勾選後可「批量合併」（自動以仍在上架中、或最近更新較新的商品當保留的主商品），或「批量忽略」（標記為不是同一商品，之後不再出現）。</p>
<form method="post" id="hintsForm">
  <button type="submit" formaction="/similarity-hints/batch-merge">批量合併</button>
  <button type="submit" formaction="/similarity-hints/batch-dismiss">批量忽略（不是同一商品）</button>
  <table>
    <thead><tr><th></th><th>相似度</th><th>商品 A</th><th>商品 B</th></tr></thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td><input type="checkbox" name="hint_ids" value="{{ row.hint.id }}"></td>
        <td>{{ "%.0f"|format(row.hint.score * 100) }}%</td>
        <td>#{{ row.a.id }} {{ row.a.current_name }}{% if not row.a.is_active %}（已下架）{% endif %}</td>
        <td>#{{ row.b.id }} {{ row.b.current_name }}{% if not row.b.is_active %}（已下架）{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</form>
{% endblock %}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/admin_api/test_similarity_hints.py -v`
Expected: 全部 PASS（含既有 3 個 + 新增 3 個）

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/admin_api/routers/similarity.py src/coolpc/admin_api/templates/similarity_hints.html tests/admin_api/test_similarity_hints.py
git commit -m "feat(admin): batch merge/dismiss from similarity-hints candidate list"
```

---

### Task 4: 手動合併頁——商品名稱搜尋（ID 作為備用）

**Files:**
- Modify: `src/coolpc/admin_api/routers/products.py`
- Modify: `src/coolpc/admin_api/templates/merge.html`
- Modify: `src/coolpc/admin_api/templates/base.html`
- Test: `tests/admin_api/test_merge_page.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: `search_products(session, SearchFilters(...))`（既有，Task 2 已改良其 `q` 語意，這裡直接沿用）。
- Produces: `GET /products/search-json?q=...` 回傳 `list[dict]`，每個 dict 為 `{"id": int, "name": str, "price": int, "is_active": bool}`，供 `merge.html` 的前端 JS 使用；本任務之外沒有其他任務依賴此端點。

- [ ] **Step 1: 寫失敗測試**

在 `tests/admin_api/test_merge_page.py` 尾端新增（若檔案已有 `_make_client` 之類的 helper，沿用既有寫法；若沒有 helper，比照 `tests/admin_api/test_similarity_hints.py` 的 `_make_client` 寫一份一樣的）：

```python
def test_product_search_json_returns_matches_by_name():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 搜尋測試",
                   current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        p_id = p.id

    resp = client.get("/products/search-json", params={"q": "搜尋測試"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == p_id
    assert data[0]["name"] == "ASUS RTX 5070 搜尋測試"
    assert data[0]["price"] == 18990
    assert data[0]["is_active"] is True


def test_product_search_json_empty_query_returns_empty_list():
    client, _Session_ = _make_client()
    resp = client.get("/products/search-json", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


def test_merge_page_has_search_inputs_and_fallback_id_inputs():
    client, _Session_ = _make_client()
    resp = client.get("/merge")
    assert resp.status_code == 200
    assert 'id="sourceSearch"' in resp.text
    assert 'id="targetSearch"' in resp.text
    assert 'name="source_id"' in resp.text
    assert 'name="target_id"' in resp.text
    assert "備用" in resp.text
```

`tests/admin_api/test_merge_page.py` 檔頭已經有 `import datetime`、`ProductName`、`_make_client`（第 15-30 行），直接沿用即可，不需要另外補 import。

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/admin_api/test_merge_page.py -v`
Expected: 前兩個新測試 FAIL（`404 Not Found`，`/products/search-json` 還不存在）；第三個測試 FAIL（`sourceSearch` 等字樣還不存在於 `merge.html`）

- [ ] **Step 3: 實作**

在 `src/coolpc/admin_api/routers/products.py`，於既有 `product_search` 路由之後新增：

```python
@router.get("/products/search-json")
def product_search_json(q: str = "", session: Session = Depends(get_session)):
    if not q.strip():
        return []
    filters = SearchFilters(q=q, limit=10)
    products, _total = search_products(session, filters)
    return [
        {"id": p.id, "name": p.current_name, "price": p.current_price, "is_active": p.is_active}
        for p in products
    ]
```

修改 `src/coolpc/admin_api/templates/merge.html` 全檔內容為：

```html
{% extends "base.html" %}
{% block title %}手動合併 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>手動合併</h1>
{% if message %}<p style="color:#15803d">{{ message }}</p>{% endif %}
{% if error %}<p style="color:#b91c1c">{{ error }}</p>{% endif %}

<form method="post" action="/merge">
  <p>
    來源商品（將被合併，舊名稱仍可搜尋）：<br>
    <input type="text" id="sourceSearch" placeholder="輸入商品名稱搜尋...">
    <div id="sourceResults"></div>
    <span id="sourceSelected"></span><br>
    或直接輸入商品ID（備用）：<input type="number" name="source_id" id="sourceId" required>
  </p>
  <p>
    目標商品（合併後保留的主商品，請選擇目前仍持續更新的商品）：<br>
    <input type="text" id="targetSearch" placeholder="輸入商品名稱搜尋...">
    <div id="targetResults"></div>
    <span id="targetSelected"></span><br>
    或直接輸入商品ID（備用）：<input type="number" name="target_id" id="targetId" required>
  </p>
  <button type="submit">合併</button>
</form>

<h2>合併紀錄</h2>
<table>
  <thead><tr><th>時間</th><th>來源</th><th>目標</th><th>狀態</th><th>操作</th></tr></thead>
  <tbody>
    {% for row in log_rows %}
    <tr>
      <td>{{ row.log.merged_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td>{{ row.source.current_name if row.source else "?" }} (#{{ row.log.source_product_id }})</td>
      <td>{{ row.target.current_name if row.target else "?" }} (#{{ row.log.target_product_id }})</td>
      <td>{{ "已復原" if row.log.undone_at else "已合併" }}</td>
      <td>
        {% if not row.log.undone_at %}
        <form method="post" action="/merge/{{ row.log.id }}/undo" style="display:inline">
          <button type="submit">Undo</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<script>
function setupProductSearch(searchInputId, resultsId, idFieldId, selectedId) {
  const searchInput = document.getElementById(searchInputId);
  const results = document.getElementById(resultsId);
  const idField = document.getElementById(idFieldId);
  const selected = document.getElementById(selectedId);
  let timer;
  searchInput.addEventListener('input', () => {
    clearTimeout(timer);
    const q = searchInput.value.trim();
    if (!q) { results.innerHTML = ''; return; }
    timer = setTimeout(async () => {
      const resp = await fetch(`/products/search-json?q=${encodeURIComponent(q)}`);
      const items = await resp.json();
      results.innerHTML = '';
      items.forEach(item => {
        const div = document.createElement('div');
        div.textContent = `#${item.id} ${item.name}（$${item.price}${item.is_active ? '' : '・已下架'}）`;
        div.style.cursor = 'pointer';
        div.style.padding = '4px';
        div.style.borderBottom = '1px solid #e5e7eb';
        div.addEventListener('click', () => {
          idField.value = item.id;
          selected.textContent = `已選擇：${item.name} (#${item.id})`;
          results.innerHTML = '';
          searchInput.value = '';
        });
        results.appendChild(div);
      });
    }, 300);
  });
}
setupProductSearch('sourceSearch', 'sourceResults', 'sourceId', 'sourceSelected');
setupProductSearch('targetSearch', 'targetResults', 'targetId', 'targetSelected');
</script>
{% endblock %}
```

修改 `src/coolpc/admin_api/templates/base.html` 的 `<header>` 區塊，把：

```html
<header>
  <a href="/">抓取狀態</a>
  <a href="/html-archive">原始 HTML</a>
  <a href="/products">商品搜尋</a>
  <a href="/similarity-hints">可能需要合併</a>
</header>
```

改成：

```html
<header>
  <a href="/">抓取狀態</a>
  <a href="/html-archive">原始 HTML</a>
  <a href="/products">商品搜尋</a>
  <a href="/similarity-hints">合併商品</a>
  <a href="/merge">手動合併</a>
</header>
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/admin_api/test_merge_page.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/admin_api/routers/products.py src/coolpc/admin_api/templates/merge.html src/coolpc/admin_api/templates/base.html tests/admin_api/test_merge_page.py
git commit -m "feat(admin): name-search product picker on manual merge page, ID as fallback"
```

---

### Task 5: 搜尋頁面 UI 調整

**Files:**
- Modify: `src/coolpc/public_api/routers/pages.py`
- Modify: `src/coolpc/public_api/templates/search.html`
- Test: `tests/public_api/test_search_page.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: 無新介面。
- Produces: 無新介面（純頁面調整），後續任務不依賴本任務的內部細節。

- [ ] **Step 1: 寫失敗測試**

在 `tests/public_api/test_search_page.py` 尾端新增：

```python
def test_search_page_brand_is_dropdown_populated_from_existing_brands():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070",
                   brand="ASUS", current_price=18990, is_active=True,
                   first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert '<select name="brand"' in resp.text
    assert 'type="text" name="brand"' not in resp.text
    assert '<option value="ASUS"' in resp.text


def test_search_page_removed_fields_are_gone():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="category_id"' not in resp.text
    assert 'name="model"' not in resp.text
    assert 'name="min_change_percent"' not in resp.text
    assert 'name="max_change_percent"' not in resp.text
    assert 'name="subcategory_id"' in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_search_page.py -v -k "brand_is_dropdown or removed_fields"`
Expected: 兩個新測試都 FAIL（目前品牌是 `<input type="text" name="brand">`，`category_id`/`model`/`min_change_percent`/`max_change_percent` 都還在頁面上）

- [ ] **Step 3: 實作**

修改 `src/coolpc/public_api/routers/pages.py` 的 `search_page` 函式，在 `subcategory_rows` 查詢之後、`return templates.TemplateResponse(...)` 之前，新增品牌清單查詢：

```python
    brands = [
        row[0] for row in
        session.query(Product.brand).filter(Product.brand.isnot(None)).distinct()
        .order_by(Product.brand).all()
    ]
```

並在 `return templates.TemplateResponse(request, "search.html", {...})` 的 context dict 裡新增一個 key：`"brands": brands,`（放在 `"subcategories": subcategories,` 那一行之後即可）。

修改 `src/coolpc/public_api/templates/search.html` 的 `<form class="filters">` 區塊，把：

```html
  <select name="category_id">
    <option value="">全部分類</option>
    {% for c in categories %}
    <option value="{{ c.id }}" {% if query.category_id == c.id %}selected{% endif %}>{{ c.name }}</option>
    {% endfor %}
  </select>
  <select name="subcategory_id">
    <option value="">全部子分類</option>
    {% for sc in subcategories %}
    <option value="{{ sc.id }}" {% if query.subcategory_id == sc.id %}selected{% endif %}>{{ sc.label }}</option>
    {% endfor %}
  </select>
  <input type="text" name="brand" placeholder="品牌" value="{{ query.brand or '' }}">
  <input type="text" name="model" placeholder="型號" value="{{ query.model or '' }}">
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
  <input type="number" step="0.1" name="min_change_percent" placeholder="最小漲跌幅 %" value="{{ query.min_change_percent if query.min_change_percent is not none else '' }}">
  <input type="number" step="0.1" name="max_change_percent" placeholder="最大漲跌幅 %" value="{{ query.max_change_percent if query.max_change_percent is not none else '' }}">
```

改成：

```html
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
```

（`categories` context 變數不再被 `search.html` 使用，但 `search_page` 仍可繼續傳入不影響功能——保留 `pages.py` 現有的 `"categories": session.query(Category).order_by(Category.name).all(),` 那一行不動，避免動到與本任務無關的程式碼。）

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_search_page.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/public_api/routers/pages.py src/coolpc/public_api/templates/search.html tests/public_api/test_search_page.py
git commit -m "feat(public): merge category/subcategory filter, brand dropdown, drop model + change-percent fields from search page"
```

---

### Task 6: 商品詳情頁——價格表格簡化、走勢圖自動更新、比較改成勾選加入清單

**Files:**
- Modify: `src/coolpc/public_api/routers/pages.py`
- Modify: `src/coolpc/public_api/templates/product_detail.html`
- Modify: `src/coolpc/public_api/templates/base.html`
- Test: `tests/public_api/test_product_detail_page.py`（既有檔案，新增測試函式）

**Interfaces:**
- Consumes: 無新介面。
- Produces: 全域 JS 物件 `window.coolpcCompare`（定義在 `base.html`，方法：`has(id)`、`add(id)`、`remove(id)`），供 `product_detail.html` 使用；`compare.html`（本計畫不修改）不受影響，因為它仍然只認 URL 上的 `ids` query string，本任務不改它的行為。

- [ ] **Step 1: 寫失敗測試**

在 `tests/public_api/test_product_detail_page.py` 尾端新增：

```python
def test_product_detail_price_table_shows_only_current_high_low_change():
    client, Session_ = _make_client()
    t1 = datetime.datetime(2026, 1, 1)
    t2 = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="價格表格簡化測試",
                   current_price=18990, is_active=True, first_seen_at=t1, last_seen_at=t2, created_at=t1)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t1, last_seen_at=t2))
        snap = ScrapeSnapshot(fetched_at=t1, scrape_type="scheduled", status="success", created_at=t1)
        session.add(snap)
        session.flush()
        session.add(PriceHistory(product_id=p.id, price=20000, scraped_at=t1, snapshot_id=snap.id))
        session.add(PriceHistory(product_id=p.id, price=18990, scraped_at=t2, snapshot_id=snap.id))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert "上次價格" not in resp.text
    assert "7 天最低" not in resp.text
    assert "30 天最低" not in resp.text
    assert "90 天最低" not in resp.text
    assert "歷史最低" in resp.text
    assert "漲跌" in resp.text


def test_product_detail_chart_has_no_apply_button_and_uses_change_listener():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="走勢圖自動更新測試",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert 'id="rangeCustom"' not in resp.text
    assert ">套用<" not in resp.text
    assert "rangeStart" in resp.text and "'change'" in resp.text


def test_product_detail_compare_checkbox_replaces_same_category_dropdown():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較勾選測試",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert 'id="compareCheckbox"' in resp.text
    assert 'id="compareAdd"' not in resp.text
    assert "addCompare(" not in resp.text


def test_base_html_exposes_shared_compare_cart_helper():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "coolpcCompare" in resp.text
    assert 'id="compareNavLink"' in resp.text
```

`tests/public_api/test_product_detail_page.py` 檔頭目前是：
`from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory`
——有 `PriceHistory` 但沒有 `ScrapeSnapshot`（上面第一個新測試會用到），請把這行改成：
`from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory, ScrapeSnapshot`

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_product_detail_page.py -v`
Expected: 四個新測試都 FAIL（目前的表格仍有「上次價格」「7/30/90 天」列；仍有 `rangeCustom` 套用按鈕；仍是 `compareAdd` 下拉選單；`base.html` 目前沒有 `coolpcCompare`）

- [ ] **Step 3: 實作**

修改 `src/coolpc/public_api/routers/pages.py` 的 `product_detail_page` 函式，刪除這一段（不再需要，畫面已經不用）：

```python
    same_category = (
        session.query(Product)
        .filter(Product.category_id == product.category_id, Product.id != product.id,
                Product.merged_into_id.is_(None))
        .order_by(Product.last_seen_at.desc())
        .limit(20)
        .all()
    )
```

並把 `return templates.TemplateResponse(...)` 的 context dict 裡的 `"same_category_products": same_category,` 那一行整行刪除。

修改 `src/coolpc/public_api/templates/product_detail.html` 全檔內容為：

```html
{% extends "base.html" %}
{% block title %}{{ product.current_name }} - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<h1>{{ product.current_name }}
  <label style="font-size:14px;font-weight:normal;margin-left:12px;">
    <input type="checkbox" id="compareCheckbox"> 加入比較
  </label>
</h1>
<p>分類：{{ category.name }} / {{ subcategory.name }}　狀態：{{ "在售" if product.is_active else "已下架" }}</p>
<p>歷史名稱：{{ historical_names | join("、") }}</p>
<p>第一次出現：{{ product.first_seen_at.strftime("%Y-%m-%d %H:%M") }}　最後一次出現：{{ product.last_seen_at.strftime("%Y-%m-%d %H:%M") }}</p>

<table>
  <tr><th>目前價格</th><td>${{ "{:,}".format(product.current_price) }}</td></tr>
  <tr><th>歷史最低 / 最高</th><td>${{ "{:,}".format(stats.all_time_low) }} / ${{ "{:,}".format(stats.all_time_high) }}</td></tr>
  <tr><th>漲跌</th><td>{% if stats.change_amount %}{{ "%+d"|format(stats.change_amount) }} ({{ "%.1f"|format(stats.change_percent) }}%){% else %}-{% endif %}</td></tr>
</table>

<h2>價格走勢</h2>
<div>
  <button data-range="7">7天</button>
  <button data-range="30">30天</button>
  <button data-range="90">90天</button>
  <button data-range="all">全部</button>
  自訂：<input type="date" id="rangeStart"> ~ <input type="date" id="rangeEnd">
</div>
<canvas id="priceChart" height="100"></canvas>

<h2>歷史價格列表</h2>
<table>
  <thead><tr><th>時間</th><th>價格</th></tr></thead>
  <tbody>
    {% for h in history %}
    <tr><td>{{ h.scraped_at.strftime("%Y-%m-%d %H:%M") }}</td><td>${{ "{:,}".format(h.price) }}</td></tr>
    {% endfor %}
  </tbody>
</table>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
const productId = {{ product.id }};
let priceChart;

async function loadPrices(params) {
  const url = new URL(`/api/products/${productId}/prices`, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v) url.searchParams.set(k, v);
  }
  const resp = await fetch(url);
  const data = await resp.json();
  const labels = data.map(d => d.scraped_at);
  const prices = data.map(d => d.price);
  if (priceChart) {
    priceChart.data.labels = labels;
    priceChart.data.datasets[0].data = prices;
    priceChart.update();
  } else {
    const ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: [{ label: '價格 (TWD)', data: prices, borderColor: '#2563eb', fill: false }] },
      options: {
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
    loadPrices(range === 'all' ? {} : { days: range });
  });
});

function loadCustomRange() {
  const startVal = document.getElementById('rangeStart').value;
  const endVal = document.getElementById('rangeEnd').value;
  if (!startVal && !endVal) return;
  // <input type=date> 只給日期，結束日要補到當天 23:59:59 才不會漏掉當天資料
  loadPrices({
    start: startVal ? `${startVal}T00:00:00` : '',
    end: endVal ? `${endVal}T23:59:59` : '',
  });
}
document.getElementById('rangeStart').addEventListener('change', loadCustomRange);
document.getElementById('rangeEnd').addEventListener('change', loadCustomRange);

const compareCheckbox = document.getElementById('compareCheckbox');
compareCheckbox.checked = window.coolpcCompare.has(productId);
compareCheckbox.addEventListener('change', () => {
  if (compareCheckbox.checked) {
    window.coolpcCompare.add(productId);
  } else {
    window.coolpcCompare.remove(productId);
  }
});

loadPrices({ days: 30 });
</script>
{% endblock %}
```

修改 `src/coolpc/public_api/templates/base.html`，把：

```html
<header>
  <a href="/">商品搜尋</a>
  <a href="/compare">商品比較</a>
</header>
<main>
{% block content %}{% endblock %}
</main>
</body>
</html>
```

改成：

```html
<header>
  <a href="/">商品搜尋</a>
  <a href="/compare" id="compareNavLink">商品比較</a>
</header>
<main>
{% block content %}{% endblock %}
</main>
<script>
window.coolpcCompare = {
  _key: 'coolpc_compare_ids',
  _read() {
    try {
      const raw = localStorage.getItem(this._key);
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  },
  _write(ids) {
    try { localStorage.setItem(this._key, JSON.stringify(ids)); } catch (e) {}
  },
  has(id) { return this._read().includes(id); },
  add(id) {
    const ids = this._read();
    if (!ids.includes(id)) { ids.push(id); this._write(ids); }
    this._updateNav();
  },
  remove(id) {
    const ids = this._read().filter(x => x !== id);
    this._write(ids);
    this._updateNav();
  },
  _updateNav() {
    const link = document.getElementById('compareNavLink');
    if (!link) return;
    const ids = this._read();
    link.textContent = ids.length ? `商品比較 (${ids.length})` : '商品比較';
    link.href = ids.length ? `/compare?ids=${ids.join(',')}` : '/compare';
  },
};
window.coolpcCompare._updateNav();
</script>
</body>
</html>
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_product_detail_page.py tests/public_api/test_search_page.py -v`
Expected: 全部 PASS（也順便跑一次搜尋頁測試，確認 `base.html` 的改動沒有讓它壞掉）

- [ ] **Step 5: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/public_api/routers/pages.py src/coolpc/public_api/templates/product_detail.html src/coolpc/public_api/templates/base.html tests/public_api/test_product_detail_page.py
git commit -m "feat(public): simplify price table, auto-update chart on range change, compare via checkbox + localStorage cart"
```

---

### Task 7: 全套驗證、重啟服務、收尾

**Files:** 無程式碼變更（純驗證與部署動作）。

**Interfaces:** 無。

- [ ] **Step 1: 跑全套測試**

Run: `uv run pytest -q`
Expected: 全數通過（Task 1-6 新增的測試 + 既有全部測試）

- [ ] **Step 2: 用真實資料庫手動驗證每個改動點**

服務啟動前先確認目前是否已有 uvicorn 進程在跑（本專案先前已手動啟動過 33690/33691），若有，先停掉再用修改後的程式碼重啟：

```bash
pkill -f "uvicorn coolpc.public_api" || true
pkill -f "uvicorn coolpc.admin_api" || true
sleep 1
cd /home/xthybot/coolpc-price-history
nohup uv run uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690 > /tmp/public_api.log 2>&1 &
nohup uv run uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691 > /tmp/admin_api.log 2>&1 &
sleep 3
```

用 `curl` 對照 Global Constraints 逐項確認（用資料庫裡實際存在的商品 id，不要憑空編號）：

- `curl -s http://127.0.0.1:33690/ | grep -c 'name="category_id"'` → 應為 `0`
- `curl -s http://127.0.0.1:33690/ | grep -c '<select name="brand"'` → 應為 `1`
- `curl -s http://127.0.0.1:33690/products/1 | grep -c '上次價格'` → 應為 `0`
- `curl -s http://127.0.0.1:33690/products/1 | grep -c 'compareCheckbox'` → 應為 `1`
- `curl -s http://127.0.0.1:33691/similarity-hints | grep -c 'hint_ids'` → 若目前有候選商品，應 ≥ `1`；若候選清單是空的（可能之前已經被合併/忽略過），先 `curl -s -X POST http://127.0.0.1:33691/similarity-hints/refresh` 重新計算一次再檢查
- `curl -s http://127.0.0.1:33691/merge | grep -c 'sourceSearch'` → 應為 `1`

若有任何一項不符預期，回頭檢查對應 Task 的檔案是否漏改，修正後重新整個重啟服務再驗證一次，不要跳過這一步直接進到下一步。

- [ ] **Step 3: Push（本任務不需要額外 commit，Task 1-6 已各自 commit 過）**

```bash
git log --oneline -6
git push
```

- [ ] **Step 4: 回報使用者**

服務保持在 `0.0.0.0:33690`（公開查詢）與 `0.0.0.0:33691`（管理介面）運行，供使用者實際點擊測試。
