# AGENTS.md — 給接手這個專案的 agent

這份文件記錄**讀原始碼看不出來的慣例與地雷**。系統功能說明請看
[`README.md`](README.md) 與 [`docs/`](docs/)；這裡只寫「動手之前必須先知道
的事」。

## 先讀這個

| 問題 | 答案 |
|---|---|
| 這是什麼 | 從原價屋估價頁定期抓價、永久保存原始 HTML、提供歷史價格查詢與管理後台 |
| 語言 | **所有介面文案、文件、commit 訊息一律繁體中文** |
| 開發流程 | TDD：先寫失敗的測試 → 實作 → 跑該檔測試 → **commit 前跑完整套件** |
| 跑測試 | `uv run pytest`（目前約 226 個，約 6 分鐘；數字會變動，實際數量用 `uv run pytest --collect-only -q` 確認） |
| 前端 | Jinja2 伺服端渲染 + 原生 JS，**沒有框架、沒有 npm、沒有建置步驟** |
| 資料庫 | SQLite（WAL 模式），schema 只透過 Alembic 變更 |
| 本機服務 | user-level systemd，**所有指令都要加 `--user`**（見最後一節） |
| 硬性限制 | 資料處理流程**完全不使用 AI／LLM／agent 推論**，全部是確定性規則 |

**動手前最少要讀**：本檔 +
[`docs/architecture.md`](docs/architecture.md)。要改資料表再讀
[`docs/database-schema.md`](docs/database-schema.md)，要改搜尋再讀
[`docs/search-semantics.md`](docs/search-semantics.md)。

## 架構速覽

兩個**各自獨立**的 FastAPI app，共用同一個 SQLite 檔案，**都沒有任何身分
驗證**：

| 服務 | 埠 | 模組 | 用途 |
|---|---|---|---|
| 公開查詢 | 33690 | `coolpc.public_api.app:app` | 搜尋頁、商品詳細、比較、JSON API |
| 管理介面 | 33691 | `coolpc.admin_api.app:app` | 抓取狀態、商品編輯、合併工具 |

管理介面沒有登入機制，**不可對公網開放**。

`src/coolpc/` 各模組職責：

| 目錄 | 職責 |
|---|---|
| `db/` | SQLAlchemy models、engine/session（WAL 等 pragma 設定在 `session.py`） |
| `parser/` | HTML 解析（cp950 解碼、估價時間、名稱/價格/狀態切分） |
| `ingest/` | 解析結果寫進資料庫（新增/更新商品、價格歷史、下架判定） |
| `scraper/` | HTTP 抓取、原始 HTML 存檔、併發鎖、匯入進入點 |
| `matching/` | 名稱正規化與相似度計算，產生合併候選 |
| `merging/` | 合併方向決策、實際合併與 Undo |
| `stats/` | 價格統計（會沿著合併鏈追蹤） |
| `search/` | 商品搜尋（AND/OR 語意、廣告過濾） |
| `query_types.py` | 把空字串正規化成 `None` 的查詢參數型別 |
| `web/static/` | 兩個服務共用的 CSS token、字體、原生 JS |

前端共用資產放在 `src/coolpc/web/static/`，由兩個 app 各自
`app.mount("/static", ...)`（`public_api/app.py:13`、`admin_api/app.py:15`）。
第三方資產（IBM Plex Mono、Chart.js）一律 self-host，**不要改成 CDN**。

## 地雷（都是真的踩過的）

### 1. 路由註冊順序：靜態路徑必須排在 `/{id}` 之前

Starlette 依**註冊順序**比對路徑樣板，先中先贏。`/products/{product_id}`
會把 `"sparklines"`、`"search-json"` 這種字串當成 id 吃掉，然後在型別驗證
階段回 422，**不會**往下找真正該匹配的路由。

現有的兩處：

- `public_api/routers/api.py:61-63` — `/products/sparklines` 註冊在
  `/products/{product_id}`（同檔 104 行）之前，原始碼有註解說明原因。
  `/products/autocomplete`（91 行）同理。
- `admin_api/routers/products.py:63` — `/products/search-json` 排在
  `/products/{product_id}`（同檔 77 行）之前，原始碼同樣有註解說明原因。

新增任何 `/products/<字串>` 路由時，一律加在動態路由**上面**。

### 2. 時間戳一律來自 HTML，不是系統時鐘

`parser/html_parser.py:17` 的 `parse_fetched_at()` 讀 HTML 裡的 `#Mdy`
元素，解析出原價屋自己的估價時間。抓不到就丟 `ParseError`，**不會退而用
系統時間**。

`scrape_snapshots.created_at` 是全系統**唯一**的系統時鐘欄位（紀錄寫入
時間，稽核用）。其餘所有時間欄位（`fetched_at`、`scraped_at`、
`last_seen_at`、`products.created_at`、`product_names.*_seen_at`）都是估價
時間。

實際落差可能很大：檔名 `2026-09-01-00-00.html`（下載時間）的內嵌估價時間
可能是 `2026-08-31 19:33`。

### 3. 匯入以 `fetched_at` 做冪等判斷

`ingest/service.py:109` 檢查是否已有相同 `fetched_at`、且 `status` 為
`success` 或 `partial` 的快照；有的話直接回傳既有紀錄、**完全不重新處理**。

好處是重複匯入安全。但代價是：**你無法靠「再匯入一次」來刷新狀態**。要讓
某個既有快照重新生效，必須先刪掉那筆 `scrape_snapshots` 與它的
`price_history`，才能重匯。

### 4. 匯入不會複製檔案，只記路徑

`save_raw_html()` 只在 `run_scrape()` 裡呼叫（`scraper/run.py:53,57`）。
`import_html_file()`（72 行）**不複製檔案**，資料庫存的是你傳進去的來源
路徑；後台的原始 HTML 檢視頁會直接開那個路徑
（`admin_api/routers/dashboard.py:67`）。

所以：**先把檔案搬到最終位置，再匯入**。匯入後搬動或刪除來源檔，封存檢視
就會壞掉。

### 5. 下架判定沒有時序保護 ⚠️ 最容易造成資料錯亂

`ingest/service.py:170` 起，會把「目前 `is_active=True` 但不在這次快照裡」
的商品全部標成下架——**不管這次快照的時間比資料庫裡既有資料舊還是新**。

同時 `ingest_product()` 會無條件覆寫 `current_price`、`current_status`、
`is_active`、`last_seen_at`。

**症狀**：匯入一批比現有資料舊的 HTML 之後，商品的「目前價格／上下架／
最後出現」全部倒退到舊快照的狀態，且只出現在新快照的商品會被誤標下架。
歷史價格（`price_history`）不受影響，錯的只有這些「目前狀態」欄位。

**修法**：讓最新的快照最後被處理。

```bash
# 1. 先備份（見地雷 6）
sqlite3 data/coolpc.db "VACUUM INTO '/tmp/before.db'"
# 2. 刪掉最新那筆快照與它的價格記錄
sqlite3 data/coolpc.db "DELETE FROM price_history WHERE snapshot_id=<id>;
                        DELETE FROM scrape_snapshots WHERE id=<id>;"
# 3. 匯入舊檔案（依時序）
uv run coolpc-scraper import-dir <dir>
# 4. 最後重匯剛才刪掉那份已封存的 HTML，讓它落在最後
uv run coolpc-scraper import-html data/raw_html/YYYY/MM/DD/<file>.html
```

注意「再跑一次抓取」通常**修不好**：如果原價屋還沒更新估價時間，新抓到的
快照會因為地雷 3 的冪等判斷被跳過。

`import_html_dir()`（`scraper/run.py:92`）是用 `sorted(glob(...))` 依**完整
檔案路徑字串**排序，不是依內嵌估價時間。`data/raw_html/YYYY/MM/DD/` 這種
排法剛好路徑順序等於時間順序；換成別的命名方式就要自己確認。

### 6. 絕對不要用 `cp` 複製線上資料庫

資料庫跑在 WAL 模式（`db/session.py` 的 pragma）。還沒 checkpoint 的交易
在 `-wal` 檔裡，直接 `cp`/`rsync` 主檔會拿到缺資料的舊快照——**這已經實際
發生過一次，導致誤判 alembic 版本落後**。

```bash
sqlite3 data/coolpc.db "VACUUM INTO '/path/to/backup.db'"
```

### 7. Schema 只透過 Alembic 變更

正式環境**不可**用 `Base.metadata.create_all()`（那只給測試的記憶體資料庫
用）。目前 head 是 `0007_drop_product_first_seen_at`。

新增 migration 後，先在快照上試跑再套用到正式庫，流程見
[`docs/deployment.md`](docs/deployment.md)。SQLite 的 ALTER 能力有限，改欄
位請用 `op.batch_alter_table()`。

### 8. 不要把已刪除的欄位加回來

| 欄位 | 移除於 |
|---|---|
| `products.last_change_amount`、`last_change_percent` | migration `0006` |
| `products.first_seen_at` | migration `0007` |

移除理由寫在 [`docs/database-schema.md`](docs/database-schema.md) 的「已移除
的欄位」。商品的漲跌數字是 `stats.compute_product_stats()` 從
`price_history` **即時算**出來的，不需要這些欄位；`created_at` 已經是「第一
次看到這個商品」的單一事實來源。

注意 `product_names.first_seen_at` 是**不同的欄位**，仍在使用中。

### 9. 搜尋比對的是 `product_names.name`，不是 `products.current_name`

`search/service.py` 的 `_require_all_patterns()` 對 `product_names` 做
`LIKE` 比對（這也是「用舊名稱也搜得到」的原因）。

**測試地雷**：只建立 `Product` 而沒有建對應的 `ProductName`，搜尋會回傳
空結果，而且不會報錯。這已經浪費過一次除錯時間。測試 fixture 一律成對建立：

```python
p = Product(...)
session.add(p); session.flush()
session.add(ProductName(product_id=p.id, name=p.current_name,
                        first_seen_at=t, last_seen_at=t))
```

另外 `product_names.name` 是**全域 unique**（`db/models.py:62`），兩個不同
商品不會共用同一個歷史名稱字串。

### 10. 測試斷言不要比對裸類名或 JS 字串

模板的 CSS 規則與 `<script>` 內的字串常常和 HTML 元素撞名，
`resp.text.find("hintDivider")` 可能先命中 CSS 的 `.hintDivider{...}` 而不是
真正的 `<div class="hintDivider">`。

- 用帶引號的 `class="hintDivider"` 而不是裸字串
- 檢查某段 JS 是否存在時，先把該函式的區間切出來再斷言，不要對整頁做
  `not in`

### 11. `Category.label` vs `Category.name`

`label` 是 `display_name or name`（`db/models.py:24`、`Subcategory` 同樣在
38 行）。`name` 是原價屋原始分類名稱，**抓取與比對邏輯只認 `name`**，改
`display_name` 不影響任何商品歸屬。

畫面上一律顯示 `label`，**唯一的例外**是管理後台的商品詳細頁
（`admin_api/templates/product_detail.html:21`），那裡刻意顯示原始
`category.name`，讓管理者核對真實歸屬。（同一行的子分類仍用
`subcategory.label`。）

### 12. I6：解析不完整的保護機制

`ingest/service.py:163` — 若本次解析到的商品數 **低於上一次成功快照的
70%**，快照標記為 `partial` 並**完全跳過下架比對**，寧可保留現有狀態，也不
要因為一次可疑的解析把大量商品誤標下架。

比較基準 `prior_successful` 只取 `status == "success"` 的快照，**刻意不含
`partial`**——否則一次 partial 會把門檻拉低，讓保護在下一輪失效。

### 13. 搜尋語意與廣告過濾

預設 **AND**：空白分隔的每個 token 都要各自命中，但不要求整段字串連續出現
（搜「ZOTAC 3050」要找得到「ZOTAC RTX3050 ECO SOLO」）。`q_match="or"` 是
明確 opt-in。

`exclude_ads`（`search/service.py:22`）過濾 `current_price == AD_PRICE`
（`AD_PRICE = 1`，30 行）。原價屋把活動公告、運費說明這類非商品項目標價
1 元。**只有公開端打開它**：

| 呼叫點 | `exclude_ads` |
|---|---|
| `public_api/routers/pages.py:71`（搜尋頁） | `True` |
| `public_api/routers/api.py:53`（`/api/products`） | `True` |
| `public_api/routers/api.py:99`（比較頁自動完成） | `True` |
| `admin_api/routers/products.py:38`（後台搜尋） | 預設 `False` |
| `admin_api/routers/products.py:68`（`search-json`） | 預設 `False` |

後台必須查得到這些項目才能編輯／合併，**不要**在後台打開這個旗標。

### 14. 匯入不受抓取併發鎖保護

`ScraperLock`（`scraper/lock.py`）只在 `run_scrape()` 裡取得
（`scraper/run.py:41-43`），CLI 的 `import-html` / `import-dir` **不會**取這
把鎖。大批匯入前先停掉排程：

```bash
systemctl --user stop coolpc-scraper.timer
```

### 15. 相似度重算是 O(n²)

`matching/similarity.py` 用 `difflib.SequenceMatcher` 在同分類內兩兩比較。
商品基數大時單次重算會吃滿一顆 CPU 數十分鐘，**曾經因此需要 `kill -9`**
（`SIGTERM` 進不去那個緊迴圈）。它刻意不排程、只由管理者手動觸發，不要把它
接到自動流程裡。

## 常用操作

```bash
# 測試
uv run pytest                              # 完整套件（約 6 分鐘）
uv run pytest tests/search/ -q             # 單一目錄
uv run pytest -q -k "ads"                  # 關鍵字篩選

# 資料庫
uv run alembic upgrade head                # 套用 migration
uv run alembic current                     # 目前版本
uv run alembic revision -m "說明"          # 新增 migration（手寫，勿 autogenerate）
sqlite3 data/coolpc.db "VACUUM INTO '/tmp/backup.db'"   # 一致快照備份

# 抓取與匯入
uv run coolpc-scraper scrape --manual
uv run coolpc-scraper import-html <path>
uv run coolpc-scraper import-dir <dir>

# 服務（注意 --user）
systemctl --user restart coolpc-public.service coolpc-admin.service
systemctl --user status coolpc-public.service
journalctl --user -u coolpc-scraper.service -n 50
systemctl --user list-timers coolpc-scraper.timer
```

長篇流程不要在這裡重複，各自看：
[`docs/deployment.md`](docs/deployment.md)（備份／migration 操作程序）、
[`docs/new-machine-setup.md`](docs/new-machine-setup.md)（新機器部署／批次
匯入）、[`docs/development.md`](docs/development.md)（TDD 與 migration 慣例）。

## Commit 慣例

- 標題用 conventional commit 前綴 + **繁體中文**描述：
  `feat(search): 公開查詢排除 1 元的廣告項目，後台維持可查`
- 內文說明**為什麼**這樣改，不只寫改了什麼；牽涉取捨時把取捨寫出來
- 保留 repo 既有的署名 trailer（`Co-Authored-By:` 與 `Claude-Session:`）
- **commit 前一定要跑完整測試套件**，不要只跑改到的那個檔

## 這台機器上的實際部署

**跑在 user-level systemd**，不是系統層級。unit 檔在
`~/.config/systemd/user/`，已開啟 linger（`Linger=yes`），所以登出後仍會執行、
開機也會自動啟動。

| Unit | 狀態 |
|---|---|
| `coolpc-public.service` | enabled，常駐（33690） |
| `coolpc-admin.service` | enabled，常駐（33691） |
| `coolpc-scraper.service` | static（oneshot，由 timer 觸發） |
| `coolpc-scraper.timer` | enabled，每 6 小時 |

**所有 systemctl / journalctl 指令都必須加 `--user`**，否則會去找系統層級的
unit 而找不到。

⚠️ **不要把 repo 裡的 `deploy/*.service` 跟這組搞混。** `deploy/` 下的是給正式
環境用的**系統層級**範本，寫死 `/opt/coolpc-price-history` 路徑與 `coolpc`
執行帳號，需要 sudo 安裝到 `/etc/systemd/system/`。這台機器沒有免密碼 sudo，
所以用的是 user-level 那一套；兩者路徑與帳號都不同，改錯地方不會生效。

## 資料與備份

- `data/` **不納入版控**（`.gitignore` 排除資料庫與 `raw_html/`）
- 需要備份的是整個 `data/`：資料庫（用 `VACUUM INTO`）+ `raw_html/`（靜態
  檔，可直接 rsync）
- 原始 HTML 是唯一能重建整個資料庫的來源，不要刪
