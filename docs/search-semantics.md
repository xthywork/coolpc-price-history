# 搜尋語意

所有商品名稱搜尋的核心邏輯集中在 `src/coolpc/search/service.py`，比對對象
永遠是 `product_names.name`（商品的**歷史名稱**清單），不是
`products.current_name`——同一商品底下任何一個歷史名稱命中都算符合，因此
搜尋舊名稱一樣能找到商品。已被合併掉的商品（`merged_into_id` 不為 `None`）
一律排除在搜尋結果之外。

## 兩種語意：AND / OR

查詢字串以空白分隔成多個 token。

### AND（預設，`q_match="and"`）

**每個 token 都必須各自命中，不要求整段查詢字串本身連續出現。**

比對邏輯（`_require_all_patterns`）：對每個 token 各自查一次
「哪些商品的哪個歷史名稱包含這個 token」，再對商品集合取交集
（token 之間不必命中同一個歷史名稱列，同一商品底下不同的歷史名稱列都算數）。

範例：搜尋 `ZOTAC 3050`
- ✅ 命中「ZOTAC RTX3050 ECO SOLO」——雖然商品名稱裡並沒有「ZOTAC 3050」
  這個連續子字串，但「ZOTAC」與「3050」分別都出現在名稱裡，兩個 token 各自
  命中即符合。
- ❌ 不命中「ZOTAC GT730 2GB Zone Edition」——雖然「ZOTAC」有命中，但整個
  名稱完全不含「3050」，AND 語意要求每個 token 都命中，一個沒中就整體排除。

這是**全站唯一**使用的商品名稱搜尋語意，包含：
- 公開搜尋首頁（`GET /`，`src/coolpc/public_api/routers/pages.py`）
- 公開 JSON API `GET /api/products`（`q_match` 參數預設值就是 `"and"`）
- 管理後台商品搜尋頁、商品搜尋 JSON（`GET /products/search-json`）——這兩處
  在程式碼裡是**寫死**用 AND（`SearchFilters(q=q, q_match="and", ...)`），
  不像 `/api/products` 一樣可用 `q_match` 參數切換

### OR（`q_match="or"`，僅 `/api/products` 可選用）

任一 token 命中即算符合，同時**額外**保留「整段查詢字串本身」的比對（例如
名稱本身就含空白，如「RTX 5070」，仍要能整段字串命中）。這是較寬鬆的瀏覽/
篩選模式，**非預設值**，只能透過公開 API `GET /api/products?q_match=or` 明確
選用；公開搜尋頁的 UI 與管理後台一律固定使用 AND，沒有切換 OR 的入口。

## 自動完成 / 精確挑選（`search_products_and`）

用於「從既有商品中精確挑出一個特定商品」的情境，例如：

- 公開商品比較頁的搜尋加入商品（`GET /api/products/autocomplete`）
- 管理後台手動合併頁的搜尋加入商品、相似度合併頁背後的商品查找
  （`GET /products/search-json`）

規則跟 AND 搜尋一樣（每個 token 各自命中即可，不要求連續子字串），但**沒有
結果筆數上限**（`limit=None`）：這類情境的查詢通常已經夠精確（AND 語意本身
已經很收斂），使用者需要看到所有真正符合條件的商品，不應該因為人為的筆數
上限而讓真正要找的商品被擠出結果之外。

`GET /api/products` 一般列表查詢仍有 `limit`（預設 50，上限 20000，見
[`docs/api-reference.md`](api-reference.md)），跟自動完成端點是不同的接口、
不同的預設行為。

## 分類/子分類、品牌、價格、上架狀態等篩選

這些不是文字比對，直接是 SQL 等值/區間篩選，套用在 AND/OR 文字搜尋結果之上
（見 `search_products()` 裡 `q` 之後的其餘 `filters.*` 判斷）：`category_id`、
`subcategory_id`、`brand`（等值）、`model`（`LIKE`）、`min_price`/`max_price`、
`is_active`。

## 排序

`SearchFilters.sort` 支援：`last_seen_desc`（預設）、`price_asc`、
`price_desc`、`name_asc`、`brand_asc`（`NULL` 排最後）、
`status_active_first`、`category_asc`（依 `Category.sort_order` 的人工顯示
排序，不是分類名稱字母順序，跟分類下拉選單的順序一致）。公開搜尋頁預設用
`price_asc`；`/api/products` 預設用 `last_seen_desc`。
