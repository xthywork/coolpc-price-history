# 原價屋歷史價格查詢系統 — 系統設計文件

日期：2026-09-02
狀態：已核准，待轉入實作計畫

## 一、背景與目標

從原價屋（coolpc.com.tw）官方估價網頁定期抓取商品價格，永久保存原始 HTML，
解析出結構化商品與價格資料，提供歷史價格查詢、走勢圖、多商品比較、公開查詢
API 與管理介面。系統執行期間**不得使用 AI/LLM/Agent** 做任何商品判斷（分類、
比對、合併皆為確定性程式規則）。

## 二、原價屋 HTML 結構分析（依實際樣本 `/home/xthybot/coolpc/download` 842 份）

- 檔案為 Big5 編碼，`<meta http-equiv="content-type" content="text/html; charset=big5">`。
- HTML 標籤大量使用大寫（`<SELECT>`、`<OPTION>`、`<OPTGROUP>`）且部分標籤未正確
  閉合（例如 `<TD class=t>...` 後直接接下一個 `<TD>`，沒有 `</TD>`）。**必須使用
  `lxml` 作為 BeautifulSoup 的 parser**；`html.parser` 在此類殘缺標籤上會解析
  失敗（巢狀錯亂、抓不到後續兄弟節點）。
- 估價時間：`<font id=Mdy>2026/2/1 14:28...</font>`，格式為 `YYYY/M/D HH:MM`，
  作為該次快照的「原價屋估價時間」，優先於系統匯入/抓取時間。
- 主分類：`#tbdy` 表格內每個 `<TR>` 代表一個主分類。第一個 `<TD>`（class=w）
  是分類編號，第二個 `<TD>`（class=t）是分類名稱文字，第三個 `<TD>` 內含一個
  `<SELECT>`。實測共 30 個主分類（品牌小主機、筆電、CPU、主機板、顯示卡...）。
- 子分類：`SELECT` 內的 `<OPTGROUP LABEL='...'>`，`LABEL` 即子分類名稱。
- 商品：`OPTGROUP` 底下的 `<OPTION>`：
  - `value=0` 且 `class=bf` 的第一個 OPTION 是統計摘要行（「共有商品 N 樣...」），
    非商品，需排除。
  - 帶 `disabled` 屬性的 OPTION 是提示文字/警語/促銷備註（例如
    `❤ 此商品為專業性產品...`、`　　↪ 【買就送】...`），非商品，需排除。
  - 其餘 OPTION 才是真正商品，`value` 屬性是**該次頁面渲染的暫時序號**，
    **不可作為永久商品 ID**（頁面重新整理即可能變動）。
  - OPTION 的 `class` 屬性標示狀態：`r`=熱賣、`g`=價格異動、
    `b`=熱賣+價格異動、無 class=普通。
  - OPTION 文字格式固定為：`名稱本體, $價格 後綴標記們`。已驗證（跨 7 個月
    抽樣、顯示卡分類全量統計）：**「熱賣」「↓任搭N↓」「↓酷幣N↓」「◆」「★」
    「↘舊價」等促銷/狀態符號一律出現在 `, $價格` 之後**，用
    `re.match(r'^(.*?),\s*\$([\d,]+)(.*)$', text)` 切分即可自然把這些符號
    排除在「名稱本體」之外，**不需要額外設計「移除熱賣/限搭機」等清理規則**。
  - 名稱本體內可能含有 `【...】`／`｛...｝` 等符號，但用途混雜不統一
    （型號代碼片段、保固年限、購買限制如「限搭NAS主機」、規格如「SFX」、
    庫存狀態如「現貨/訂/客訂」），**不適合強行結構化成獨立標籤欄位**（會誤判
    型號片段），改採全文搜尋（見六）。
  - 名稱本體內可解析出庫存狀態關鍵字（現貨/訂/客訂/拆封品等），做成
    `current_status` 結構化欄位。
  - 名稱本體並非完全穩定：原價屋會不定期調整描述格式本身（例如新增顏色字樣、
    改變框線符號），這種漂移無法用移除特定詞彙的規則安全處理，只能透過
    相似度候選 + 人工合併機制解決（見五）。

## 三、專案結構

單一 uv 專案（monorepo，多模組），不拆分成多個 repo：

```
coolpc-price-history/
├── pyproject.toml
├── README.md
├── src/coolpc/
│   ├── db/            # SQLAlchemy models + Alembic migrations
│   ├── scraper/        # HTTP 下載 + 原始 HTML 存檔
│   ├── parser/           # HTML → 結構化資料（lxml）
│   ├── ingest/            # 解析結果 → 寫入 DB（比對/建立/更新商品、寫歷史價格、標記下架）
│   ├── matching/           # 名稱正規化 + 相似度候選（僅供管理員參考，不自動合併）
│   ├── public_api/          # FastAPI app，port 33690
│   ├── admin_api/             # FastAPI app，port 33691
│   └── cli.py                   # 手動抓取、匯入單一 HTML / 整個目錄
├── deploy/
│   ├── coolpc-scraper.service     # systemd oneshot：單次抓取
│   ├── coolpc-scraper.timer         # 每 6 小時觸發
│   ├── coolpc-public.service          # 公開查詢常駐服務
│   └── coolpc-admin.service              # 管理介面常駐服務
├── data/
│   ├── coolpc.db                          # SQLite
│   └── raw_html/YYYY/MM/DD/*.html          # 永久保存原始 HTML（依日期分目錄）
├── docs/superpowers/specs/                  # 設計文件（本文件）與後續規劃文件
└── tests/                                     # 使用真實 HTML 樣本做回歸測試
```

## 四、資料庫 Schema（SQLite + SQLAlchemy + Alembic）

```
categories        (id, name)                                   -- 主分類
subcategories       (id, category_id FK, name)                  -- 子分類

products               -- 商品主體
  id                        PK，穩定永久 ID（自增整數）
  category_id, subcategory_id   -- 目前所屬分類（隨抓取更新）
  current_name                   -- 目前名稱字串；比對鍵，全域唯一（未合併商品間）
  brand, model                    -- 由名稱規則抽取，供搜尋/相似度使用（非必然準確）
  current_status                   -- 現貨/訂/客訂/拆封品/其他，由名稱規則解析
  current_price
  is_active                          -- 在售 / 已下架
  first_seen_at, last_seen_at
  merged_into_id (nullable FK→products.id)   -- 若已被合併，指向目標商品
  created_at

product_names         -- 歷史名稱（含 current_name 本身），一對多
  id, product_id FK, name, first_seen_at, last_seen_at

price_history            -- 價格歷史（主要資料量表）
  id, product_id FK, price, status, badges(熱賣/開箱/圖片等 raw 字串),
  scraped_at（來自 HTML #Mdy 或匯入指定時間）, snapshot_id FK

scrape_snapshots             -- 每次抓取/匯入紀錄
  id, fetched_at, scrape_type(scheduled/manual/import),
  raw_html_path, status(success/partial/failed), error_message,
  total_products, new_products, delisted_products,
  price_up_count, price_down_count

merge_log                       -- 合併操作紀錄，供 undo
  id, source_product_id FK, target_product_id FK,
  merged_at, undone_at (nullable)

similarity_hints                   -- 相似度候選，僅供管理員參考
  id, product_a_id FK, product_b_id FK, score, computed_at, dismissed(bool)

products_fts                          -- SQLite FTS5 虛擬表，索引 product_names.name
```

**比對規則（已與使用者確認）**：每次抓取時，商品名稱字串與資料庫中現有
`product_names`（未被合併者）完全一致 → 視為同一商品，更新 `current_price`
/`current_status`/`last_seen_at`，並寫入一筆 `price_history`。名稱字串有任何
差異（哪怕一個字）→ 視為新商品建立，同時執行相似度比對產生
`similarity_hints` 供管理員參考；**系統本身絕不自動合併**。

**下架/重新上架**：每次抓取完成後，資料庫中 `is_active=true` 但本次快照未
抓到的商品標記 `is_active=false`；若之後重新出現（名稱字串命中），恢復
`is_active=true` 並更新 `last_seen_at`，歷史價格全程保留不受影響。

**合併**：不刪除任何資料。`source.merged_into_id = target.id`；
`source` 名下所有 `product_names` 改掛到 `target`（保留關聯記錄，不刪除）；
查詢 `target` 的歷史價格時，`price_history` 需同時取 `product_id = target.id`
與「所有 `merged_into_id = target.id` 的來源商品」的紀錄聯集呈現。

**Undo 合併**：讀 `merge_log`，清空 `source.merged_into_id`，
`product_names` 關聯改回 `source`，標記 `merge_log.undone_at`。因未刪除任何
資料，操作完全可逆。

## 五、商品名稱正規化與相似度候選

`matching` 模組提供：
- 正規化函式：統一全形/半形符號、去除多餘空白、忽略【】｛｝()等框線符號差異。
- 相似度：以正規化後字串做 `difflib.SequenceMatcher` 比對（比對範圍限制在
  同一主分類內以控制計算量），分數寫入 `similarity_hints`，管理介面顯示
  「可能需要合併的商品」列表，完全由管理員決定是否合併，系統不自動處理。

## 六、搜尋設計

- 商品名稱、舊名稱搜尋：對 `product_names.name` 建立 **SQLite FTS5** 全文
  索引（`products_fts`），支援中文子字串/分詞搜尋，涵蓋「限搭」「抗漲」
  「五年保」「SFX」等任意名稱內關鍵字，取代不可靠的結構化標籤抽取。
- 結構化篩選：分類、子分類、品牌、型號、最低/最高價格、在售/下架、
  `current_status`、最近漲價/降價、漲跌幅範圍。
- 中文搜尋皆以 UTF-8 處理（資料庫內儲存已從 Big5 解碼為 UTF-8）。

## 七、公開查詢服務（port 33690，預設 `0.0.0.0:33690`）

FastAPI + Jinja2 + Chart.js。頁面：
- 商品搜尋（含所有第六節篩選條件）
- 商品列表（名稱、分類、現價、上次價、漲跌額/幅、30天最低/最高、
  在售狀態、最後更新時間）
- 商品詳細頁（歷史名稱、分類/子分類、現價/上次價/漲跌、首次/最後出現時間、
  在售狀態、7/30/90天統計、歷史最低/最高、價格走勢圖 7/30/90/全部/自訂區間、
  下方歷史價格列表、同分類快速加入比較）
- 商品比較（2–5 個商品，多商品疊圖 + 比較表格：現價、7天最低、30天最低/最高、
  歷史最低/最高、最近漲跌）
- JSON API：`GET /api/products`、`/api/products/{id}`、
  `/api/products/{id}/prices`、`/api/products/{id}/stats`、`/api/categories`、
  `/api/compare`。無需登入、無需 API Key。

## 八、管理介面（port 33691，預設 `0.0.0.0:33691`）

FastAPI + Jinja2，無需登入（使用者自行以 nginx 做反向代理與存取限制，本系統
不實作 nginx）：
- 最近抓取時間、成功/失敗狀態、每次抓到商品數、新商品數、下架數、
  漲價/降價商品數（讀 `scrape_snapshots`）
- 手動觸發抓取
- 瀏覽保存的原始 HTML（依 `raw_html_path`）
- 商品搜尋
- 人工合併商品 / Undo 合併
- 可能需要合併的商品列表（讀 `similarity_hints`）

## 九、抓取與排程

- 獨立 CLI 程序（`coolpc-scraper`）負責單次抓取：下載 HTML → 依日期存檔到
  `data/raw_html/` → 呼叫 parser → 呼叫 ingest 寫入 DB → 寫入
  `scrape_snapshots` 紀錄結果。
- 錯誤處理：網路失敗、HTTP 錯誤、HTML 格式異常、parser 失敗皆捕捉並記錄到
  `scrape_snapshots.status=failed/error_message`，**原始 HTML 若已下載成功則
  仍永久保存**，且**失敗不影響/不覆蓋既有商品與價格資料**（DB 寫入用單一
  transaction，失敗即 rollback）。
- 併發保護：抓取程序啟動時取檔案鎖（`data/scraper.lock`），若鎖已存在且
  持有者程序仍存活則直接跳過本次執行並記錄，避免兩次抓取重疊。
- systemd：`coolpc-scraper.timer`（`OnCalendar=*-*-* 0/6:00:00`，
  `Persistent=true` 確保重開機後補跑）觸發 `coolpc-scraper.service`
  （`Type=oneshot`）。`coolpc-public.service`、`coolpc-admin.service` 為
  常駐服務，`WantedBy=multi-user.target` 確保開機自動啟動。所有
  unit file 放在 `deploy/`，README 附安裝指令。
- 手動抓取：CLI 指令與管理介面按鈕皆呼叫同一支抓取函式，共用併發鎖。

## 十、歷史 HTML 匯入

- CLI 支援匯入單一 HTML 檔案，或整個目錄（遞迴掃描 `*.html`）。
- 匯入時使用 HTML 內 `#Mdy` 解析出的估價時間作為該筆 `price_history.scraped_at`
  / `scrape_snapshots.fetched_at`，而非匯入操作當下的系統時間。
- 匯入邏輯與排程抓取共用同一套 parser + ingest pipeline，僅 `scrape_type`
  標記為 `import`。
- 匯入目錄時依檔名（時間戳）排序後依序處理，確保 `first_seen_at`/
  `last_seen_at`/下架判斷邏輯正確反映歷史時間軸。

## 十一、測試策略

使用 `/home/xthybot/coolpc/download` 現有 842 份真實 HTML 樣本（不使用假資料）
建立測試，至少涵蓋：
- HTML 成功解析、中文無亂碼（Big5→UTF-8）
- 商品主分類/子分類正確
- 商品價格正確、後綴標記（★◆熱賣任搭N等）正確排除於名稱本體之外
- 連續匯入多份時間相近樣本後，價格歷史正確累積
- 商品改名後（名稱字串不同）資料不遺失（產生新商品記錄，舊名稱仍可查）
- 商品下架（快照中消失）與重新上架（重新出現）狀態正確
- 人工合併：歷史價格合併查詢、舊名稱搜尋仍可命中合併後商品
- Undo 合併：合併前後狀態完全恢復，無資料遺失
- 商品比較：2–5 個商品統計數據正確

## 十二、部署與交付

README 涵蓋：Ubuntu Server 安裝、`uv` 安裝、建立 venv、安裝 dependencies、
初始化資料庫（Alembic migrate）、啟動公開/管理服務、啟用 systemd timer、
手動抓取指令、匯入舊 HTML 指令、執行測試指令。
