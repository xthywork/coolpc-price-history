# 原價屋歷史價格查詢系統 (coolpc-price-history)

從原價屋官方估價網頁定期抓取商品價格，永久保存原始 HTML，解析出結構化商品
與價格資料，提供歷史價格查詢、走勢圖、多商品比較、公開查詢 API，以及一套
商品資料整理用的管理介面（含手動編輯商品欄位、新增分類、以相似度為基礎的
重複商品合併建議）。

**本系統執行期間不使用 AI / LLM / Agent 進行任何商品判斷。** 分類歸屬、
新舊商品比對、重複商品的合併方向，全部都是確定性（deterministic）的程式
規則，不涉及任何模型推論，行為可重現、可測試。

- **要動這個專案的程式碼（人或 agent）請先讀 [`AGENTS.md`](AGENTS.md)**：
  開發慣例與踩過的地雷（路由註冊順序、匯入時序、WAL 備份等）。
- 完整文件索引：[`docs/`](docs/)
- 原始設計文件（初版，部分內容已隨系統演進而過時，見
  [`docs/architecture.md`](docs/architecture.md) 開頭的「與原始設計文件的差異」）：
  [`docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md`](docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md)

## 系統概觀

```
原價屋估價頁 (evaluate.php)
        │  cp950/Big5 編碼的 HTML
        ▼
   scraper.fetcher  ──── 永久保存原始 HTML ──▶  data/raw_html/YYYY/MM/DD/*.html
        │
        ▼
   parser.html_parser  （BeautifulSoup + lxml，純規則式解析，見
        │                docs/architecture.md 的解析細節）
        ▼
   ingest.service  （新增/更新商品、寫入價格歷史、依商品名稱完全相等比對）
        │
        ▼
      SQLite (data/coolpc.db，WAL 模式)
        │
   ┌────┴────────────────────────────┐
   ▼                                  ▼
public_api（0.0.0.0:33690）      admin_api（0.0.0.0:33691）
公開查詢頁 + JSON API              抓取狀態 / 商品編輯 / 相似商品合併
```

- 兩個服務各自是獨立的 FastAPI app、獨立的 uvicorn 進程、共用同一個 SQLite
  資料庫檔案，皆不需要登入。
- 前端一律是 Jinja2 伺服端渲染 + 原生 JavaScript，**刻意不使用任何前端框架**
  （React/Vue 等），也沒有任何建置流程。共用的 CSS、字體與少量原生 JS 放在
  `src/coolpc/web/static/`，兩個服務各自 mount 到 `/static`，外觀由一組
  CSS 變數（token）統一控制，支援跟隨系統的明暗主題。第三方資產（IBM Plex
  Mono 字體、Chart.js）一律 self-host，不依賴外部 CDN。
- ORM 為 SQLAlchemy 2.0（`Mapped[...]` 型別註記風格），schema 演進透過
  Alembic migration 管理，不使用 `create_all` 讓正式環境自動長欄位。

完整架構說明見 [`docs/architecture.md`](docs/architecture.md)。

## 系統需求

- Ubuntu Server 22.04 以上（其他有 systemd 的 Linux 發行版亦可）
- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)

## 安裝

```bash
git clone <此專案的 git remote URL> /opt/coolpc-price-history
cd /opt/coolpc-price-history
```

建議建立一個專用系統帳號執行本服務（非必要，但符合最小權限原則）：

```bash
sudo useradd -r -s /usr/sbin/nologin coolpc
sudo chown -R coolpc:coolpc /opt/coolpc-price-history
```

安裝 uv：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

建立 venv 並安裝相依套件：

```bash
cd /opt/coolpc-price-history
uv venv
uv sync
```

初始化資料庫（在 `data/coolpc.db` 建立所有資料表，執行到目前最新的
migration）：

```bash
uv run alembic upgrade head
```

`data/raw_html/` 目錄用於永久保存每次抓取的原始 HTML，請確保有足夠磁碟空間
並定期備份整個 `data/` 目錄（資料庫 + 原始 HTML）。備份與日後 schema 變更的
操作程序見 [`docs/deployment.md`](docs/deployment.md)。

## 執行

啟動公開查詢服務（`0.0.0.0:33690`）：

```bash
uv run uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690
```

啟動管理介面（`0.0.0.0:33691`）：

```bash
uv run uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691
```

兩個服務皆不需要登入、不內建任何存取控制。本系統不實作 nginx；若要限制
管理介面的存取來源，請自行在 nginx（或其他反向代理）設定存取限制，並將
對外流量導向 `127.0.0.1:33690`（公開）與 `127.0.0.1:33691`（管理）。

### systemd 部署

有兩種安裝方式，**兩者的 unit 檔位置、執行帳號、指令都不同，不要混用**：

| | 系統層級 | 使用者層級 |
|---|---|---|
| unit 檔位置 | `/etc/systemd/system/` | `~/.config/systemd/user/` |
| 範本來源 | repo 的 `deploy/*.service` | 依現場路徑自行撰寫 |
| 需要 sudo | 是 | 否 |
| 執行帳號 | 專用的 `coolpc` 帳號 | 目前登入的使用者 |
| 指令 | `sudo systemctl ...` | `systemctl --user ...` |
| 適用情境 | 正式環境（`/opt` 安裝） | 沒有 sudo 權限、或裝在家目錄 |

#### 系統層級（正式環境，需要 sudo）

```bash
sudo cp deploy/coolpc-scraper.service deploy/coolpc-scraper.timer \
        deploy/coolpc-public.service deploy/coolpc-admin.service \
        /etc/systemd/system/
sudo systemctl daemon-reload

# 排程抓取（每 6 小時一次，見 deploy/coolpc-scraper.timer 的 OnCalendar；
# 重開機期間錯過的排程會依 Persistent=true 補跑）
sudo systemctl enable --now coolpc-scraper.timer

# 公開查詢與管理介面常駐服務
sudo systemctl enable --now coolpc-public.service
sudo systemctl enable --now coolpc-admin.service
```

`deploy/*.service` 內預設路徑為 `/opt/coolpc-price-history`、執行使用者為
`coolpc`；若安裝路徑或執行使用者不同，請先修改這些檔案內的
`WorkingDirectory`、`ExecStart`、`User`、`Group`、`Environment=COOLPC_DB_PATH=...`
再複製到 `/etc/systemd/system/`。

檢查排程與服務狀態：

```bash
systemctl list-timers coolpc-scraper.timer
systemctl status coolpc-scraper.service
systemctl status coolpc-public.service
systemctl status coolpc-admin.service
journalctl -u coolpc-scraper.service -n 50
```

#### 使用者層級（不需要 sudo）

沒有 sudo 權限、或專案裝在家目錄時，可以改用 user-level systemd。unit 檔放
在 `~/.config/systemd/user/`，內容與 `deploy/*.service` 類似，但要拿掉
`User=`／`Group=`（user service 本來就以該使用者身分執行），並把 service 的
`WantedBy` 由 `multi-user.target` 改成 `default.target`；`WorkingDirectory`、
`ExecStart`、`Environment=COOLPC_DB_PATH=` 改成實際安裝路徑。

```bash
systemctl --user daemon-reload
systemctl --user enable --now coolpc-public.service coolpc-admin.service
systemctl --user enable --now coolpc-scraper.timer

# 讓服務在登出後仍繼續執行、並在開機時自動啟動（只需設定一次）
loginctl enable-linger "$USER"
```

狀態檢查同樣要加 `--user`：

```bash
systemctl --user status coolpc-public.service
systemctl --user list-timers coolpc-scraper.timer
journalctl --user -u coolpc-scraper.service -n 50
```

**注意**：`systemctl` 不加 `--user` 會去找系統層級的 unit，對這組服務會顯示
「找不到」。

完整部署細節（含資料庫備份策略、日後 schema migration 的正確操作流程）見
[`docs/deployment.md`](docs/deployment.md)；在全新機器上從 git 佈署的逐步流程
見 [`docs/new-machine-setup.md`](docs/new-machine-setup.md)。

## CLI 手動操作

安裝後可用 `coolpc-scraper` 指令（定義於 `src/coolpc/cli.py`，
`pyproject.toml` 的 `[project.scripts]` 註冊為 `coolpc-scraper`）：

```bash
# 手動觸發一次抓取（跟排程共用同一組併發鎖，不會同時執行兩次）
uv run coolpc-scraper scrape --manual

# 匯入單一 HTML 檔案（使用檔案內嵌的估價時間，而非匯入當下的系統時間）
uv run coolpc-scraper import-html /path/to/2026-02-01-21-40.html

# 匯入整個目錄（遞迴尋找所有 *.html，依完整檔案路徑排序後依序處理）
uv run coolpc-scraper import-dir /path/to/html/dir
```

也可以透過管理介面首頁（`http://<主機>:33691/`）點擊「手動執行抓取」按鈕
達到跟 `scrape --manual` 相同的效果。

批次匯入前請先看
[`docs/new-machine-setup.md`](docs/new-machine-setup.md#第二部分一次匯入一批既有的-html)
的注意事項，其中幾點很容易踩到：

- **處理順序是檔案路徑字母序，不是內嵌估價時間**。因為每份快照都會把「這次
  沒出現的商品」標記為下架，檔案順序必須與時間順序一致；`YYYY-MM-DD-HH-MM`
  這類命名剛好符合。
- **匯入不會複製檔案**，資料庫只記下來源路徑（後台的原始 HTML 檢視會直接開
  那個路徑），所以要先把檔案放到最終位置再匯入。
- **匯入以估價時間判斷重複**，同一個時間點重跑不會重複寫入，中斷後可安全重來。
- **匯入不受抓取併發鎖保護**，大批匯入前先停掉排程
  （`systemctl --user stop coolpc-scraper.timer`）。

## 執行測試

```bash
uv run pytest
```

大多數測試不需要任何外部資料即可執行。其中解析器、scraper、CLI 與端對端
回歸測試（目前是 `tests/parser/`、`tests/scraper/` 底下的檔案，加上
`tests/test_cli.py` 與 `tests/test_regression_real_html.py`；確切清單可用
`grep -rl COOLPC_SAMPLE_DIR tests/` 查）會用到一份不納入版控的真實原價屋
HTML 樣本語料庫；預設路徑是 `/home/xthybot/coolpc/download`，可用
`COOLPC_SAMPLE_DIR` 環境變數指向其他位置，**找不到語料庫時這些測試會自動
skip，不會讓測試套件失敗**。

測試涵蓋 HTML 解析（含 cp950/Big5 編碼、多種降價/漲價標記格式、促銷倒數
尾綴清理）、分類/子分類建立、價格更新、改名、下架/重新上架、人工合併、
Undo 合併、相似度合併建議、AND/OR 搜尋語意、分頁、商品比較、管理後台商品
編輯與新增分類等情境。開發慣例（TDD 流程、如何新增 migration）見
[`docs/development.md`](docs/development.md)。

## 環境變數

| 變數 | 說明 | 預設值 |
|---|---|---|
| `COOLPC_DB_PATH` | SQLite 資料庫檔案路徑 | `data/coolpc.db` |
| `COOLPC_EVALUATE_URL` | 原價屋估價頁網址 | `https://coolpc.com.tw/evaluate.php` |
| `COOLPC_SAMPLE_DIR` | 端對端回歸測試用的真實 HTML 樣本語料庫路徑（僅測試使用） | `/home/xthybot/coolpc/download` |

## 功能總覽

### 公開查詢服務（`:33690`）

- **商品搜尋首頁**：關鍵字（AND 語意，見
  [`docs/search-semantics.md`](docs/search-semantics.md)）、分類/子分類、
  品牌、上架狀態、價格區間（即時 AJAX 篩選、不整頁重載）、多種排序；數字
  頁碼分頁（可指定每頁筆數：10/20/50/100/500/1000/全部、可直接跳頁），並
  在切換每頁筆數時保留原本的捲動位置。
- **商品詳細頁**：目前價格、歷史最低/最高、漲跌幅、價格走勢圖（7/30/90天/
  全部/自訂區間）、歷史名稱清單、加入比較。
- **商品比較頁**：同時比較 2 至 5 個商品，透過搜尋輸入框 + 下拉選單挑選商品
  （chip 形式呈現已選商品），並排顯示價格走勢圖與統計數據。
- **自動排除廣告項目**：原價屋的估價單裡混有活動公告、運費／安裝說明、保固
  通知這類非商品項目，一律標價 1 元。公開端的搜尋頁、`/api/products`、比較頁
  的商品挑選都會把它們濾掉（它們沒有價格可查）；**管理介面則維持看得到**，
  才能編輯或合併這些項目。判斷條件是「價格剛好等於 1」，實際資料裡沒有任何
  真商品賣 1 元。
- **JSON API**：無需登入或 API Key。

  | 端點 | 用途 |
  |---|---|
  | `GET /api/categories` | 全部分類 |
  | `GET /api/products` | 商品列表查詢（關鍵字、分類、品牌、價格區間、排序、分頁） |
  | `GET /api/products/autocomplete` | 名稱自動完成（AND 語意、不限筆數） |
  | `GET /api/products/sparklines` | 批次取多個商品的迷你走勢資料點（一次最多 100 個） |
  | `GET /api/products/{id}` | 單一商品詳細資料與統計 |
  | `GET /api/products/{id}/prices` | 該商品的歷史價格序列（可指定區間） |
  | `GET /api/products/{id}/stats` | 該商品的價格統計 |
  | `GET /api/compare?ids=1,2,3` | 多商品比較（2～5 個） |

  參數、回應格式與範例見
  [`docs/api-reference.md`](docs/api-reference.md)。

### 管理介面（`:33691`）

- **抓取狀態首頁**：全部抓取/匯入紀錄（狀態、新增/下架/漲跌數量），分頁
  機制與公開搜尋頁一致；「手動執行抓取」按鈕。原始 HTML 封存沒有獨立列表
  頁，檔案路徑掛在對應那一列的滑鼠提示上，估價時間可點入檢視完整內容。
- **商品搜尋 / 詳細編輯頁**：列表欄位為 ID、商品名稱、品牌、目前價格、
  狀態（販售中／已下架）、建立時間；商品名稱可點入詳細頁查看/編輯完整
  欄位（分類、子分類、品牌、型號、原始狀態文字、目前價格、是否在售），
  分類/子分類以下拉選單編輯，並可在編輯畫面直接「+ 新增類別」。搜尋輸入
  框與分頁機制與公開搜尋頁一致。可勾選 2 至 5 個商品，在新分頁開啟公開
  比較頁，或帶入管理站的手動合併頁批次處理。
- **合併商品（相似度建議）**：系統依名稱相似度（見
  [`docs/architecture.md`](docs/architecture.md) 的相似度比對章節）自動抓出
  候選重複商品，可個別合併/忽略，或勾選後一次全部合併。
- **手動合併**：搜尋或從商品列表帶入 2 至 5 個商品，指定一個保留商品後
  批次合併其餘商品（不依賴相似度分數）；任一項無效時整批不會合併，每個
  來源商品仍可在合併紀錄列表逐筆 Undo。

完整操作說明見 [`docs/admin-guide.md`](docs/admin-guide.md)。

## 資料庫

現行 schema（migration `0007_drop_product_first_seen_at`，最新 head）欄位
總覽與各表用途見 [`docs/database-schema.md`](docs/database-schema.md)。

## 目錄結構

```
src/coolpc/
  db/                 SQLAlchemy models、engine/session 建立
  parser/             HTML 解析（cp950 解碼、名稱/價格/狀態切分）
  ingest/             解析結果寫入資料庫（新增/更新商品、價格歷史）
  scraper/            HTTP 抓取、原始 HTML 保存、抓取併發鎖
  matching/           商品名稱正規化、相似度計算與合併候選產生
  merging/            合併方向決策、實際合併/Undo 邏輯
  stats/               價格統計（含合併鏈追蹤）
  search/              商品搜尋（AND/OR 語意）
  query_types.py       把空字串正規化成 None 的 Pydantic 查詢參數型別
  public_api/           公開服務：FastAPI app、routers、templates、schemas
  admin_api/             管理介面：FastAPI app、routers、templates
  web/static/           兩個服務共用的前端資產（CSS token、字體、原生 JS）
  cli.py                coolpc-scraper 命令列工具
deploy/                 systemd unit 檔案（抓取排程、兩個常駐服務）
data/                   SQLite 資料庫與永久保存的原始 HTML（不納入版控）
migrations/             Alembic migration
tests/                   測試（含真實 HTML 樣本端對端回歸測試）
docs/                    完整專案文件（見下方文件索引）
docs/superpowers/        初版設計文件與各階段實作計畫（歷史留存，非最新狀態）
AGENTS.md                開發慣例與地雷（接手改程式碼前必讀）
```

## 文件索引

| 文件 | 內容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **開發慣例與地雷**：接手改這個專案前必讀 |
| [`docs/architecture.md`](docs/architecture.md) | 系統架構、資料流、解析/比對/合併邏輯細節 |
| [`docs/database-schema.md`](docs/database-schema.md) | 完整資料表/欄位說明，含已移除欄位紀錄 |
| [`docs/api-reference.md`](docs/api-reference.md) | 公開 JSON API 完整參考 |
| [`docs/admin-guide.md`](docs/admin-guide.md) | 管理介面逐頁操作說明 |
| [`docs/search-semantics.md`](docs/search-semantics.md) | AND/OR 搜尋語意詳細規則 |
| [`docs/deployment.md`](docs/deployment.md) | 正式環境部署、備份、schema migration 操作程序 |
| [`docs/new-machine-setup.md`](docs/new-machine-setup.md) | 在新機器上從 git 佈署、批次匯入既有 HTML |
| [`docs/development.md`](docs/development.md) | 開發慣例、TDD 流程、新增 migration |
