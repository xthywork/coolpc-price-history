# 在新機器上部署與匯入既有 HTML

這份文件講兩件事：**如何在一台全新的 Ubuntu Server 上，從 git 把這個系統
架起來**，以及**如何把一批已經下載好的原價屋 HTML 一次匯入資料庫**。

日常維運（備份策略、日誌檢查、日後 schema 變更的操作程序）另見
[`deployment.md`](deployment.md)。

---

# 第一部分：在新的 Ubuntu Server 上部署

開始之前有兩個前提要先知道：

1. **這是 private repo**，新機器必須先設定好 GitHub 認證才能 clone。
2. **資料庫不在版控裡**。`.gitignore` 排除了 `data/coolpc.db` 與
   `data/raw_html/`，所以 clone 下來只有程式碼，資料庫是空的——既有的商品
   與價格歷史不會跟著過去，要另外搬（見步驟 5）。

## 1. 準備作業系統

```bash
sudo apt update
sudo apt install -y git curl sqlite3
```

不需要另外安裝 Python。專案要求 Python 3.12 以上，但下一步的 uv 會自動下載
並管理對應版本，所以即使是 Ubuntu 22.04（內建 Python 3.10）也不必自己處理。
前端沒有任何 npm / build 步驟。

## 2. 設定 GitHub 認證

三種方式擇一。

**方式 A：SSH deploy key（推薦，適合長期運行的伺服器）**

```bash
ssh-keygen -t ed25519 -C "coolpc-server" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

把印出來的公鑰貼到 GitHub 專案的 Settings → Deploy keys → Add deploy key，
只給讀取權限即可。

**方式 B：GitHub CLI**

```bash
sudo apt install -y gh
gh auth login
```

**方式 C：HTTPS + Personal Access Token**

clone 時帳號填 GitHub 使用者名稱，密碼欄位填 token。

## 3. Clone 專案

```bash
sudo mkdir -p /opt && cd /opt
sudo git clone git@github.com:xthybot/coolpc-price-history.git
cd coolpc-price-history
```

預設會拿到 `main` 分支。若要部署某個特定的釋出版本：

```bash
git checkout v2.0.0
```

建立專用系統帳號並移交所有權（符合最小權限原則，`deploy/*.service` 預設也
是用這個帳號執行）：

```bash
sudo useradd -r -s /usr/sbin/nologin coolpc
sudo chown -R coolpc:coolpc /opt/coolpc-price-history
```

## 4. 安裝 uv 與相依套件

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

cd /opt/coolpc-price-history
uv venv
uv sync
```

`uv venv` 會在專案下建立 `.venv/`，`deploy/*.service` 裡的 `ExecStart` 就是
指向 `/opt/coolpc-price-history/.venv/bin/uvicorn`。

## 5. 準備資料庫

這裡要先決定：新機器是要**從零開始累積**，還是要**沿用既有的歷史資料**。

### 選項 A：全新開始

```bash
uv run alembic upgrade head
```

會在 `data/coolpc.db` 建立所有資料表（空的），之後靠排程抓取逐步累積價格
歷史。

### 選項 B：把既有資料搬過來

資料庫是 SQLite 的 WAL 模式，**不能直接 `cp`/`rsync` 複製 `.db` 檔案**——還
沒 checkpoint 回主檔案的交易會留在 `-wal` 檔裡，直接複製會拿到一份缺資料的
舊快照。正確做法是用 `VACUUM INTO` 產生一致快照。

在**舊機器**上：

```bash
# 資料庫：用 VACUUM INTO 取一致快照（會自動處理 WAL 合併）
sqlite3 /path/to/old/data/coolpc.db "VACUUM INTO '/tmp/coolpc-snapshot.db'"
scp /tmp/coolpc-snapshot.db 新機器:/tmp/

# 原始 HTML 封存：是靜態檔案，可以直接 rsync
rsync -av /path/to/old/data/raw_html/ 新機器:/opt/coolpc-price-history/data/raw_html/
```

在**新機器**上：

```bash
sudo mv /tmp/coolpc-snapshot.db /opt/coolpc-price-history/data/coolpc.db
sudo chown -R coolpc:coolpc /opt/coolpc-price-history/data

# 確認 schema 已在最新版（若舊機器版本較舊，這裡會補跑缺少的 migration）
cd /opt/coolpc-price-history
uv run alembic upgrade head
```

> **注意**：如果是「搬家」而不是多開一台，記得把舊機器的排程停掉
> （`sudo systemctl disable --now coolpc-scraper.timer`），否則兩台會各自
> 繼續累積不同的價格歷史而分岔。

## 6. 手動啟動確認可以跑

正式掛 systemd 之前，先在前景各跑一次確認沒問題：

```bash
uv run uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690
# 另開一個終端
uv run uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691
```

用瀏覽器或 `curl` 確認兩個服務都回 200 之後，Ctrl-C 停掉，繼續下一步。

## 7. 設定 systemd 常駐服務與抓取排程

```bash
sudo cp deploy/coolpc-public.service deploy/coolpc-admin.service \
        deploy/coolpc-scraper.service deploy/coolpc-scraper.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable --now coolpc-public.service
sudo systemctl enable --now coolpc-admin.service
sudo systemctl enable --now coolpc-scraper.timer     # 每 6 小時自動抓取
```

`deploy/*.service` 內預設安裝路徑是 `/opt/coolpc-price-history`、執行帳號是
`coolpc`。若您的路徑或帳號不同，**複製到 `/etc/systemd/system/` 之前**要先
修改檔案內的 `WorkingDirectory`、`ExecStart`、`User`、`Group` 與
`Environment=COOLPC_DB_PATH=`。

檢查狀態：

```bash
systemctl status coolpc-public.service coolpc-admin.service
systemctl list-timers coolpc-scraper.timer
journalctl -u coolpc-scraper.service -n 50
```

## 8. 網路存取

```bash
sudo ufw allow 33690/tcp    # 公開查詢服務
```

**管理介面（33691）沒有任何身分驗證機制**，不建議直接對公網開放。實務上請
擇一：

- 只在本機/內網開放，需要時透過 SSH port forwarding 存取
- 用 nginx（或其他反向代理）加上來源 IP 限制或 HTTP 基本認證，再轉發到
  `127.0.0.1:33691`

---

# 第二部分：一次匯入一批既有的 HTML

如果手上已經有一批下載好的原價屋估價頁 HTML，可以用 `import-dir` 一次全部
匯入：

```bash
cd /opt/coolpc-price-history
uv run coolpc-scraper import-dir /path/to/html/dir
```

## 它實際會做什麼

- **遞迴**尋找該目錄底下所有 `*.html`（含子目錄），依**檔案路徑字母排序**後
  逐一處理
- 每份檔案的時間戳取自 **HTML 內容裡的估價時間**，不是檔名、也不是匯入當下
  的系統時間
- 每處理完一份就印一行結果：
  `[success] fetched_at=... total=... new=... delisted=... up=... down=...`
- 任何一份檔案失敗，最後的 exit code 會是非 0

## 四個必須注意的地方

### 1. 排序是照檔名，但時間先後很重要

匯入是有狀態的：每一份快照都會把「這次沒出現的商品」標記為下架。因此檔案
**必須依時間先後順序處理**，而程式是照檔案路徑字母排序。

`2026-02-01-21-40.html` 這種命名剛好字母排序等於時間排序，沒有問題。但如果
檔名格式不一致（例如混入 `1.html`、`2.html`、`10.html`，字母排序會變成
1、10、2），順序就會錯亂，商品的上下架狀態會不正確。匯入前請先確認檔名排序
與時間順序一致。

另外只會比對小寫的 `.html`，副檔名是 `.htm` 或 `.HTML` 的檔案不會被抓到。

### 2. 可以重複執行，不會重複匯入

判斷依據是 HTML 內的估價時間：同一個時間點若已經有匯入成功（`success` 或
`partial`）的紀錄，會直接沿用既有快照、不重新處理，不會重複寫入價格歷史。
所以匯入中途被打斷，直接重跑同一個目錄是安全的。

### 3. 匯入不會複製檔案，只記下路徑

這點跟排程抓取不同。排程抓取會把 HTML 存進 `data/raw_html/`；**匯入則只是把
您指定的來源路徑記在資料庫裡**。管理後台的「原始 HTML 封存」頁面是直接開啟
那個路徑的檔案。

因此請**在匯入之前先把 HTML 資料夾放到最終位置**（建議放
`/opt/coolpc-price-history/data/raw_html/` 底下），匯入之後不要再搬動或刪除，
否則封存頁面會找不到檔案。

### 4. 匯入期間先停掉排程抓取

匯入沒有跟排程抓取共用併發鎖，兩者同時執行可能讓快照的時間順序錯亂：

```bash
sudo systemctl stop coolpc-scraper.timer
```

## 建議的完整操作流程

檔案數量多的時候（數百份以上）會跑很久，建議丟到背景並保留 log：

```bash
sudo systemctl stop coolpc-scraper.timer

cd /opt/coolpc-price-history
nohup uv run coolpc-scraper import-dir /opt/coolpc-price-history/data/raw_html \
  > /tmp/import.log 2>&1 &
```

追蹤進度：

```bash
tail -f /tmp/import.log
grep -c '^\[success\]' /tmp/import.log      # 已成功匯入幾份
grep '^\[failed\]'  /tmp/import.log         # 有沒有失敗的
grep '^\[partial\]' /tmp/import.log         # 有沒有被 I6 保護機制擋下的
```

> `partial` 代表該份 HTML 解析到的商品數低於前一次成功快照的 70%，系統判定
> 可能是解析不完整，會跳過下架比對以策安全。詳見
> [`database-schema.md`](database-schema.md) 的 `scrape_snapshots` 狀態機說明。

匯入完成後驗證結果：

```bash
sqlite3 data/coolpc.db "
SELECT status, COUNT(*) FROM scrape_snapshots WHERE scrape_type='import' GROUP BY status;
SELECT COUNT(*) AS products FROM products;
SELECT COUNT(*) AS price_rows FROM price_history;
SELECT MIN(fetched_at), MAX(fetched_at) FROM scrape_snapshots;"
```

確認無誤後把排程開回來：

```bash
sudo systemctl start coolpc-scraper.timer
```

## 容量參考值

實際匯入 842 份 HTML（450 個獨立時間點）之後的規模，可以用來估算磁碟需求：

| 項目 | 數量 |
|---|---|
| 商品 | 19,194（其中 6,488 為上架中） |
| 分類 | 30 |
| 價格歷史紀錄 | 約 299 萬筆 |
| 資料庫檔案大小 | 約 337 MB |

平均一份 HTML 快照會讓資料庫成長約 0.7 MB，另外還要加上原始 HTML 檔案本身
所佔的空間。

## 單一檔案匯入

只要匯入一份檔案時用 `import-html`，行為與上述完全相同（一樣讀 HTML 內嵌的
估價時間、一樣不複製檔案、一樣可重複執行）：

```bash
uv run coolpc-scraper import-html /path/to/2026-02-01-21-40.html
```
