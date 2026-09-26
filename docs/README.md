# 文件索引

請先看 [專案概觀](../README.md)；接手修改程式或操作本機服務前，先讀
[AGENTS.md](../AGENTS.md) 的慣例與地雷。本頁將現行文件與歷史規劃紀錄分開。
**現行行為以原始碼與下列現行文件為準；歷史 spec／plan 只記錄當時的規劃，
不代表目前的實作狀態或待辦。**

## 現行文件：按任務查找

| 要做的事 | 先讀 |
|---|---|
| 理解服務拓樸、抓取與匯入資料流 | [系統架構](architecture.md) |
| 查資料表、欄位、時間戳與已移除欄位 | [資料庫結構](database-schema.md) |
| 理解搜尋條件、AND／OR 語意及廣告過濾 | [搜尋語意](search-semantics.md) |
| 串接或查詢公開 JSON API | [API 參考](api-reference.md) |
| 使用管理介面編輯商品、處理合併 | [管理介面指南](admin-guide.md) |
| 備份、部署、執行 schema migration | [部署指南](deployment.md) |
| 新機器安裝、批次匯入既有 HTML | [新機器設定](new-machine-setup.md) |
| 開發、執行測試、撰寫 migration | [開發指南](development.md) 與 [AGENTS.md](../AGENTS.md) |

## 歷史規劃紀錄

以下文件保留當時的設計、決策及工作清單供追溯。其狀態文字、核取清單和
實作描述都屬於歷史紀錄；查現況請回到上方現行文件及原始碼。

### 設計規格（specs）

- [docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md](superpowers/specs/2026-09-02-coolpc-price-history-design.md)
- [docs/superpowers/specs/2026-09-05-ui-redesign-design.md](superpowers/specs/2026-09-05-ui-redesign-design.md)

### 實作計畫（plans）

- [docs/superpowers/plans/2026-09-02-coolpc-price-history-implementation.md](superpowers/plans/2026-09-02-coolpc-price-history-implementation.md)
- [docs/superpowers/plans/2026-09-03-ui-admin-refinements-implementation.md](superpowers/plans/2026-09-03-ui-admin-refinements-implementation.md)
- [docs/superpowers/plans/2026-09-04-compare-search-page-refinements-implementation.md](superpowers/plans/2026-09-04-compare-search-page-refinements-implementation.md)
