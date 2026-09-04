# 系統架構

## 與原始設計文件的差異

[`docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md`](superpowers/specs/2026-09-02-coolpc-price-history-design.md)
是專案初期的設計文件，`docs/superpowers/plans/` 下三份是對應的實作計畫，
兩者都是**歷史留存的規劃紀錄**，記錄當時的設計決策與理由，之後不再回頭修改
（改了就失去了「當初規劃了什麼」的紀錄價值）。系統實際落地後經過多輪需求
調整，下列幾點目前的實際行為已經跟原始設計文件不同，以本文件與
[`docs/database-schema.md`](database-schema.md)、
[`docs/search-semantics.md`](search-semantics.md)、
[`docs/admin-guide.md`](admin-guide.md) 為準：

- **`products` 表少了 `last_change_amount`、`last_change_percent`、
  `first_seen_at` 三個欄位**——原始設計中這三個欄位都存在，之後依需求分兩次
  移除（migration `0006`、`0007`），詳見
  [`docs/database-schema.md`](database-schema.md#已移除的欄位請勿重新加回)。
- **搜尋預設語意是 AND，不是 OR**——原始設計的空白分隔搜尋是 OR 語意（任一
  片段命中即符合），後續依需求改為預設 AND（每個片段都要命中），OR 僅在
  `/api/products` 保留為明確選用的選項。見
  [`docs/search-semantics.md`](search-semantics.md)。
- **公開搜尋頁的分頁機制**已從簡易的上一頁/下一頁，改為數字頁碼（含省略號）
  + 可指定每頁筆數（10/20/50/100/500/1000/全部）+ 直接跳頁 + 切換每頁筆數
  時保留捲動位置。
- **管理後台的商品詳細/編輯頁與分類新增功能**（`GET /products/{id}`、
  `POST /products/{id}`、`POST /categories`）是原始計畫之後才新增的能力，
  原始設計/計畫文件中沒有涵蓋，見 [`docs/admin-guide.md`](admin-guide.md)。
- **分類顯示名稱（`Category.display_name`）與排序（`sort_order`）機制**
  （migration `0004`、`0005`）同樣是原始設計之後才新增。

## 服務拓樸

系統由三種進程組成，共用同一個 SQLite 資料庫檔案（`data/coolpc.db`）：

1. **`public_api`**（`src/coolpc/public_api/`）：常駐 FastAPI + uvicorn 服務，
   監聽 `0.0.0.0:33690`。商品搜尋、詳細頁、比較頁、JSON API。
2. **`admin_api`**（`src/coolpc/admin_api/`）：常駐 FastAPI + uvicorn 服務，
   監聽 `0.0.0.0:33691`。抓取狀態、原始 HTML 封存、商品編輯、重複商品合併。
3. **抓取排程**（`coolpc-scraper` CLI，透過 systemd timer 每 6 小時觸發一次
   `oneshot` 服務）：抓一次原價屋估價頁、解析、寫入資料庫後即結束進程，不是
   常駐服務。

`public_api` 與 `admin_api` 完全獨立：各自是獨立的 FastAPI app（見
`src/coolpc/public_api/app.py`、`src/coolpc/admin_api/app.py`）、獨立的
uvicorn 進程、獨立的路由/模板/schema，唯一共用的是資料庫 model
（`src/coolpc/db/models.py`）、搜尋邏輯（`src/coolpc/search/service.py`）、
分頁工具函式（`admin_api` 直接 import `public_api.routers.pages` 的
`PAGE_SIZE_OPTIONS`/`_resolve_page_size`/`_build_page_list`，讓兩邊的分頁
行為維持一致而不用複製一份邏輯）、以及 `get_session`
依賴（`admin_api.dependencies` 直接 re-export `public_api.dependencies.
get_session`）。刻意分成兩個服務而非一個 app 掛兩組路由，是為了讓管理介面
可以獨立限制對外存取來源（見 README「正式環境部署」段落），不需要在應用層
另外實作權限系統——本系統完全不做登入/驗證，存取控制交給反向代理層負責。

前端統一走 Jinja2 伺服端渲染 + 原生 JavaScript，刻意不引入任何前端框架：
互動較多的頁面（商品搜尋頁的即時價格篩選、商品比較頁與手動合併頁的
chip 挑選器、商品編輯頁的分類/子分類連動下拉選單）都是直接在模板內嵌
`<script>`，用 `fetch()` 呼叫既有 JSON 端點局部更新 DOM，不整頁重載。

## 資料流：抓取 → 解析 → 寫入 → 服務

```
fetch_html()          scraper/fetcher.py
  │  httpx GET COOLPC_EVALUATE_URL（預設 https://coolpc.com.tw/evaluate.php）
  │  失敗 → FetchError → ScrapeSnapshot(status="failed")
  ▼
save_raw_html()        依估價時間存到 data/raw_html/YYYY/MM/DD/*.html
  │                     （檔名衝突時自動加 -1/-2... 後綴，原始檔案永不覆蓋）
  ▼
parse_html()            parser/html_parser.py
  │  decode_html(): cp950/Big5 解碼（原站編碼）
  │  parse_fetched_at(): 從 #Mdy 節點解析估價時間（HTML 內嵌時間戳，
  │                       不是抓取當下的系統時間——這點很重要：補匯歷史
  │                       檔案、或抓取當下網路延遲，都不會扭曲時間序列）
  │  parse_products(): 走訪 #tbdy 底下每個分類 <tr> 的 <select>，
  │                     逐一切出「名稱, $價格 標記」文字並解析
  │  失敗 → ParseError → ScrapeSnapshot(status="failed")，
  │         但仍會先保存原始 HTML（raw_html_path 不為 None），
  │         方便事後用保存下來的 HTML 除錯或補寫解析規則
  ▼
ingest_snapshot()       ingest/service.py
  │  idempotent：同一個 fetched_at 若已有 success/partial 紀錄，
  │              直接回傳既有紀錄，不重複處理（見
  │              docs/database-schema.md 的 scrape_snapshots 章節）
  │  I6 保護：本次商品數 < 上次成功快照商品數的 70% → status="partial"，
  │           跳過整批下架判斷
  │  逐一 ingest_product()：
  │    - product_names.name 完全相等 → 視為既有商品，更新價格/狀態/
  │      分類/last_seen_at，寫入一筆 price_history
  │    - 完全找不到 → 視為新商品，建立 products + product_names +
  │      price_history
  │  收尾：本次快照沒出現、目前仍 is_active 的既有商品標記下架
  │        （partial 快照跳過這步）
  ▼
   data/coolpc.db（WAL 模式，讀寫並行）
  │
  ├──▶ public_api：搜尋、詳細頁、比較頁、JSON API
  └──▶ admin_api：抓取狀態、原始 HTML 封存、商品編輯、合併
```

### 商品比對：完全等值，沒有模糊比對

`ingest_product` 判斷「這是不是既有商品」的唯一依據是
`product_names.name` **完全字串相等**，沒有任何模糊/相似度比對。這代表
原價屋商品名稱裡任何會變動的雜訊文字（促銷倒數期限、行銷用語變化）都會讓
系統誤判成新商品，破壞價格歷史連續性。目前已知並已用全語料庫驗證、在
`parser/html_parser.py` 用專門規則清理掉的兩類雜訊：

- `▼下殺到 M/D HH:MM`（限時下殺倒數，會隨檔期變動）
- `優惠至 M/D` / `活動至 M/D止`（任搭/組合優惠檔期到期日）

還有一類已知但**刻意不處理**的風險：行銷用語（例如「限時」「春節限時」
「限量活動」「酷幣5000」）也會在同一實體商品身上時有時無、時換時異，但
這類文字沒有固定結構可以安全地用 regex 辨識邊界，貿然用關鍵字比對可能誤刪
真正屬於商品名稱一部分的文字，因此交給下方的相似度合併機制事後處理，而非
在解析階段預先清理。

## 相似度合併機制

當「完全等值比對」因為名稱雜訊而把同一實體商品拆成兩筆不同的
`products` 紀錄時，系統提供一套**確定性、非 AI** 的重複商品偵測與合併流程，
在管理後台完成：

1. `matching/similarity.py` 的 `refresh_similarity_hints()`（管理後台「合併
   商品」頁點擊「重新計算相似度候選」觸發）：
   - `normalize_name()`：NFKC 正規化、移除「【...】」「｛...｝」促銷標籤
     括號**及其內容**（視為雜訊）、移除 `()（）[]` 符號本身但**保留內容**
     （這些括號常裝真正有區別意義的規格文字，例如超頻頻率、風扇數）、
     移除所有空白、轉小寫。
   - 用 `difflib.SequenceMatcher` 計算正規化後兩字串的相似度比例
     （0～1），**只在同一個 `category_id` 內兩兩比較**（不同分類的商品
     不會被拿來比較，也是降低計算量的手段）。
   - 相似度 ≥ `0.75`（`SIMILARITY_THRESHOLD`）就寫入一筆 `similarity_hints`。
   - 已存在的配對（不論方向）不重複計算。
   - **效能注意**：這是同分類內商品數的 O(n²) 兩兩比較，商品基數大時
     （例如上萬筆商品）會是重運算量操作，執行時間可能長達數分鐘，且目前
     實作是同步阻塞、沒有進度回報或逾時中斷；正式環境不建議設定成自動
     排程觸發，應由管理者視需要手動點擊執行，並留意伺服器 CPU 負載。
2. 管理員在「合併商品」頁逐一檢視候選（並排顯示商品 A / B 與相似度分數），
   可個別「合併」（自動決定保留方向，見下方）或「忽略」（標記
   `dismissed=True`，之後不再出現），也可以勾選多組後「合併下列所有項目」
   一次處理。

## 合併方向決策（`choose_merge_direction`）

**純規則，不涉及名稱或相似度判斷**，依序套用：

1. 兩商品只有一個仍在上架中（`is_active`）→ 該商品當保留目標（target）。
2. 都上架或都下架 → `last_seen_at` 較新者當 target。
3. 完全同分（罕見）→ `id` 較小者當 target。

`merge_products()` 的實際效果：把來源商品（source）的所有 `product_names`
改掛到 target（`product_id` 欄位重新指向），並在 `source.merged_into_id`
記下 target 的 id——**不刪除 source 這筆 `products` 紀錄**，只是讓它對外
（公開 API/頁面）一律視為不存在。`price_history` 也不搬動，仍掛在原本各自
的 `product_id` 下；`stats.service.get_merged_group_product_ids()` 在查詢時
才沿著 `merged_into_id` 鏈把整個合併群組的價格歷史合併起來，因此合併前的
歷史價格不會遺失，且支援連續合併鏈（A 併入 B，之後 B 又併入 C）。

`merge_log.moved_name_ids` 記錄本次確切搬動了哪些 `product_names.id`，讓
`undo_merge()` 能精確復原——不能只靠時間戳或名稱反推，因為 target 商品在
這之後可能自己又累積了新的歷史名稱。若 target 之後又被捲入更新的一次合併
（成為另一個合併的 source），系統會拒絕 Undo 較舊的那筆合併，要求先 Undo
較新的（避免復原順序錯亂導致名稱歸屬損毀）。

## 併發控制

- **抓取層**：`scraper/lock.py` 的 `ScraperLock` 用一個檔案鎖
  （`data/scraper.lock`，內容為持有進程的 PID）確保排程抓取與手動抓取
  （CLI `scrape --manual` 或管理介面按鈕）不會同時執行；鎖若對應的 PID 已經
  不存在（進程異常終止但沒清乾淨），會自動判定為 stale 並清除重新取得。
- **資料庫層**：SQLite WAL 模式讓抓取寫入交易與網站讀取查詢可以並行，不會
  互相阻塞（見 [`docs/database-schema.md`](database-schema.md) 開頭的
  pragma 說明）。
