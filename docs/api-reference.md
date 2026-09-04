# 公開 JSON API 參考

服務：`public_api`（`0.0.0.0:33690`），路由定義於
`src/coolpc/public_api/routers/api.py`，前綴一律是 `/api`。無需登入或
API Key。所有回應皆為 JSON，schema 定義於 `src/coolpc/public_api/schemas.py`。

已被合併掉的商品（`merged_into_id` 不為 `None`）對所有端點一律視為不存在，
回傳 `404`。

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
| `q_match` | `"and"` \| `"or"` | `"and"` | 見上方連結 |
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

## `GET /api/products/autocomplete`

精確挑選單一商品用的自動完成端點（給前端下拉選單/chip 挑選器使用），
**永遠是 AND 語意、不退回 OR、不限制結果筆數**——見
[`docs/search-semantics.md`](search-semantics.md#自動完成--精確挑選search_products_and)。

| 參數 | 型別 | 說明 |
|---|---|---|
| `q` | string | 空字串或省略時直接回傳空結果，不查詢資料庫 |

回應格式同 `ProductListPage`。

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

多商品比較，`ids` 為逗號分隔的商品 id 字串，**數量須介於 2 到 5 個之間**。

- `ids` 格式錯誤（無法解析成整數）→ `400`
- 數量不在 2～5 之間 → `400`
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
