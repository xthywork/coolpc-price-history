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

`deploy/` 的四份 unit 是**系統層級部署範本**，假設安裝在
`/opt/coolpc-price-history`、執行帳號為 `coolpc`；不同環境請先修改再複製到
`/etc/systemd/system/`。以下未加 `--user` 的操作指令只適用於這種部署。
**本專案目前這台機器使用的是使用者層級 unit**（位於
`~/.config/systemd/user/`），不是 `deploy/` 內的範本；在這台機器上請把
`sudo systemctl ...` 改為 `systemctl --user ...`，`journalctl ...` 改為
`journalctl --user ...`，且不要操作 `/etc/systemd/system/`。兩種方式的設定
與指令不可混用，詳見 [README 的 systemd 部署段落](../README.md#systemd-部署)。

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
   `VACUUM INTO`（會讀取包含 WAL 中已提交交易的一致資料，產生一份體積較精簡的
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

以下命令以 `/opt/coolpc-price-history` 的**系統層級部署**為例；先
`cd /opt/coolpc-price-history`，由可使用 `sudo` 的維運帳號執行。這台機器
的使用者層級部署須依上節改用 `systemctl --user`，並以實際資料庫路徑及
擁有該專案的使用者執行 `sqlite3`、Alembic。

1. **停止 timer、正在執行的 scraper service 與兩個常駐服務**。只停止
   timer 不會中斷已啟動的 oneshot；管理頁也能手動觸發抓取，因此兩個網站
   服務同樣要停。確認沒有其他手動抓取或匯入程序繼續寫入資料庫：

   ```bash
   sudo systemctl stop coolpc-scraper.timer coolpc-public.service coolpc-admin.service
   sudo systemctl stop coolpc-scraper.service
   sudo systemctl status coolpc-scraper.timer coolpc-scraper.service
   ```

2. **取一份一致備份，複製一份作演練**（見上方「WAL 模式下的檔案系統層
   備份」）。備份檔保留不動；目標檔案都必須尚未存在，並要留足備份、
   演練及 migration 的磁碟空間。以下命令須在同一個 shell 依序執行；
   任一目標已存在（含懸空符號連結）或備份失敗時即停止：

   ```bash
   set -e
   for target in data/coolpc-before-migration.db data/coolpc-migration-test.db; do
     if [ -e "$target" ] || [ -L "$target" ]; then
       printf '目標已存在，停止操作：%s\n' "$target" >&2
       exit 1
     fi
   done
   sudo -u coolpc sqlite3 data/coolpc.db "VACUUM INTO 'data/coolpc-before-migration.db'"
   sudo -u coolpc cp data/coolpc-before-migration.db data/coolpc-migration-test.db
   ```

3. **先記下快照的資料列數，再在快照上演練 migration**。執行前先檢視本次
   migration，列出**每一張受影響的表**（包括會重建的表）；以下三張表只是
   範例，**不是完整檢查清單**。把每張前後都存在的受影響表加入
   `counts_sql` 的 migration 前／後列數查詢，並把同一批表加入下方的
   `PRAGMA table_info` 迴圈，逐一核對 migration 前後的欄位與預期結構。
   若有意增刪資料列，須先為各表
   訂出預期列數變化，將範例中的相等檢查改為逐表驗證預期值；新增或刪除
   整張表時，另行核對該表在 migration 前後的存在狀態、欄位及可查的
   資料列數。尤其是會重建表的 schema 變更，更要確認資料沒有遺漏。
   以下兩段在同一個專用 shell 依序執行；`set -e` 讓任一步失敗時停止
   後續命令：

   ```bash
   set -e
   counts_sql="SELECT 'products', COUNT(*) FROM products UNION ALL SELECT 'price_history', COUNT(*) FROM price_history UNION ALL SELECT 'scrape_snapshots', COUNT(*) FROM scrape_snapshots ORDER BY 1;"
   before_counts=$(sudo -u coolpc sqlite3 data/coolpc-migration-test.db "$counts_sql")
   for table in products price_history scrape_snapshots; do
     printf 'migration 前：%s\n' "$table"
     sudo -u coolpc sqlite3 data/coolpc-migration-test.db "PRAGMA table_info($table);"
   done
   sudo -u coolpc env COOLPC_DB_PATH=data/coolpc-migration-test.db \
     /opt/coolpc-price-history/.venv/bin/alembic upgrade head
   after_counts=$(sudo -u coolpc sqlite3 data/coolpc-migration-test.db "$counts_sql")
   printf 'migration 前：\n%s\nmigration 後：\n%s\n' "$before_counts" "$after_counts"
   test "$before_counts" = "$after_counts"  # 不相同就停止操作並調查
   for table in products price_history scrape_snapshots; do
     printf 'migration 後：%s\n' "$table"
     sudo -u coolpc sqlite3 data/coolpc-migration-test.db "PRAGMA table_info($table);"
   done
   ```

4. **快照驗證通過後，才對正式資料庫執行**。先確認資料庫仍沒有其他寫入者，
   再核對正式庫的資料列數與備份基準相同，執行 migration 後再比一次：

   ```bash
   live_before=$(sudo -u coolpc sqlite3 data/coolpc.db "$counts_sql")
   test "$before_counts" = "$live_before"  # 不相同就停止操作並調查
   sudo -u coolpc /opt/coolpc-price-history/.venv/bin/alembic upgrade head
   live_after=$(sudo -u coolpc sqlite3 data/coolpc.db "$counts_sql")
   printf '正式庫 migration 前：\n%s\n正式庫 migration 後：\n%s\n' "$live_before" "$live_after"
   test "$live_before" = "$live_after"  # 不相同就不要啟動服務，先調查
   for table in products price_history scrape_snapshots; do
     printf '正式庫 migration 後：%s\n' "$table"
     sudo -u coolpc sqlite3 data/coolpc.db "PRAGMA table_info($table);"
   done
   ```

5. **資料列數及 schema 均確認後，重啟兩個常駐服務和 timer**：

   ```bash
   sudo systemctl start coolpc-public.service coolpc-admin.service
   sudo systemctl start coolpc-scraper.timer
   sudo systemctl status coolpc-public.service coolpc-admin.service coolpc-scraper.timer
   ```

6. 用實際頁面/API 快速抽查（例如商品列表頁、單一商品詳細頁、剛異動 schema
   涉及到的欄位）確認服務行為正常，而不是只看 HTTP 狀態碼 200 就視為完成——
   純 HTTP 層檢查無法發現版面 CSS 衝突之類的問題，只能發現後端邏輯層級的
   錯誤，需要的話仍應實際在瀏覽器操作一次功能路徑。

SQLite 對部分 `ALTER TABLE` 操作有限制。**需要 SQLite 無法直接完成的
表結構變更**（例如本專案 `0006`、`0007` 的刪欄位操作）可用
`op.batch_alter_table(...)`；Alembic 在必要時會以建立新表、複製資料、
替換舊表的方式處理。並非所有 migration 都要用 batch：`0004`、`0005`
新增欄位時直接使用 `op.add_column(...)`。請依實際操作與 SQLite 支援程度
選擇，並在快照演練時核對資料列數與欄位。

## 反向代理與存取限制

本系統不實作任何登入/驗證機制，兩個服務預設都監聽 `0.0.0.0`。正式環境務必
自行決定存取策略，常見做法：

- 只把 `33690`（公開查詢）對外開放，`33691`（管理介面）只留在內網或透過
  VPN/SSH tunnel 存取；
- 或在 nginx（等反向代理）設定 IP allowlist、Basic Auth 等機制保護
  `33691`，並將實際對外流量導向 `127.0.0.1:33690`。

本專案本身不包含任何 nginx 設定檔，需自行準備。
