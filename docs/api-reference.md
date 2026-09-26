# 公開 JSON API 參考

服務：`public_api`（`0.0.0.0:33690`），路由定義於
`src/coolpc/public_api/routers/api.py`，前綴一律是 `/api`。無需登入或
API Key。所有回應皆為 JSON，schema 定義於 `src/coolpc/public_api/schemas.py`。

已被合併掉的商品（`merged_into_id` 不為 `None`）不會出現在商品列表或
自動完成；單一商品詳細/價格歷史/統計及比較端點遇到該 id 回 `404`。
批次走勢端點則忽略不存在或已合併的 id，不因個別 id 回 `404`。

## `GET /api/categories`

回傳全部分類，依 `sort_order`（人工顯示排序）再依名稱排序。

回應：`CategoryOut[]`

```json
[{ "id": 12, "name": "GPU 顯示卡" }]
```

> 注意：這裡的 `name` 欄位實際回傳的是 `Category.label`（`display_name or
> name`，即畫面顯示名稱），不是資料庫的原始 `Category.name`——欄位命名沿用
> 早期版本，語意上等同「顯示用名稱」，非欄位字面意思。

## `GET /api/products`

商品列表查詢，公開搜尋首頁背後也是呼叫這個邏輯（頁面走 `/`，這裡是給外部
呼叫的 JSON 版本）。

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `q` | string | 無 | 搜尋關鍵字，空白分隔多個 token；語意見 [`docs/search-semantics.md`](search-semantics.md) |
| `q_match` | string | `"and"` | 只有精確等於 `"and"` 走 AND；`"or"` 及任何其他字串走 OR，沒有值域驗證。詳見 [`docs/search-semantics.md`](search-semantics.md) |
| `category_id` | int | 無 | |
| `subcategory_id` | int | 無 | |
| `brand` | string | 無 | 精確等值比對 |
| `model` | string | 無 | 部分比對（`LIKE %model%`） |
| `min_price` / `max_price` | int | 無 | |
| `is_active` | bool | 無 | |
| `sort` | string | `last_seen_desc` | 見 [`docs/search-semantics.md`](search-semantics.md#排序) |
| `limit` | int | `50` | 上限 `20000` |
| `offset` | int | `0` | |

所有 `int`/`bool`/`float` 型的可選參數（`category_id`、`subcategory_id`、
`min_price`、`max_price`、`is_active` 等）接受空字串（`?is_active=`）視同
未指定，不會回 `422`（見 `src/coolpc/query_types.py` 的 `OptionalInt` /
`OptionalBool` / `OptionalFloat`）。

回應：`ProductListPage`

```json
{
  "items": [{
    "id": 123,
    "current_name": "ASUS RTX 5070 PRIME 12G",
    "category_name": "GPU 顯示卡",
    "subcategory_name": "NVIDIA",
    "current_price": 18990,
    "previous_price": 17990,
    "change_amount": 1000,
    "change_percent": 5.56,
    "low_30d": 17990,
    "high_30d": 18990,
    "is_active": true,
    "last_seen_at": "2026-02-01T21:40:00"
  }],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

`change_amount`/`change_percent`/`low_30d`/`high_30d` 皆為即時從
`price_history` 計算（`compute_product_stats`），非資料庫欄位快取值；商品
無足夠歷史資料時對應欄位為 `null`。

列表與下方自動完成均排除 `current_price = 1` 的項目；管理後台搜尋保留。
名稱及 `model` 的 `LIKE` 篩選不逸出 `%`、`_`，萬用字元行為見
[`docs/search-semantics.md`](search-semantics.md#sql-like-萬用字元)。

## `GET /api/products/autocomplete`

精確挑選單一商品用的自動完成端點（給前端下拉選單/chip 挑選器使用），
**永遠是 AND 語意、不退回 OR、不限制結果筆數**——見
[`docs/search-semantics.md`](search-semantics.md#自動完成--精確挑選search_products_and)。

| 參數 | 型別 | 說明 |
|---|---|---|
| `q` | string | 空字串或省略時直接回傳空結果，不查詢資料庫 |

回應格式同 `ProductListPage`。

## `GET /api/products/sparklines?ids=1,2,3`

批次回傳多個商品近期的價格點，格式為 `{商品 id 字串: [價格...]}`（只有
價格數字，沒有時間戳）。這個端點原本是為了搜尋結果列表的迷你走勢圖而
新增，該走勢圖後來從搜尋頁移除了，但端點本身作為公開 API 的一部分繼續
保留、未被撤下。

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `ids` | string | `""` | 逗號分隔的商品 id；空字串或全部無效直接回傳 `{}`，不查詢資料庫。一次最多 100 個，超過回 `400`（搜尋頁「全部顯示」可以選到上萬筆，沒有這個上限的話一次請求就會拉出過量走勢資料） |
| `days` | int | `30` | 只回傳最近幾天的價格點（`1` ～ `3650`） |

已被合併掉、或不存在的 id 會靜靜被忽略（不會出現在回傳結果的 key
裡），不會因為其中一個 id 無效就讓整個請求失敗。若個別商品在該時間範圍內
的資料點少於 2 筆（不足以畫出一條線），會補取其合併群組各成員最後最多
32 筆歷史價格，再取樣為最多 32 點；已有的近期點也會保留。

```json
{ "123": [18990, 18990, 17990], "456": [4290, 4290] }
```

## `GET /api/products/{id}`

單一商品完整詳細資料。商品不存在或已被合併掉回 `404`。

回應：`ProductDetail`

```json
{
  "id": 123,
  "current_name": "ASUS RTX 5070 PRIME 12G",
  "historical_names": ["ASUS RTX 5070 PRIME 12G"],
  "category_name": "GPU 顯示卡",
  "subcategory_name": "NVIDIA",
  "current_price": 18990,
  "previous_price": 17990,
  "change_amount": 1000,
  "change_percent": 5.56,
  "created_at": "2026-01-15T10:00:00",
  "last_seen_at": "2026-02-01T21:40:00",
  "is_active": true,
  "stats": {
    "current_price": 18990,
    "previous_price": 17990,
    "change_amount": 1000,
    "change_percent": 5.56,
    "low_7d": 17990, "high_7d": 18990,
    "low_30d": 17990, "high_30d": 18990,
    "low_90d": 17990, "high_90d": 18990,
    "all_time_low": 16990, "all_time_high": 18990
  }
}
```

`created_at` 為此商品第一次被抓到的估價時間（原本另有一個語意相同的
`first_seen_at` 欄位，已於 migration `0007_drop_product_first_seen_at`
移除，這裡從 `created_at` 讀取，見
[`docs/database-schema.md`](database-schema.md#已移除的欄位請勿重新加回)）。

## `GET /api/products/{id}/prices`

該商品（含合併鏈上所有前身商品）的價格歷史序列，依時間升冪排序。

| 參數 | 型別 | 說明 |
|---|---|---|
| `start` / `end` | datetime (ISO 8601) | 皆可省略；接受空字串視同未指定 |
| `days` | int | 只在 `start` 未指定時生效，等同 `start = now - days 天` |

回應：`PricePoint[]`，每筆 `{ "scraped_at": ..., "price": ... }`。

## `GET /api/products/{id}/stats`

回應：`ProductStatsOut`（同 `ProductDetail.stats` 的結構，見上方）。

## `GET /api/compare?ids=1,2,3`

多商品比較，`ids` 為逗號分隔的商品 id 字串，**數量須介於 2 到 20 個之間**。

- `ids` 格式錯誤（無法解析成整數）→ `400`
- `ids` 含重複商品 id → `400`
- 數量不在 2～20 之間 → `400`
- 任一 id 不存在或已被合併掉 → `404`（訊息含該 id）

回應：`CompareResult`

```json
{
  "items": [{
    "id": 123, "current_name": "...", "current_price": 18990,
    "low_7d": 17990, "low_30d": 17990, "high_30d": 18990,
    "all_time_low": 16990, "all_time_high": 18990,
    "change_amount": 1000, "change_percent": 5.56
  }],
  "series": [{ "product_id": 123, "scraped_at": "...", "price": 18990 }]
}
```

`series` 是所有被比較商品（含各自合併鏈）的價格歷史序列合併在一起，前端
依 `product_id` 分組繪製走勢圖。
