# 在新機器上部署與匯入既有 HTML

這份文件講兩件事：**如何在一台全新的 Ubuntu Server 上，從 git 把這個系統
架起來**，以及**如何把一批已經下載好的原價屋 HTML 一次匯入資料庫**。

日常維運（備份策略、日誌檢查、日後 schema 變更的操作程序）另見
[`deployment.md`](deployment.md)。

本文件第一部分以安裝在 `/opt/coolpc-price-history`、使用專用 `coolpc` 帳號
的**系統層級 systemd** 為範例；`deploy/*.service` 也只適用於此模式。
**目前這台機器改用使用者層級 systemd**，unit 位於
`~/.config/systemd/user/`，所有服務操作須用 `systemctl --user`／
`journalctl --user`，不要把下方的 `sudo systemctl` 命令直接用在這台機器。
第二部分範例中的 `/opt/coolpc-price-history` 與 `sudo -u coolpc` 也屬於
系統層級部署；在這台機器上請改用實際專案路徑
`/home/xthybot/coolpc-price-history`，並以目前登入帳號直接執行 CLI。
兩種模式的對照見 [README 的 systemd 部署段落](../README.md#systemd-部署)。

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
sudo apt install -y git curl sqlite3 rsync
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
sudo install -m 755 "$(command -v uv)" /usr/local/bin/uv
sudo -u coolpc env UV_CACHE_DIR=/opt/coolpc-price-history/.uv-cache \
  UV_PYTHON_INSTALL_DIR=/opt/coolpc-price-history/.uv-python \
  /usr/local/bin/uv venv --python 3.12
sudo -u coolpc env UV_CACHE_DIR=/opt/coolpc-price-history/.uv-cache \
  UV_PYTHON_INSTALL_DIR=/opt/coolpc-price-history/.uv-python \
  /usr/local/bin/uv sync
sudo -u coolpc mkdir -p data/raw_html
```

前一步已把專案交給 `coolpc`；建立 `.venv/`、安裝相依套件時也要以
`coolpc` 身分執行，否則會在它擁有的目錄裡產生其他帳號的檔案。
安裝程式會把 `uv` 放到維運帳號的家目錄，所以先複製可執行檔到共用的
`/usr/local/bin/uv`，並明確指定 `coolpc` 可寫入的快取與 Python 安裝位置；
不依賴 `nologin` 系統帳號的家目錄存在。`deploy/*.service` 的 `ExecStart`
指向 `/opt/coolpc-price-history/.venv/bin/` 內的執行檔。

## 5. 準備資料庫

這裡要先決定：新機器是要**從零開始累積**，還是要**沿用既有的歷史資料**。

### 選項 A：全新開始

```bash
cd /opt/coolpc-price-history
sudo -u coolpc .venv/bin/alembic upgrade head
```

會在 `data/coolpc.db` 建立所有資料表（空的），之後靠排程抓取逐步累積價格
歷史。

### 選項 B：把既有資料搬過來

資料庫是 SQLite 的 WAL 模式，**不能直接 `cp`/`rsync` 複製 `.db` 檔案**——還
沒 checkpoint 回主檔案的交易會留在 `-wal` 檔裡，直接複製會拿到一份缺資料的
舊快照。正確做法是用 `VACUUM INTO` 產生一致快照。

在**舊機器**上先停止排程及正在執行的 scraper，確認沒有手動抓取或匯入
仍在寫入，再取資料庫快照、同步 HTML。若舊機器和目前這台一樣採用
user-level systemd：

```bash
systemctl --user stop coolpc-scraper.timer coolpc-scraper.service
systemctl --user status coolpc-scraper.timer coolpc-scraper.service
```

若舊機器採用 `deploy/` 的 system-level unit，則用
`sudo systemctl stop coolpc-scraper.timer coolpc-scraper.service`；搬家不再
啟動舊機器時，另外停用 timer。若舊機器仍有網站服務可手動觸發抓取，
也要停用該入口或停止舊服務後再搬遷。下方 `/path/to/old/data/` 須換成
舊機器的實際路徑；若來源檔案不屬於目前帳號，改由具備讀取權限的帳號執行。

### 搬遷順序：新機器預檢 → 舊機器建立並傳送 → 新機器驗證並匯入

先在**新機器**執行接收端預檢，再回到舊機器建立快照並傳送檔案，最後才在
新機器執行驗證與匯入。預檢會拒絕已存在的暫存路徑（包含失效符號連結）；
請先人工查明並處理既有檔案，不要刪除或覆蓋它們。

在**新機器**上，傳送前執行：

```bash
if [ -e /tmp/coolpc-snapshot.db ] || [ -L /tmp/coolpc-snapshot.db ] || \
   [ -e /tmp/coolpc-raw-html ] || [ -L /tmp/coolpc-raw-html ] || \
   [ -e /tmp/coolpc-raw-html.sha256 ] || [ -L /tmp/coolpc-raw-html.sha256 ]; then
  printf '%s\n' '接收端暫存路徑已有檔案或符號連結；停止搬遷，請先檢查。' >&2
  exit 1
fi
```

只有預檢成功後才開始傳送。預檢與傳送之間若有其他程序建立這些路徑，也要
停止並查明，不可沿用既有內容。

在**舊機器**上：

```bash
set -e  # 以下指令有任何一步失敗就停止，不傳送先前留下的快照
if [ -e /tmp/coolpc-snapshot.db ] || [ -L /tmp/coolpc-snapshot.db ]; then
  printf '%s\n' '暫存快照路徑已存在（含失效的符號連結）；停止搬遷，請先檢查。' >&2
  exit 1
fi
if [ -e /tmp/coolpc-raw-html.sha256 ] || [ -L /tmp/coolpc-raw-html.sha256 ]; then
  printf '%s\n' 'HTML 校驗清單路徑已存在；停止搬遷，請先檢查。' >&2
  exit 1
fi

# 資料庫：用 VACUUM INTO 取一致快照（會自動處理 WAL 合併）
sqlite3 /path/to/old/data/coolpc.db "VACUUM INTO '/tmp/coolpc-snapshot.db'"
scp /tmp/coolpc-snapshot.db 新機器:/tmp/

# 建立 HTML 相對路徑與 SHA-256 清單，供接收端驗證完整性
cd /path/to/old/data/raw_html
find . -type f -name '*.html' -exec sha256sum -- {} + > /tmp/coolpc-raw-html.sha256
test -s /tmp/coolpc-raw-html.sha256
scp /tmp/coolpc-raw-html.sha256 新機器:/tmp/

# 傳送原始 HTML 封存至新機器的暫存目錄
rsync -av /path/to/old/data/raw_html/ 新機器:/tmp/coolpc-raw-html/
```

請在同一個 shell 執行完整區塊；若快照路徑已有檔案或符號連結，先查明來源，
不要覆蓋或刪除。`VACUUM INTO`、任一 `scp`、`rsync` 或校驗清單建立失敗都應
停止搬遷；不要在新機器使用未完成或先前留下的暫存檔。

在**新機器**上：

必須先驗證傳送結果，再複製任何檔案。下列區塊以 `set -e` 遇到失敗即停止；
缺少快照、清單、HTML 目錄或任一清單列出的檔案，或內容校驗不符，都會中止，
不會執行後續資料庫複製、HTML 安裝或 Alembic 檢查：

先確認目標資料庫不存在。若 `data/coolpc.db` 已存在，**立即停止搬遷**，
先備份並判斷那份資料是否要保留、合併或另行處理；不要用舊機器快照
直接覆蓋它。以下 guard 連指向不存在檔案的符號連結也會擋下；`cp -n`
再次避免覆蓋，複製後核對內容；若目標在檢查後才被建立且內容不同，
也會停止搬遷：

```bash
set -e

test -s /tmp/coolpc-snapshot.db
test -s /tmp/coolpc-raw-html.sha256
test -d /tmp/coolpc-raw-html
(cd /tmp/coolpc-raw-html && sha256sum -c /tmp/coolpc-raw-html.sha256)

if sudo test -e /opt/coolpc-price-history/data/coolpc.db || \
   sudo test -L /opt/coolpc-price-history/data/coolpc.db; then
  printf '%s\n' '目標資料庫已存在；停止搬遷，先備份並判斷如何處理。' >&2
  exit 1
fi
sudo cp -n /tmp/coolpc-snapshot.db /opt/coolpc-price-history/data/coolpc.db || exit 1
if ! sudo cmp -s /tmp/coolpc-snapshot.db /opt/coolpc-price-history/data/coolpc.db; then
  printf '%s\n' '目標資料庫與快照不同；停止搬遷，先檢查目標檔案。' >&2
  exit 1
fi
sudo mkdir -p /opt/coolpc-price-history/data/raw_html
sudo rsync -av /tmp/coolpc-raw-html/ /opt/coolpc-price-history/data/raw_html/
sudo chown -R coolpc:coolpc /opt/coolpc-price-history/data

# 先確認舊機器資料庫的 schema 版本
cd /opt/coolpc-price-history
sudo -u coolpc .venv/bin/alembic current
```

若版本落後，先依 [`deployment.md`](deployment.md#schema-變更新增-alembic-migration的正式環境操作程序)
在快照上演練並核對列數，再對這份資料庫執行 `sudo -u coolpc
.venv/bin/alembic upgrade head`。確認資料與封存路徑無誤後，再啟動服務。

搬家時請讓舊機器的 timer 保持停用，否則兩台會各自累積不同的價格歷史而
分岔。系統層級用 `sudo systemctl disable --now coolpc-scraper.timer`；
使用者層級用 `systemctl --user disable --now coolpc-scraper.timer`。

**搬遷後要核對 `raw_html_path`**：資料庫儲存的是抓取或匯入當時的路徑，
複製資料庫與 HTML 不會自動改寫它。排程抓取通常記錄相對路徑
`data/raw_html/...`，只要新機器服務的 `WorkingDirectory` 仍是專案根目錄、
且檔案搬到相同相對位置，路徑即可繼續使用。匯入可能記錄絕對路徑或其他
相對路徑；先用下列查詢抽查，再選擇**在新機器保留原路徑及讀取權限**，
或**在備份後明確改寫資料庫中的路徑**，並逐筆確認新路徑存在、服務帳號
可以讀取。不要只移動 HTML 後就啟動服務：後台封存頁會直接開啟
`raw_html_path`，檔案不在原位置就無法檢視。

```bash
cd /opt/coolpc-price-history
sudo -u coolpc sqlite3 data/coolpc.db \
  "SELECT CASE WHEN raw_html_path LIKE 'data/raw_html/%' THEN '預設相對路徑' ELSE '其他路徑' END, COUNT(*) FROM scrape_snapshots WHERE raw_html_path IS NOT NULL GROUP BY 1;"
sudo -u coolpc sqlite3 data/coolpc.db \
  "SELECT id, raw_html_path FROM scrape_snapshots WHERE raw_html_path IS NOT NULL AND raw_html_path NOT LIKE 'data/raw_html/%' ORDER BY id LIMIT 20;"
```

第二個查詢只列出前 20 筆供抽查；「其他路徑」若超過 20 筆，必須繼續
檢查剩餘資料，確認每一種來源路徑如何對應到新機器。

## 6. 手動啟動確認可以跑

正式掛 systemd 之前，先在前景各跑一次確認沒問題：

```bash
sudo -u coolpc .venv/bin/uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690
# 另開一個終端
sudo -u coolpc .venv/bin/uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691
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
sudo systemctl status coolpc-public.service coolpc-admin.service
sudo systemctl list-timers coolpc-scraper.timer
sudo journalctl -u coolpc-scraper.service -n 50
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
匯入。**下方批次流程只適用於空資料庫的首次匯入**；先讀排序、封存路徑與
停用排程注意事項，再依「建議的完整操作流程」執行。若資料庫已有快照，
請先讀下方「既有資料庫補匯舊檔案」。

先確認 `coolpc` 帳號對來源目錄及每個 HTML 都有讀取權限；若來源是
另一個帳號的私人目錄，先搬到 `data/raw_html/` 的最終位置並調整權限。

## 它實際會做什麼

- **遞迴**尋找該目錄底下所有 `*.html`（含子目錄），依**檔案路徑字母排序**後
  逐一處理
- 每份檔案的時間戳取自 **HTML 內容裡的估價時間**，不是檔名、也不是匯入當下
  的系統時間
- 每處理完一份就印一行結果：
  `[success] fetched_at=... total=... new=... delisted=... up=... down=...`
- 任何一份檔案是 `failed` 或 `partial`，最後的 exit code 會是非 0

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
空資料庫首次匯入若中途被打斷，可在確認檔案的處理順序後重跑同一個目錄；
這不表示既有資料庫補匯舊檔案後，重跑最新快照能修復目前狀態。

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
sudo systemctl stop coolpc-scraper.service
sudo systemctl stop coolpc-admin.service
sudo systemctl status coolpc-scraper.timer coolpc-scraper.service
```

`stop` timer 只阻止下次觸發，不會停止已在跑的 oneshot。確認沒有其他手動
抓取、匯入程序；暫停管理服務可防止有人從管理頁手動觸發抓取。若管理
服務原本就未啟動，匯入完成後不必為此啟動。
若在目前這台使用者層級部署，以上三行及下方流程的 `sudo systemctl`
都要改成 `systemctl --user`。

## 建議的完整操作流程（空資料庫首次匯入）

檔案數量多的時候（數百份以上）會跑很久，建議丟到背景並保留 log：

```bash
sudo systemctl stop coolpc-scraper.timer
sudo systemctl stop coolpc-scraper.service
sudo systemctl stop coolpc-admin.service
sudo systemctl status coolpc-scraper.timer coolpc-scraper.service

cd /opt/coolpc-price-history
sudo -v
nohup sudo -n -u coolpc .venv/bin/coolpc-scraper import-dir /opt/coolpc-price-history/data/raw_html \
  > /tmp/import.log 2>&1 &
```

目前這台使用者層級部署則以 `systemctl --user` 停止 timer、管理服務與
正在執行的 scraper，從專案根目錄直接執行 `.venv/bin/coolpc-scraper`；
匯入結束並核對結果後，只恢復原本有啟動的服務。

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
sudo -u coolpc sqlite3 data/coolpc.db "
SELECT status, COUNT(*) FROM scrape_snapshots WHERE scrape_type='import' GROUP BY status;
SELECT COUNT(*) AS products FROM products;
SELECT COUNT(*) AS price_rows FROM price_history;
SELECT MIN(fetched_at), MAX(fetched_at) FROM scrape_snapshots;"
```

確認無誤後把排程開回來：

```bash
sudo systemctl start coolpc-admin.service  # 僅在管理服務原本有啟動時執行
sudo systemctl start coolpc-scraper.timer
```

## 既有資料庫補匯舊檔案

**不要直接將較舊 HTML 匯入已有較新快照的資料庫。** 匯入會無條件覆寫商品的
目前價格、狀態、上下架與最後出現時間；下架比對也不檢查時序。即使最後
重新匯入最新的 HTML，相同 `fetched_at` 的 `success`／`partial` 快照會被
直接略過，目前狀態仍可能停在舊快照。

請先依 [`AGENTS.md` 地雷 5](../AGENTS.md#hazard-5)
的復原程序操作：以 `VACUUM INTO` 備份，確認最新快照的 ID 及其已封存的
原始 HTML 確實可讀，才移除**該筆**快照及其 `price_history` 紀錄；接著依
HTML 內嵌估價時間由舊到新匯入歷史檔案，最後重匯剛才確認的最新 HTML。
執行前也要依上節停止排程、執行中的抓取及管理服務，確認沒有其他匯入程序。
完成後核對最新快照是否重新處理，並抽查商品的 `current_price`、
`current_status`、`is_active`、`last_seen_at` 與最新 HTML 是否一致；尤其檢查
只在最新快照出現的商品仍為上架。核對無誤後才恢復原本啟動的服務。

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

若當時排程與管理服務正在運作，同樣先依上文停止 timer、執行中的 scraper
與管理服務，確認無其他匯入程序，匯入並核對結果後再恢復原先的服務狀態。

```bash
sudo -u coolpc .venv/bin/coolpc-scraper import-html /path/to/2026-02-01-21-40.html
```
