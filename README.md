# 原價屋歷史價格查詢系統 (coolpc-price-history)

從原價屋官方估價網頁定期抓取商品價格，永久保存原始 HTML，解析出結構化商品
與價格資料，提供歷史價格查詢、走勢圖、多商品比較、公開查詢 API 與管理介面。

系統執行期間不使用 AI / LLM / Agent 進行任何商品判斷；分類、比對、合併皆為
確定性程式規則。

系統設計文件：[`docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md`](docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md)
實作計畫：[`docs/superpowers/plans/2026-09-02-coolpc-price-history-implementation.md`](docs/superpowers/plans/2026-09-02-coolpc-price-history-implementation.md)

## 系統需求

- Ubuntu Server 22.04 以上（其他有 systemd 的 Linux 發行版亦可）
- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)

## 1. 安裝

```bash
git clone <此專案的 git remote URL> /opt/coolpc-price-history
cd /opt/coolpc-price-history
```

建議建立一個專用系統帳號執行本服務（非必要，但符合最小權限原則）：

```bash
sudo useradd -r -s /usr/sbin/nologin coolpc
sudo chown -R coolpc:coolpc /opt/coolpc-price-history
```

## 2. 安裝 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

## 3. 建立 venv 與安裝 dependencies

```bash
cd /opt/coolpc-price-history
uv venv
uv sync
```

## 4. 初始化資料庫

```bash
uv run alembic upgrade head
```

會在 `data/coolpc.db` 建立所有資料表。`data/raw_html/` 目錄
用於永久保存每次抓取的原始 HTML，請確保有足夠的磁碟空間並定期備份 `data/`
整個目錄（資料庫 + 原始 HTML）。

## 5. 啟動公開查詢服務（0.0.0.0:33690）

```bash
uv run uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690
```

## 6. 啟動管理介面（0.0.0.0:33691）

```bash
uv run uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691
```

兩個服務皆不需要登入。本系統不實作 nginx；若要限制管理介面的存取來源，請
自行在 nginx（或其他反向代理）設定存取限制，並將對外流量導向
`127.0.0.1:33690`（公開）與 `127.0.0.1:33691`（管理）。

## 7. 啟用每 6 小時自動抓取（systemd）

```bash
sudo cp deploy/coolpc-scraper.service deploy/coolpc-scraper.timer \
        deploy/coolpc-public.service deploy/coolpc-admin.service \
        /etc/systemd/system/
sudo systemctl daemon-reload

# 排程抓取（每 6 小時一次，重開機後仍會依 Persistent=true 補跑）
sudo systemctl enable --now coolpc-scraper.timer

# 公開查詢與管理介面常駐服務
sudo systemctl enable --now coolpc-public.service
sudo systemctl enable --now coolpc-admin.service
```

`deploy/*.service` 內預設路徑為 `/opt/coolpc-price-history`、執行使用者為
`coolpc`；若安裝路徑或執行使用者不同，請先修改這些檔案內的
`WorkingDirectory`、`ExecStart`、`User`、`Group` 再複製到
`/etc/systemd/system/`。

檢查排程與服務狀態：

```bash
systemctl list-timers coolpc-scraper.timer
systemctl status coolpc-scraper.service
systemctl status coolpc-public.service
systemctl status coolpc-admin.service
journalctl -u coolpc-scraper.service -n 50
```

## 8. 手動抓取

透過 CLI：

```bash
uv run coolpc-scraper scrape --manual
```

或透過管理介面首頁（`http://<主機>:33691/`）點擊「手動執行抓取」按鈕。
兩者共用同一組併發鎖，不會與排程抓取同時執行。

## 9. 匯入舊 HTML

匯入單一檔案（會使用 HTML 內嵌的估價時間，而非匯入當下時間）：

```bash
uv run coolpc-scraper import-html /path/to/2026-02-01-21-40.html
```

匯入整個目錄（遞迴尋找所有 `*.html`，依檔名時間排序後依序處理）：

```bash
uv run coolpc-scraper import-dir /path/to/html/dir
```

## 10. 執行測試

```bash
uv run pytest
```

測試使用 `/home/xthybot/coolpc/download` 下的真實原價屋 HTML 樣本，涵蓋解析、
中文編碼、分類、價格、改名、下架/重新上架、人工合併、Undo 合併、舊名稱搜尋、
商品比較等情境。

## 環境變數

| 變數 | 說明 | 預設值 |
|---|---|---|
| `COOLPC_DB_PATH` | SQLite 資料庫檔案路徑 | `data/coolpc.db` |
| `COOLPC_EVALUATE_URL` | 原價屋估價頁網址 | `https://coolpc.com.tw/evaluate.php` |

## API

公開服務（`0.0.0.0:33690`）提供以下 JSON API，無需登入或 API Key：

```
GET /api/products
GET /api/products/{id}
GET /api/products/{id}/prices
GET /api/products/{id}/stats
GET /api/categories
GET /api/compare?ids=1,2,3
```

## 目錄結構

```
src/coolpc/          原始碼（db / parser / ingest / matching / scraper /
                      merging / stats / search / public_api / admin_api）
deploy/               systemd unit 檔案
data/                 SQLite 資料庫與永久保存的原始 HTML（不納入版控）
migrations/            Alembic migration
tests/                  測試（含真實 HTML 樣本回歸測試）
docs/superpowers/       設計文件與實作計畫
```
