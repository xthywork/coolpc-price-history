# 部署與維運

基本安裝/啟動步驟見 [README.md](../README.md)。本文件涵蓋正式環境運作
之後需要的維運操作：備份、日誌檢查、以及**日後每次 schema 變更**都應遵循
的安全操作程序。

## 服務組成

| systemd unit | 類型 | 說明 |
|---|---|---|
| `coolpc-scraper.timer` | timer | 每 6 小時觸發一次（`OnCalendar=*-*-* 0/6:00:00`），`Persistent=true` 代表關機期間錯過的排程會在下次開機後補跑一次，`RandomizedDelaySec=60` 避免多台機器同時對原站送出請求 |
| `coolpc-scraper.service` | oneshot | 實際執行 `coolpc-scraper scrape` 一次後結束，由 timer 觸發，不常駐 |
| `coolpc-public.service` | simple，常駐 | `uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690`，`Restart=on-failure` |
| `coolpc-admin.service` | simple，常駐 | `uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691`，`Restart=on-failure` |

四份 unit 檔案都在 `deploy/`，內建路徑假設安裝在 `/opt/coolpc-price-history`、
執行帳號為 `coolpc`；不同環境請先修改再複製到 `/etc/systemd/system/`。

## 日誌檢查

```bash
journalctl -u coolpc-scraper.service -n 50      # 最近一次抓取執行結果
journalctl -u coolpc-public.service -f          # 即時追蹤公開服務日誌
journalctl -u coolpc-admin.service -f
systemctl list-timers coolpc-scraper.timer      # 確認下次排程時間、上次執行結果
```

抓取本身的成功/失敗/partial 狀態與統計數字，更完整地記錄在資料庫的
`scrape_snapshots` 表，管理介面「抓取狀態」首頁會顯示最近 20 筆——比對
`journalctl` 訊息時建議兩邊一起看。

## 備份

需要備份的是整個 `data/` 目錄：

- `data/coolpc.db`（+ SQLite WAL 模式下可能同時存在的 `data/coolpc.db-wal`、
  `data/coolpc.db-shm`，見下方「WAL 模式下的檔案系統層備份」）
- `data/raw_html/`：每次抓取永久保存的原始 HTML，是所有解析結果的原始
  真相來源（source of truth），解析規則之後若需要回頭驗證或修正，都要靠
  這份語料庫。

### WAL 模式下的檔案系統層備份

本系統的 SQLite 連線一律開啟 WAL 模式（見
[`docs/database-schema.md`](database-schema.md) 開頭的 pragma 說明）。
WAL 模式下，最近的寫入可能還停留在 `coolpc.db-wal` 檔案裡、尚未
checkpoint 回主檔案 `coolpc.db`。**如果直接用 `cp`/`rsync` 只複製
`coolpc.db` 本體，可能會漏掉還沒 checkpoint 的資料，複製到一份不一致的
快照**（本專案在導入 migration `0006`/`0007` 時，第一次用 `cp` 對正在
服務中的資料庫取快照做 migration 演練，就實際遇到這個問題：快照裡的
`alembic_version` 落後於資料庫實際的 schema 版本）。

正確做法有兩種：

1. **服務全部停機時**直接複製整個 `data/` 目錄（`coolpc.db`、
   `coolpc.db-wal`、`coolpc.db-shm` 一起複製）——這是最單純可靠的方式，
   適合排定的維護窗口。
2. **服務仍在運作、需要線上取得一致快照時**，用 SQLite 自己的
   `VACUUM INTO`（會自動處理 WAL 合併，產生一份內容一致、且體積較精簡的
   單一檔案快照）：

   ```bash
   sqlite3 data/coolpc.db "VACUUM INTO '/path/to/backup/coolpc-$(date +%Y%m%d-%H%M%S).db'"
   ```

   不要用 `cp`/`rsync` 對一個仍在被寫入的 WAL 模式資料庫做檔案層級複製。

建議搭配 cron 或另一個 systemd timer 定期執行 `VACUUM INTO` 備份到異地
儲存空間，並定期抽測還原（`alembic current` 確認版本、抽查幾筆資料）。

## Schema 變更（新增 Alembic migration）的正式環境操作程序

**這是本專案實際採用、且已驗證過的安全流程**，每次要對正式環境套用新的
schema migration 時應該照著做，而不是直接在正式資料庫上 `alembic upgrade
head`：

1. **先停止兩個常駐服務**（避免 migration 執行期間有寫入交易進行中，
   也避免 uvicorn worker 手上還拿著舊 schema 的 SQLAlchemy 連線繼續跑）：

   ```bash
   sudo systemctl stop coolpc-public.service coolpc-admin.service
   ```

2. **取一份一致快照**做演練（見上方「WAL 模式下的檔案系統層備份」，服務
   已停止的話用 `cp` 也可以，習慣用 `VACUUM INTO` 更保險）：

   ```bash
   sqlite3 data/coolpc.db "VACUUM INTO '/tmp/coolpc-migration-test.db'"
   ```

3. **先在快照上跑一次 migration**，確認語法/邏輯正確、不會出錯，並確認
   資料列數在 migration 前後一致（尤其是 `DROP COLUMN` 這種在 SQLite 上
   靠 `batch_alter_table` 重建整張表完成的操作，值得多一層確認）：

   ```bash
   COOLPC_DB_PATH=/tmp/coolpc-migration-test.db uv run alembic upgrade head
   sqlite3 /tmp/coolpc-migration-test.db "SELECT COUNT(*) FROM products;"
   sqlite3 /tmp/coolpc-migration-test.db "PRAGMA table_info(products);"
   ```

4. **快照驗證通過後，才對正式資料庫執行**：

   ```bash
   uv run alembic upgrade head
   sqlite3 data/coolpc.db "SELECT COUNT(*) FROM products;"   # 再次確認列數
   ```

5. **重啟兩個常駐服務**：

   ```bash
   sudo systemctl start coolpc-public.service coolpc-admin.service
   systemctl status coolpc-public.service coolpc-admin.service
   ```

6. 用實際頁面/API 快速抽查（例如商品列表頁、單一商品詳細頁、剛異動 schema
   涉及到的欄位）確認服務行為正常，而不是只看 HTTP 狀態碼 200 就視為完成——
   純 HTTP 層檢查無法發現版面 CSS 衝突之類的問題，只能發現後端邏輯層級的
   錯誤，需要的話仍應實際在瀏覽器操作一次功能路徑。

SQLite 對 `ALTER TABLE ... DROP COLUMN` 的支援因版本而異，本專案的
migration 一律用 `op.batch_alter_table(...)`（Alembic 的可攜寫法，會建立
新表、搬移資料、再替換舊表），避免依賴特定 SQLite 版本的原生語法，見
`migrations/versions/0006_drop_last_change_columns.py`、
`migrations/versions/0007_drop_product_first_seen_at.py` 兩個實例。

## 反向代理與存取限制

本系統不實作任何登入/驗證機制，兩個服務預設都監聽 `0.0.0.0`。正式環境務必
自行決定存取策略，常見做法：

- 只把 `33690`（公開查詢）對外開放，`33691`（管理介面）只留在內網或透過
  VPN/SSH tunnel 存取；
- 或在 nginx（等反向代理）設定 IP allowlist、Basic Auth 等機制保護
  `33691`，並將實際對外流量導向 `127.0.0.1:33690`。

本專案本身不包含任何 nginx 設定檔，需自行準備。
