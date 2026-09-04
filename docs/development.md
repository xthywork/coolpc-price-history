# 開發指南

## 專案慣例

- **後端邏輯一律是確定性程式規則，不使用 AI/LLM/Agent 做任何商品判斷**
  （分類歸屬、新舊商品比對、合併方向決策皆然）。新增功能時若涉及「猜測」
  性質的判斷（例如从名稱猜品牌/型號，見 `ingest/service.py` 的
  `guess_brand`/`guess_model`），一律用可測試、可重現的規則式邏輯實作，
  不引入模型推論。
- **前端不使用任何框架**，一律 Jinja2 伺服端渲染 + 原生 JavaScript
  （`<script>` 直接內嵌在模板裡，用 `fetch()` 呼叫既有 JSON 端點局部更新
  DOM）。新頁面請延續這個模式，不要引入 React/Vue/建置工具鏈。
- **畫面文案一律使用繁體中文**。
- **Schema 演進只透過 Alembic migration**，不依賴 `Base.metadata.
  create_all()` 讓正式環境自動長出新欄位/新表（測試套件例外，見下方）。
- `SearchFilters`/搜尋邏輯集中在 `src/coolpc/search/service.py` 單一位置，
  `public_api` 與 `admin_api` 都直接呼叫這裡，不要在兩邊各自複製一份比對
  邏輯（分頁工具函式同理，`admin_api` 直接 import `public_api.routers.
  pages` 的 `PAGE_SIZE_OPTIONS`/`_resolve_page_size`/`_build_page_list`）。

## 專案結構速查

見 [README.md](../README.md#目錄結構) 的目錄結構段落；模組職責細節見
[`docs/architecture.md`](architecture.md)。

## 開發流程：TDD

專案採 TDD 開發，新功能/修 bug 的標準流程：

1. 先寫一個會失敗的測試，描述期望行為。
2. 執行該測試，確認確實是因為功能未實作而失敗（不是測試本身寫錯）。
3. 寫最小可行的實作讓測試通過。
4. 執行受影響的測試檔案，再執行完整測試套件，確認沒有連帶破壞其他行為。
5. Commit。

## 執行測試

```bash
uv run pytest                          # 全部測試
uv run pytest tests/search/            # 單一目錄
uv run pytest tests/search/test_search.py -v   # 單一檔案，詳細輸出
uv run pytest -k "merge"               # 依名稱關鍵字篩選
```

`pyproject.toml` 設定 `testpaths = ["tests"]`、`pythonpath = ["src"]`，
所以 `uv run pytest` 不需要額外參數就能找到 `coolpc` package。

### 測試目錄對應

| 目錄 | 涵蓋範圍 |
|---|---|
| `tests/parser/` | HTML 解析（編碼、名稱/價格/狀態切分、促銷尾綴清理） |
| `tests/ingest/` | 商品比對、新增/更新、I6 partial 保護 |
| `tests/scraper/` | 抓取、鎖、失敗處理 |
| `tests/matching/` | 名稱正規化、相似度計算 |
| `tests/merging/` | 合併方向決策、合併/Undo |
| `tests/stats/` | 價格統計、合併鏈追蹤 |
| `tests/search/` | AND/OR 搜尋語意 |
| `tests/db/` | Model/schema 層基本檢查 |
| `tests/public_api/` | 公開頁面與 JSON API |
| `tests/admin_api/` | 管理介面頁面與表單流程 |
| `tests/test_regression_real_html.py` | 端對端回歸測試，見下方 |
| `tests/test_integration_merge_journey.py` | 跨模組整合情境（例如完整合併→Undo 流程） |

多數測試用記憶體 SQLite（`create_engine("sqlite:///:memory:")` +
`Base.metadata.create_all(engine)`）建立乾淨資料庫，不需要真實資料或外部
服務。`public_api`/`admin_api` 的頁面測試普遍用
`app.dependency_overrides[get_session] = ...` 換掉正式的 `get_session`
依賴，指向這個記憶體資料庫。

### 端對端回歸測試（真實 HTML 樣本）

`tests/test_regression_real_html.py` 用一份不納入版控的真實原價屋 HTML
語料庫做端對端驗證（完整跑一次 `parse_html` → `ingest_snapshot`，確認長
時間序列的抓取不會拋例外、不會遺失資料）。語料庫預設路徑
`/home/xthybot/coolpc/download`，可用 `COOLPC_SAMPLE_DIR` 環境變數指向
其他位置；**該路徑不存在時這個測試檔會自動 skip**，不會讓 CI 或其他機器
上的測試套件失敗。

## 新增一個 Alembic Migration

1. 修改 `src/coolpc/db/models.py`（新增/修改欄位或表）。
2. 手寫 migration 檔案到 `migrations/versions/`（初版 schema
   `53b4bb1e5ed2_initial_schema.py` 是當初用 `alembic revision
   --autogenerate` 產生的一次性 bootstrap，但從 `0002_fts5` 開始，之後
   每一份 migration 都是手寫，不再依賴 autogenerate——原因是
   `Category`/`Subcategory` 的 `label` 之類的 Python property 不對應實際
   欄位，autogenerate 容易誤判；手寫也讓每個 migration 可以附上清楚的
   「為什麼」註解）。檔名慣例：`NNNN_簡短描述.py`（四位數流水號，接續現有
   最大號碼），內容包含 `revision`/`down_revision`（接續現有最新 head）、
   `upgrade()`、`downgrade()`。
3. SQLite 對 `ALTER TABLE` 的支援有限（尤其是 `DROP COLUMN`、修改欄位型別/
   約束），一律用 `op.batch_alter_table("表名") as batch_op:` 包住欄位變更
   操作（Alembic 會自動用「建新表→搬資料→替換」的方式達成，不依賴特定
   SQLite 版本的原生語法）。可參考
   `migrations/versions/0006_drop_last_change_columns.py`、
   `migrations/versions/0007_drop_product_first_seen_at.py`。
4. 若是移除欄位，記得同步檢查並更新所有使用到該欄位的地方：
   `src/coolpc/**/*.py`、`src/coolpc/**/templates/*.html`、以及**所有**
   測試檔案裡建立該 model 的 fixture（欄位移除後，測試裡任何還在傳入該
   關鍵字參數的 `Product(...)`/`Category(...)` 呼叫都會直接因為
   `TypeError: unexpected keyword argument` 失敗，需要逐一找出並移除）。
5. 在本機執行 `uv run alembic upgrade head` 套用到本機資料庫，執行
   `uv run pytest` 確認測試套件全綠。
6. 部署到正式環境時的操作程序（先停服務、快照演練、再對正式資料庫執行）見
   [`docs/deployment.md`](deployment.md#schema-變更新增-alembic-migration的正式環境操作程序)，
   **不要**在有正式流量的服務仍在執行時直接對正式資料庫跑
   `alembic upgrade head`。

## Commit 慣例

- 一個 commit 對應一個邏輯完整的變動（一個功能、一個修正），訊息說明「為
  什麼」而不只是「改了什麼」（程式碼本身已經說明改了什麼）。
- 涉及資料庫欄位增刪的 commit，訊息應同時涵蓋 model 變更、migration、以及
  所有受影響呼叫端的調整，讓單一 commit 可以完整回溯一次 schema 變更的
  全貌。
