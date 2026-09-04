# 資料庫 Schema

儲存引擎為 SQLite，透過 SQLAlchemy 2.0（`src/coolpc/db/models.py`）定義
model，schema 演進一律透過 Alembic migration（`migrations/versions/`）管理，
**不使用 `Base.metadata.create_all()` 對正式環境自動建表/改表**（測試套件
才用 `create_all` 建立記憶體資料庫）。

連線時會設定三個 SQLite pragma（見 `src/coolpc/db/session.py`）：

| Pragma | 值 | 原因 |
|---|---|---|
| `journal_mode` | `WAL` | 抓取寫入交易可能持續數秒到數十秒；WAL 模式讓讀取者（公開/管理網站）在寫入交易進行時仍可並行讀取，避免回傳「database is locked」 |
| `busy_timeout` | `30000`（毫秒） | 讀寫短暫衝突時的保底重試等待時間 |
| `foreign_keys` | `ON` | SQLite 預設關閉外鍵限制，開啟後 schema 上宣告的 FK 才會真正被檢查 |

## 資料表總覽

| 資料表 | 用途 |
|---|---|
| `categories` | 商品分類（原價屋原始分類） |
| `subcategories` | 商品子分類，隸屬某個分類 |
| `products` | 商品主表：目前狀態、目前價格、分類歸屬 |
| `product_names` | 商品的歷史名稱清單（同一商品改名時累加，不覆蓋） |
| `price_history` | 每次抓取到的價格快照，一筆對應一次抓取 |
| `scrape_snapshots` | 每次抓取/匯入的執行紀錄與統計 |
| `merge_log` | 人工合併紀錄，支援 Undo |
| `similarity_hints` | 系統自動產生的重複商品合併候選 |

## `categories`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `name` | str, unique | 原價屋原始分類名稱。**抓取/比對邏輯永遠只認這個欄位**，`display_name` 純粹是畫面顯示用，改了它不會影響任何商品的分類歸屬判斷 |
| `display_name` | str, nullable | 人工設定的顯示名稱覆蓋（migration `0004_category_display_names`）。有設定時，畫面上（`Category.label` 屬性）顯示這個值，沒有設定則退回顯示 `name` |
| `sort_order` | int, nullable | 人工設定的顯示排序，數字小排前面；`None` 排在所有有設定的分類之後，同分類間再依 `name` 排序（migration `0005_category_sort_order`） |

`Category.label`（Python property）= `display_name or name`。除了管理後台
「商品詳細資料」頁的分類欄位**刻意**改用原始 `name`（見
[`docs/admin-guide.md`](admin-guide.md#商品搜尋--詳細編輯頁)）之外，其餘所有
頁面與 API（分類下拉選單、搜尋結果的分類文字、`/api/categories`）一律顯示
`label`。

## `subcategories`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `category_id` | int, FK → `categories.id` | |
| `name` | str | 原價屋原始子分類名稱；跟 `category_id` 組成 unique constraint |
| `display_name` | str, nullable | 同 `categories.display_name`，`Subcategory.label` = `display_name or name` |

原價屋許多分類本身沒有真正的第二層子分類，實際資料是一筆 `name` 為空字串
的子分類代表「分類本身」——這是原站 HTML 結構的既有慣例（見
`src/coolpc/parser/html_parser.py` 的 `_iter_select_options`：沒有
`<optgroup>` 包住時 `subcategory_name` 就是空字串），不是本系統額外發明的
規則。畫面上遇到空字串子分類名稱時只顯示分類名稱，不會留下多餘的
「分類 / 」。新增分類時（見 `POST /categories`，
[`docs/admin-guide.md`](admin-guide.md)）也會依這個慣例自動建立一筆同名的
空字串子分類。

## `products`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `category_id` | int, FK → `categories.id` | |
| `subcategory_id` | int, FK → `subcategories.id` | |
| `current_name` | str, indexed | 目前商品名稱（最新一次抓取到的原始名稱） |
| `brand` | str, nullable | 從名稱前綴猜測（`ingest.service.guess_brand`，比對一份已知品牌清單） |
| `model` | str, nullable | 從名稱中「【型號】」/「｛型號｝」括號樣式擷取（`ingest.service.guess_model`）；並非每個商品名稱都有這種括號標記，抓不到就是 `None`，不是系統性缺失 |
| `current_status` | str, nullable | 原價屋原始狀態文字（例如「現貨」「訂」「客訂」「拆封品」），從名稱中的括號標記擷取 |
| `current_price` | int | 目前價格 |
| `is_active` | bool | 是否仍在原價屋上架中；每次成功抓取後，所有「本次快照沒出現」的商品會被設為 `False`（除非本次判定為 `partial`，見下方「I6 保護機制」） |
| `last_seen_at` | datetime | 最後一次被抓到的估價時間（來自 HTML 內嵌時間戳，不是牆上時鐘時間） |
| `merged_into_id` | int, nullable, FK → `products.id` | 若此商品已被合併掉，指向合併後保留的目標商品；對外（公開 API/頁面）一律視為不存在（404） |
| `created_at` | datetime | 此商品第一次被抓到時的估價時間 |

### 已移除的欄位（請勿重新加回）

以下兩組欄位曾經存在，已依需求明確移除，並保留 migration 供日後查閱：

| 欄位 | 移除於 | 原因 |
|---|---|---|
| `last_change_amount`、`last_change_percent` | `migrations/versions/0006_drop_last_change_columns.py` | 只被 `SearchFilters` 的 `recent_change`/`min_change_percent`/`max_change_percent` 篩選條件使用，而這三個篩選條件從未在任何頁面 UI 實際串接——純粹是沒人用的 API 參數，已一併移除。商品詳細頁/比較頁顯示的漲跌數字是 `compute_product_stats()` 從 `price_history` **即時計算**出來的，跟這兩個欄位完全無關，移除後不受影響 |
| `first_seen_at` | `migrations/versions/0007_drop_product_first_seen_at.py` | `ingest_product()` 建立新商品時，`first_seen_at` 與 `created_at` 從一開始就永遠被設成同一個值，全專案沒有任何地方讓兩者出現過不同值，是完全重複的欄位；`created_at` 保留為單一事實來源 |

`product_names.first_seen_at`（見下方）是**不同、獨立**的欄位，未受影響，
仍然存在且持續使用中。

## `product_names`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `product_id` | int, indexed, FK → `products.id` | |
| `name` | str, indexed, unique | 這個商品曾經用過的一個名稱（全域唯一：兩個不同商品不會有同一個歷史名稱字串，因為 `ingest_product` 是靠 `product_names.name` 完全相等來判斷「這是不是既有商品」） |
| `first_seen_at` | datetime | 這個名稱第一次出現的估價時間 |
| `last_seen_at` | datetime | 這個名稱最後一次出現的估價時間 |

商品改名時（原價屋估價頁上同一實體商品的文字變了），`ingest_product` 找不到
`name` 完全相等的既有紀錄，會建立一筆**新的** `ProductName`，但沿用同一個
`product_id`——因此一個商品可以累積多筆歷史名稱，商品詳細頁的「歷史名稱」
即來自這張表。搜尋（`search_products`/`search_products_and`）也是對這張表的
`name` 做 `LIKE` 比對，而非對 `products.current_name`，因此搜尋歷史名稱一樣
能找到商品。

## `price_history`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `product_id` | int, indexed, FK → `products.id` | |
| `price` | int | 該次抓取的價格 |
| `status` | str, nullable | 該次抓取的狀態文字 |
| `badges` | str, nullable | 該次抓取的其餘標記文字（例如「◆ ★ 熱賣」） |
| `scraped_at` | datetime, indexed | 該次抓取的估價時間 |
| `snapshot_id` | int, FK → `scrape_snapshots.id` | |

商品合併後，價格走勢圖/統計（`stats.service`）會沿著 `merged_into_id` 鏈
把來源商品與目標商品的 `price_history` 合併查詢（`get_merged_group_product_ids`
以廣度優先方式展開整條合併鏈，正確處理「A 併入 B，之後 B 又併入 C」的情況），
確保合併前的歷史價格不會消失。

## `scrape_snapshots`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `fetched_at` | datetime | 估價時間（HTML 內嵌時間戳） |
| `scrape_type` | str | `"scheduled"` \| `"manual"` \| `"import"` |
| `raw_html_path` | str, nullable | 原始 HTML 檔案在 `data/raw_html/` 下的路徑；解析失敗（fetch 失敗）時為 `None` |
| `status` | str，預設 `"success"` | `"success"` \| `"partial"` \| `"failed"` |
| `error_message` | str, nullable | 失敗時的錯誤訊息 |
| `total_products` | int，預設 `0` | 本次解析到的商品總數 |
| `new_products` | int，預設 `0` | 本次新增的商品數 |
| `delisted_products` | int，預設 `0` | 本次判定下架的商品數 |
| `price_up_count` / `price_down_count` | int，預設 `0` | 本次漲價/降價的商品數 |
| `created_at` | datetime | 此紀錄的建立時間（系統時間，非估價時間） |

### `status` 狀態機

- `"failed"`：HTTP 抓取失敗，或 HTML 解析失敗（找不到估價時間欄位、找不到
  商品表格、完全解析不出任何商品）。
- `"partial"`：**I6 保護機制**——本次解析到的商品總數低於「上一次真正成功」
  快照商品總數的 70% 時觸發，代表原站 HTML 結構可能局部改版、解析可能不
  完整。觸發時**完全跳過下架比對**，寧可暫時保留所有商品現有的 `is_active`
  狀態不變，也不要因為一次可疑的解析結果誤將大量商品標記下架。判斷基準
  刻意只採計上一次 `"success"`（不含 `"partial"`）的快照，避免一旦發生一次
  partial，門檻被連續攤低而失效。
- `"success"`：正常完成，本次快照中沒出現的既有上架商品會被標記下架。

`ingest_snapshot` 對相同 `fetched_at` 是 idempotent 的：若已有一筆
`status` 為 `"success"` 或 `"partial"` 的紀錄，重複匯入同一個 `fetched_at`
會直接回傳既有紀錄、不重新處理，避免補匯歷史檔案時重複寫入
`price_history`。

## `merge_log`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `source_product_id` | int, FK → `products.id` | 被合併掉的商品 |
| `target_product_id` | int, FK → `products.id` | 合併後保留的商品 |
| `merged_at` | datetime | |
| `undone_at` | datetime, nullable | 若此合併已被 Undo，記錄 Undo 時間 |
| `moved_name_ids` | str（JSON 陣列），預設 `"[]"` | 本次合併時被改掛到 `target` 的 `product_names.id` 清單，供 Undo 精確還原（不能只靠時間或名稱反推，因為 target 之後可能又有自己的新名稱） |

## `similarity_hints`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int, PK | |
| `product_a_id` / `product_b_id` | int, FK → `products.id` | 候選配對（`product_a_id < product_b_id`，比對時已排序） |
| `score` | float | 名稱相似度分數（0～1），見 [`docs/architecture.md`](architecture.md) 的相似度比對章節 |
| `computed_at` | datetime | |
| `dismissed` | bool，預設 `False` | 被忽略或已合併後標記為 `True`，之後不再顯示 |
