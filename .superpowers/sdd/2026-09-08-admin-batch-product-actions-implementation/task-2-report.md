# Task 2 報告：合併路由與預填多商品選取器

## 結果

管理端現在支援 `GET /merge?ids=...` 預填 2 至 5 個商品，第一個預填商品預設為保留目標；`POST /merge` 支援一個目標與 1 至 4 個來源（合計 2 至 5 個）的一次性合併。

## RED / GREEN 證據

1. 先新增 GET 預填與錯誤處理測試，執行：

   ```text
   uv run pytest tests/admin_api/test_merge_page.py -q -k 'prefill or batch'
   ```

   RED：`test_merge_form_prefills_requested_products_and_marks_first_as_target` 與 `test_merge_form_rejects_invalid_prefill_ids` 失敗，因舊版 `/merge` 未讀取 `ids`。

2. 實作 query 解析、資料庫驗證與預填 chip 後，同一組 GET 測試 GREEN：2 passed。

3. 先新增多來源 POST 測試，舊單筆路由 RED：成功訊息是 `合併成功`，不是 `已合併 2 個來源商品`，證明舊路由未提供批次契約。

4. 實作多值表單解析、`merge_products_batch()` 呼叫與單一 transaction 後，GET／POST／rollback 測試 GREEN：4 passed。

5. 受影響測試：

   ```text
   uv run pytest tests/admin_api/test_merge_page.py tests/merging/test_merge.py -q
   ```

   結果：27 passed。

6. 完整套件：

   ```text
   uv run pytest -q --junitxml=/tmp/coolpc-task2-pytest.xml
   ```

   JUnit 結果：232 tests、0 failures、0 errors，338.974 秒。

## 修改檔案

- `src/coolpc/admin_api/routers/products.py`
  - 新增安全的合併 ID 解析與商品狀態驗證。
  - `GET /merge` 接受 comma-separated `ids`、預填未被合併的商品，並以既有 notice 顯示錯誤。
  - `POST /merge` 改讀取重複 `source_id` 欄位，僅在 `merge_products_batch()` 全部成功後 commit。
- `src/coolpc/admin_api/templates/merge.html`
  - chip 上限由 2 提高為 5，支援伺服端預填與 radio target。
  - 同步時為每個非 target chip 動態建立同名 `source_id` hidden input。
- `tests/admin_api/test_merge_page.py`
  - 覆蓋預填、query 錯誤、多來源合併、全回滾與既有特殊字元 redirect 測試的批次介面。

## POST form contract

```text
source_id=<來源商品 ID>&source_id=<來源商品 ID>&target_id=<保留商品 ID>
```

- `target_id` 必須剛好一個。
- 合計商品數必須為 2 至 5；商品 ID 必須是整數、不可重複、必須存在且未被合併。
- 成功時 redirect 至 `/merge?message=已合併+N+個來源商品`。
- 驗證或合併失敗時 rollback，redirect 至 `/merge?error=...`。

## 自我審查

- 多來源資料庫狀態與 `MergeLog` 以真實 HTTP/SQLAlchemy 測試驗證。
- service 及 router 都預先驗證，確保無部分合併；router 僅在完整成功後 commit。
- 原有兩商品表單提交仍使用相同 `source_id`／`target_id` 合約，Undo 測試通過。
- 未修改 schema、systemd、公開 API 或其他 UI；未納入既有未追蹤 implementation plan。

## 疑慮

- 僅有既存 `datetime.utcnow()` 與 TestClient deprecation warnings；不屬本次範圍，未修改。
- 完整測試需以背景程序執行，因本環境約 31 秒會中斷前景工具回傳；JUnit 檔確認完整套件已完成。
