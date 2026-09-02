# 原價屋歷史價格查詢系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可執行的原價屋歷史價格查詢系統：定期抓取原價屋估價頁 HTML、
解析商品與價格、累積歷史、提供公開查詢/比較/圖表與管理介面。

**Architecture:** 單一 uv 專案，分層模組：`db`（SQLAlchemy models）→
`parser`（HTML→結構化資料）→`ingest`（結構化資料→DB，含比對/下架邏輯）→
`matching`（相似度候選）／`scraper`（下載+併發鎖）／`merging`（合併/undo）／
`stats`（價格統計計算，供 API 共用）→`public_api`／`admin_api`（FastAPI +
Jinja2）。CLI 為抓取/匯入的統一入口，供排程與人工操作共用。

**Tech Stack:** Python 3.12、uv、SQLAlchemy 2.0 + Alembic、SQLite (含 FTS5)、
BeautifulSoup4 + lxml、httpx、FastAPI + Jinja2 + Chart.js（CDN）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-02-coolpc-price-history-design.md`

## Global Constraints

- 系統執行期間不得使用 AI/LLM/Agent 做任何商品判斷；所有分類/比對/合併皆為確定性程式規則。
- HTML 一律用 `cp950` codec 解碼（Big5 的 Windows/廠商擴充變體，即一般俗稱的「Big5」；**不可用 Python 內建的 `big5` codec**——經 Task 5 審查實測驗證，`big5` 會把 ETen 廠商擴充字元解成亂碼，例如常見品牌「宏碁」會變成「宏??」，因為「碁」字落在 `big5` codec 未涵蓋的擴充區）。BeautifulSoup 必須使用 `lxml` parser（`html.parser` 對此站台的未閉合標籤會解析失敗）。
- 商品比對規則：名稱字串完全一致（在未被合併的 `product_names` 中）＝同一商品；任何差異＝新商品，僅寫入 `similarity_hints` 供人工參考，絕不自動合併。
- 抓取/匯入失敗不得破壞既有資料：DB 寫入包在單一 transaction 內，失敗即 rollback；已下載的原始 HTML 仍永久保存。
- 兩次抓取不可同時執行（檔案鎖保護）。
- 公開服務預設監聽 `0.0.0.0:33690`；管理服務預設監聽 `0.0.0.0:33691`；皆不需要登入，本專案不實作 nginx。
- 原始 HTML 永久保存於 `data/raw_html/YYYY/MM/DD/*.html`，不得刪除或覆蓋。
- 原價屋估價頁 URL：`https://coolpc.com.tw/evaluate.php`（可用環境變數 `COOLPC_EVALUATE_URL` 覆蓋）。
- 測試一律使用 `/home/xthybot/coolpc/download` 下的真實 HTML 樣本，不得用假造資料。

---

## Task 1: 專案骨架與工具鏈

**Files:**
- Create: `pyproject.toml`
- Create: `src/coolpc/__init__.py`, `src/coolpc/db/__init__.py`, `src/coolpc/parser/__init__.py`, `src/coolpc/ingest/__init__.py`, `src/coolpc/matching/__init__.py`, `src/coolpc/scraper/__init__.py`, `src/coolpc/merging/__init__.py`, `src/coolpc/stats/__init__.py`, `src/coolpc/public_api/__init__.py`, `src/coolpc/admin_api/__init__.py`
- Create: `tests/__init__.py`, `tests/test_smoke.py`
- Create: `data/.gitkeep`, `data/raw_html/.gitkeep`

**Interfaces:**
- Produces: 可執行 `uv run pytest` 的專案骨架；後續所有模組都掛在 `src/coolpc/` 下。

- [ ] **Step 1: 寫 pyproject.toml**

```toml
[project]
name = "coolpc"
version = "0.1.0"
description = "原價屋歷史價格查詢系統"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "beautifulsoup4>=4.12",
    "lxml>=5.3",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
]

[project.scripts]
coolpc-scraper = "coolpc.cli:main"

[dependency-groups]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/coolpc"]
```

- [ ] **Step 2: 建立目錄與空 `__init__.py`**

```bash
mkdir -p src/coolpc/{db,parser,ingest,matching,scraper,merging,stats,public_api,admin_api}
mkdir -p tests data/raw_html
for d in "" db parser ingest matching scraper merging stats public_api admin_api; do
  touch "src/coolpc/${d:+$d/}__init__.py"
done
touch tests/__init__.py data/.gitkeep data/raw_html/.gitkeep
```

- [ ] **Step 3: 建立 venv 並安裝相依套件**

```bash
uv venv
uv sync
```

- [ ] **Step 4: 寫 smoke test**

```python
# tests/test_smoke.py
def test_smoke():
    import coolpc
    assert coolpc is not None
```

- [ ] **Step 5: 執行測試確認通過**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/ data/.gitkeep data/raw_html/.gitkeep uv.lock
git commit -m "chore: 建立專案骨架與工具鏈"
```

---

## Task 2: 資料庫 Models

**Files:**
- Create: `src/coolpc/db/models.py`
- Test: `tests/db/test_models.py`

**Interfaces:**
- Consumes: 無（純資料層）
- Produces: `Base`（DeclarativeBase）與 `Category`, `Subcategory`, `Product`, `ProductName`, `PriceHistory`, `ScrapeSnapshot`, `MergeLog`, `SimilarityHint` 類別，供 Task 3 起所有模組使用。欄位如 spec 第四節所定義。

- [ ] **Step 1: 寫失敗測試（建表並插入一筆完整資料鏈）**

```python
# tests/db/test_models.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import (
    Base, Category, Subcategory, Product, ProductName,
    PriceHistory, ScrapeSnapshot, MergeLog, SimilarityHint,
)

def test_create_full_chain():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.datetime(2026, 2, 1, 21, 40)
    with Session(engine) as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()

        snap = ScrapeSnapshot(
            fetched_at=now, scrape_type="manual", raw_html_path=None,
            status="success", total_products=1, new_products=1,
            delisted_products=0, price_up_count=0, price_down_count=0,
            created_at=now,
        )
        session.add(snap)
        session.flush()

        product = Product(
            category_id=cat.id, subcategory_id=sub.id,
            current_name="ASUS RTX 5070 PRIME 12G, $18990",
            brand="ASUS", model="RTX 5070 PRIME 12G",
            current_status=None, current_price=18990,
            is_active=True, first_seen_at=now, last_seen_at=now,
            created_at=now,
        )
        session.add(product)
        session.flush()

        session.add(ProductName(product_id=product.id, name=product.current_name,
                                 first_seen_at=now, last_seen_at=now))
        session.add(PriceHistory(product_id=product.id, price=18990, status=None,
                                  badges="◆ ★", scraped_at=now, snapshot_id=snap.id))
        session.commit()

        assert session.query(Product).count() == 1
        assert session.query(ProductName).count() == 1
        assert session.query(PriceHistory).count() == 1

def test_merge_log_and_similarity_hint_tables_exist():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.datetime(2026, 2, 1)
    with Session(engine) as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A",
                      current_price=100, is_active=True, first_seen_at=now,
                      last_seen_at=now, created_at=now)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B",
                      current_price=200, is_active=True, first_seen_at=now,
                      last_seen_at=now, created_at=now)
        session.add_all([p1, p2])
        session.flush()
        session.add(MergeLog(source_product_id=p1.id, target_product_id=p2.id, merged_at=now))
        session.add(SimilarityHint(product_a_id=p1.id, product_b_id=p2.id, score=0.9, computed_at=now))
        session.commit()
        assert session.query(MergeLog).count() == 1
        assert session.query(SimilarityHint).count() == 1
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'coolpc.db.models'`

- [ ] **Step 3: 實作 models.py**

```python
# src/coolpc/db/models.py
from __future__ import annotations
import datetime
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    subcategories: Mapped[list["Subcategory"]] = relationship(back_populates="category")


class Subcategory(Base):
    __tablename__ = "subcategories"
    __table_args__ = (UniqueConstraint("category_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str]
    category: Mapped["Category"] = relationship(back_populates="subcategories")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    subcategory_id: Mapped[int] = mapped_column(ForeignKey("subcategories.id"))
    current_name: Mapped[str] = mapped_column(index=True)
    brand: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    current_status: Mapped[str | None] = mapped_column(default=None)
    current_price: Mapped[int]
    # 上次價格異動幅度，於 Task 8 ingest_product 每次比對到既有商品時更新；
    # 新商品建立時為 None。用於 Task 17 搜尋條件「最近漲價/降價/漲跌幅」，
    # 避免每次搜尋都要對全表逐筆計算統計。
    last_change_amount: Mapped[int | None] = mapped_column(default=None)
    last_change_percent: Mapped[float | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    first_seen_at: Mapped[datetime.datetime]
    last_seen_at: Mapped[datetime.datetime]
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), default=None)
    created_at: Mapped[datetime.datetime]


class ProductName(Base):
    __tablename__ = "product_names"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(index=True, unique=True)
    first_seen_at: Mapped[datetime.datetime]
    last_seen_at: Mapped[datetime.datetime]


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[int]
    status: Mapped[str | None] = mapped_column(default=None)
    badges: Mapped[str | None] = mapped_column(default=None)
    scraped_at: Mapped[datetime.datetime] = mapped_column(index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("scrape_snapshots.id"))


class ScrapeSnapshot(Base):
    __tablename__ = "scrape_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime.datetime]
    scrape_type: Mapped[str]
    raw_html_path: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="success")
    error_message: Mapped[str | None] = mapped_column(default=None)
    total_products: Mapped[int] = mapped_column(default=0)
    new_products: Mapped[int] = mapped_column(default=0)
    delisted_products: Mapped[int] = mapped_column(default=0)
    price_up_count: Mapped[int] = mapped_column(default=0)
    price_down_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime]


class MergeLog(Base):
    __tablename__ = "merge_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    target_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    merged_at: Mapped[datetime.datetime]
    undone_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
    # JSON 陣列，記錄本次合併時被改掛到 target 的 ProductName.id 清單，
    # 供 Task 15 的 undo_merge 精確還原（不能只靠時間或名稱反推）。
    moved_name_ids: Mapped[str] = mapped_column(default="[]")


class SimilarityHint(Base):
    __tablename__ = "similarity_hints"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_a_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_b_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    score: Mapped[float]
    computed_at: Mapped[datetime.datetime]
    dismissed: Mapped[bool] = mapped_column(default=False)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/db && touch tests/db/__init__.py
git add src/coolpc/db/models.py tests/db/
git commit -m "feat: 新增資料庫 models"
```

---

## Task 3: DB Session 管理 + Alembic 初始化

**Files:**
- Create: `src/coolpc/db/session.py`
- Create: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_initial.py`
- Test: `tests/db/test_session.py`

**Interfaces:**
- Consumes: `coolpc.db.models.Base`（Task 2）
- Produces: `get_engine(db_path: str | None = None) -> Engine`、`get_session_factory(engine) -> sessionmaker[Session]`，供所有後續模組取得 DB session。環境變數 `COOLPC_DB_PATH` 可覆蓋預設路徑 `data/coolpc.db`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/db/test_session.py
import os
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import Base, Category

def test_get_engine_and_session_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = get_session_factory(engine)
    with Session() as session:
        session.add(Category(name="測試分類"))
        session.commit()
    with Session() as session:
        assert session.query(Category).count() == 1
    assert db_path.exists()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/db/test_session.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作 session.py**

```python
# src/coolpc/db/session.py
import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

DEFAULT_DB_PATH = "data/coolpc.db"


def get_db_path() -> str:
    return os.environ.get("COOLPC_DB_PATH", DEFAULT_DB_PATH)


def get_engine(db_path: str | None = None) -> Engine:
    path = db_path or get_db_path()
    return create_engine(f"sqlite:///{path}")


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/db/test_session.py -v`
Expected: PASS

- [ ] **Step 5: 初始化 Alembic 並產生首個 migration**

```bash
uv run alembic init migrations
```

編輯 `alembic.ini`：把 `sqlalchemy.url` 這行移除或留空（改由 `migrations/env.py` 動態決定）。

編輯 `migrations/env.py`，在 `target_metadata = None` 那行改為：

```python
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from coolpc.db.models import Base
from coolpc.db.session import get_db_path

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", f"sqlite:///{get_db_path()}")
```

```bash
uv run alembic revision --autogenerate -m "initial schema"
```

檢查產生的 `migrations/versions/xxxx_initial_schema.py` 是否包含全部 8 張表，若有缺漏（Alembic 對 SQLite 某些型別推斷可能不完整）手動修正。

- [ ] **Step 6: 套用 migration 並確認**

```bash
uv run alembic upgrade head
uv run python -c "
from coolpc.db.session import get_engine
from sqlalchemy import inspect
insp = inspect(get_engine())
print(sorted(insp.get_table_names()))
"
```

Expected 輸出包含全部 8 張表名（含 alembic_version）。

- [ ] **Step 7: Commit**

```bash
git add src/coolpc/db/session.py tests/db/test_session.py alembic.ini migrations/
git commit -m "feat: 新增 DB session 管理與 Alembic migration"
```

---

## Task 4: FTS5 全文索引 Migration

**Files:**
- Create: `migrations/versions/0002_fts5.py`
- Test: `tests/db/test_fts.py`

**Interfaces:**
- Consumes: `product_names` 表（Task 2/3）
- Produces: `products_fts` FTS5 虛擬表 + 觸發器（INSERT/UPDATE/DELETE on `product_names` 同步），供 Task 15（`/api/products` 搜尋）使用。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/db/test_fts.py
import datetime
import subprocess, sys, os
from sqlalchemy import text
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName

def _upgrade_head(db_path):
    env = os.environ.copy()
    env["COOLPC_DB_PATH"] = str(db_path)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)

def test_fts_search_finds_product_by_substring(tmp_path, monkeypatch):
    db_path = tmp_path / "fts.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    _upgrade_head(db_path)
    engine = get_engine(str(db_path))
    Session = get_session_factory(engine)
    now = datetime.datetime(2026, 2, 1)
    with Session() as session:
        cat = Category(name="固態硬碟")
        sub = Subcategory(name="NAS碟", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id,
                     current_name="Synology HAT3300 4TB PLUS系列(3.5吋/5400轉/三年保固)【限搭NAS主機】",
                     current_price=6890, is_active=True, first_seen_at=now,
                     last_seen_at=now, created_at=now)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name,
                                 first_seen_at=now, last_seen_at=now))
        session.commit()

        rows = session.execute(
            text("SELECT product_id FROM products_fts WHERE products_fts MATCH :q"),
            {"q": "限搭"},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == p.id
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/db/test_fts.py -v`
Expected: FAIL，`sqlalchemy.exc.OperationalError: no such table: products_fts`

- [ ] **Step 3: 撰寫 migration**

```python
# migrations/versions/0002_fts5.py
"""fts5 for product_names"""
from alembic import op

revision = "0002_fts5"
down_revision = "0001_initial"  # 依 Task 3 產生的實際 revision id 調整
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIRTUAL TABLE products_fts USING fts5(
            product_id UNINDEXED, name, tokenize='unicode61'
        )
    """)
    op.execute("""
        CREATE TRIGGER product_names_ai AFTER INSERT ON product_names BEGIN
            INSERT INTO products_fts(product_id, name) VALUES (new.product_id, new.name);
        END
    """)
    op.execute("""
        CREATE TRIGGER product_names_ad AFTER DELETE ON product_names BEGIN
            DELETE FROM products_fts WHERE product_id = old.product_id AND name = old.name;
        END
    """)
    op.execute("""
        CREATE TRIGGER product_names_au AFTER UPDATE ON product_names BEGIN
            DELETE FROM products_fts WHERE product_id = old.product_id AND name = old.name;
            INSERT INTO products_fts(product_id, name) VALUES (new.product_id, new.name);
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS product_names_au")
    op.execute("DROP TRIGGER IF EXISTS product_names_ad")
    op.execute("DROP TRIGGER IF EXISTS product_names_ai")
    op.execute("DROP TABLE IF EXISTS products_fts")
```

注意：`down_revision` 要填 Task 3 實際產生的 initial migration revision id（`uv run alembic history` 可查）。

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/db/test_fts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0002_fts5.py tests/db/test_fts.py
git commit -m "feat: 新增 FTS5 全文索引 migration"
```

---

## Task 5: Parser — Big5 解碼與估價時間解析

**Files:**
- Create: `src/coolpc/parser/models.py`
- Create: `src/coolpc/parser/html_parser.py`
- Test: `tests/parser/test_decode_and_time.py`

**Interfaces:**
- Consumes: 無
- Produces: `ParseError` exception；`decode_html(raw_bytes: bytes) -> str`；`parse_fetched_at(soup: BeautifulSoup) -> datetime.datetime`。供 Task 6/7 與 Task 8 起全部模組使用。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/parser/test_decode_and_time.py
import datetime
from bs4 import BeautifulSoup
from coolpc.parser.html_parser import decode_html, parse_fetched_at

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"

def test_decode_html_produces_correct_chinese_text():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    assert "原價屋線上估價" in text
    assert "顯示卡VGA" in text

def test_parse_fetched_at_reads_mdy_field():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    soup = BeautifulSoup(text, "lxml")
    fetched_at = parse_fetched_at(soup)
    assert fetched_at == datetime.datetime(2026, 2, 1, 14, 28)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/parser/test_decode_and_time.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/parser/models.py
from __future__ import annotations
import datetime
from dataclasses import dataclass, field


class ParseError(Exception):
    """HTML 結構異常或無法解析時拋出。"""


@dataclass
class ParsedProduct:
    category_name: str
    subcategory_name: str
    name: str
    price: int
    status: str | None
    badges: str


@dataclass
class ParsedSnapshot:
    fetched_at: datetime.datetime
    products: list[ParsedProduct] = field(default_factory=list)
```

```python
# src/coolpc/parser/html_parser.py
from __future__ import annotations
import datetime
import re
from bs4 import BeautifulSoup
from coolpc.parser.models import ParseError

MDY_PATTERN = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})")


def decode_html(raw_bytes: bytes) -> str:
    # 用 cp950（非內建 big5 codec）：big5 無法涵蓋 ETen 廠商擴充字元，
    # 會把「碁」等字解成亂碼，導致常見品牌「宏碁」變成「宏??」。
    try:
        return raw_bytes.decode("cp950", errors="replace")
    except LookupError as exc:
        raise ParseError(f"無法以 cp950 解碼: {exc}") from exc


def parse_fetched_at(soup: BeautifulSoup) -> datetime.datetime:
    node = soup.find(id="Mdy")
    if node is None:
        raise ParseError("找不到 #Mdy 估價時間欄位")
    m = MDY_PATTERN.search(node.get_text())
    if not m:
        raise ParseError(f"無法解析估價時間: {node.get_text()!r}")
    year, month, day, hour, minute = (int(g) for g in m.groups())
    return datetime.datetime(year, month, day, hour, minute)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/parser/test_decode_and_time.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/parser && touch tests/parser/__init__.py
git add src/coolpc/parser/ tests/parser/
git commit -m "feat: parser - Big5 解碼與估價時間解析"
```

---

## Task 6: Parser — 名稱/價格/後綴切分與狀態抽取

**Files:**
- Modify: `src/coolpc/parser/html_parser.py`
- Test: `tests/parser/test_split_and_status.py`

**Interfaces:**
- Consumes: `ParseError`（Task 5）
- Produces: `split_name_price_badges(option_text: str) -> tuple[str, int, str]`；`STATUS_KEYWORDS: list[str]`；`extract_status(name: str) -> str | None`。供 Task 7 使用。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/parser/test_split_and_status.py
import pytest
from coolpc.parser.html_parser import split_name_price_badges, extract_status
from coolpc.parser.models import ParseError

def test_split_basic_product():
    name, price, badges = split_name_price_badges(
        "GIGABYTE AI TOP NVIDIA ConnectX-7 連接線【現貨】, $3990 ★"
    )
    assert name == "GIGABYTE AI TOP NVIDIA ConnectX-7 連接線【現貨】"
    assert price == 3990
    assert badges == "★"

def test_split_with_hot_sale_and_bundle_badges():
    name, price, badges = split_name_price_badges(
        "Acer Nitro ARC B580 OC 12GB(2740MHz/27cm/雙風扇/註三年), $8490 ★ 熱賣"
    )
    assert name == "Acer Nitro ARC B580 OC 12GB(2740MHz/27cm/雙風扇/註三年)"
    assert price == 8490
    assert badges == "★ 熱賣"

def test_split_with_price_drop_prefix():
    name, price, badges = split_name_price_badges(
        "華擎 ARC B580 Challenger 12G OC(2740MHz/25cm/雙風扇/註三年), $9290↘$8990 ◆ ★"
    )
    assert name == "華擎 ARC B580 Challenger 12G OC(2740MHz/25cm/雙風扇/註三年)"
    assert price == 8990
    assert badges == "◆ ★"

def test_split_raises_on_malformed_text():
    with pytest.raises(ParseError):
        split_name_price_badges("這不是一個有效的商品字串")

def test_split_handles_arrow_before_comma_bundle_format():
    """真實資料另一種降價格式：逗號在箭頭之後而非之前（常見於「搭購」組合優惠），
    例如 "...$2,799↘, $1499 ★"（原價前沒有逗號，逗號出現在箭頭與新價之間）。"""
    name, price, badges = split_name_price_badges(
        "【螢幕搭購】Raymii LS5U (單螢幕/穿夾兩用/高負重氣壓/17-43吋/承載18KG) $2,799↘, $1499 ★"
    )
    assert name == "【螢幕搭購】Raymii LS5U (單螢幕/穿夾兩用/高負重氣壓/17-43吋/承載18KG)"
    assert price == 1499
    assert badges == "★"

def test_split_handles_arrow_before_comma_bundle_format_with_multiple_badges():
    name, price, badges = split_name_price_badges(
        "【主機搭購】PHILIPS 27E2G2200〈1H1P/IPS/144Hz/HDR10〉$2988↘, $2788 ◆ ★"
    )
    assert name == "【主機搭購】PHILIPS 27E2G2200〈1H1P/IPS/144Hz/HDR10〉"
    assert price == 2788
    assert badges == "◆ ★"

def test_split_handles_bare_old_price_before_arrow_bundle_format():
    """真實資料第三種降價格式：原價完全沒有 $ 前綴，只有裸數字後面緊接箭頭，
    常見於「組合優惠」整機搭購方案（例如「微星 Raider/Cyborg/Katana + 威剛
    16G」系列）。例如 "...125290↘, $124000 ◆ ★"（原價 125290 沒有 $，
    新價 124000 才有 $）。"""
    name, price, badges = split_name_price_badges(
        "【組合優惠】微星 Raider Ultra 9 黑 B2WI-025TW+威剛16G 125290↘, $124000 ◆ ★"
    )
    assert name == "【組合優惠】微星 Raider Ultra 9 黑 B2WI-025TW+威剛16G"
    assert price == 124000
    assert badges == "◆ ★"
    assert "," not in name
    assert "$" not in name
    assert "↘" not in name

def test_split_takes_final_price_across_chained_price_drops():
    """真實資料存在連續兩次降價的情況（例如 BenQ 螢幕搭購方案），
    例如 "...$3988↘, $3188↘$2988 ◆ ★"，必須取「最後」一次（最低）的價格
    2988，而不是中間那次 3188，且 badges 不應殘留 "↘$2988" 之類的片段。"""
    name, price, badges = split_name_price_badges(
        "【主機搭購】BenQ GW2790〈2H1P/IPS/100Hz/含喇叭〉.光智慧2.0 $3988↘, $3188↘$2988 ◆ ★"
    )
    assert name == "【主機搭購】BenQ GW2790〈2H1P/IPS/100Hz/含喇叭〉.光智慧2.0"
    assert price == 2988
    assert badges == "◆ ★"

def test_split_does_not_mis_split_on_embedded_dollar_sign_in_name():
    """真實資料的重大陷阱：商品名稱本身就含有行銷用的「原價$1590」字樣
    （$ 前面沒有逗號，只是緊貼在中文字後面，且沒有箭頭符號），例如
    "...原價$1590, $1190 ◆ ★ 熱賣"。逗號才是唯一能區分「這是價格起點」
    與「名稱裡剛好有個 $ 符號」的依據，所以沒有箭頭時，逗號必須是必要
    （不可為可選），否則會把名稱內嵌的 "$1590" 誤判成價格（應為 1190）。"""
    name, price, badges = split_name_price_badges(
        "視博通 MW-III 顯卡長35/CPU高16.5/網孔面板+燈條/玻璃透側/E-ATX 原價$1590, $1190 ◆ ★ 熱賣"
    )
    assert name == "視博通 MW-III 顯卡長35/CPU高16.5/網孔面板+燈條/玻璃透側/E-ATX 原價$1590"
    assert price == 1190
    assert badges == "◆ ★ 熱賣"

def test_split_handles_up_arrow_price_increase_warning():
    """真實資料還有一種與「↘ 降價」對稱的「↗ 漲價預告」格式，
    例如 "...(AD5U56008G-S), $2999↗$3099 ◆ ★"，常見於記憶體類商品，
    提醒買家即將漲價。目前實際在賣的價格是箭頭「前」的 2999，
    箭頭與未來價 3099 都應從 badges 消掉，不應殘留。"""
    name, price, badges = split_name_price_badges(
        "威剛 單條8GB D5-5600/CL46 (AD5U56008G-S), $2999↗$3099 ◆ ★"
    )
    assert name == "威剛 單條8GB D5-5600/CL46 (AD5U56008G-S)"
    assert price == 2999
    assert badges == "◆ ★"

def test_extract_status_finds_in_stock():
    assert extract_status("GIGABYTE 連接線【現貨】") == "現貨"

def test_extract_status_finds_order():
    assert extract_status("NVIDIA DGX Spark Cable 40 CM【訂】") == "訂"

def test_extract_status_ignores_non_status_bracket():
    assert extract_status("Synology HAT3300 4TB【限搭NAS主機】") is None

def test_extract_status_none_when_absent():
    assert extract_status("酷碼 VGA Holder 顯卡用支架 千斤頂顯卡支撐架/(0005-KUH00)") is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/parser/test_split_and_status.py -v`
Expected: FAIL，`ImportError: cannot import name 'split_name_price_badges'`

- [ ] **Step 3: 實作**

補在 `src/coolpc/parser/html_parser.py` 尾端：

```python

# 真實資料的降價格式：
#   1) "NAME, $原價↘$新價 標記"（逗號在原價之前，箭頭與新價之間無逗號）
#   2) "NAME $原價↘, $新價 標記"（原價前無逗號，逗號在箭頭與新價之間，
#      常見於「搭購」組合優惠）
#   3) "NAME 原價(無 $ 前綴)↘, $新價 標記"（原價完全沒有 $ 符號，只有裸數字，
#      常見於「組合優惠」整機搭購方案，如「微星 Raider/Cyborg/Katana + 威剛
#      16G」系列）
#   4) 連續降價："NAME $價1↘, $價2↘$價3 標記"（同一商品出現兩次以上的箭頭
#      降價，須取「最後」一次的價格，例如 BenQ 螢幕的搭購方案）
# 格式 3 的「裸數字」只有在後面緊接箭頭符號 ↘ 時才視為原價，避免誤吃一般
# 商品名稱結尾剛好是數字（例如型號）但其實沒有降價的情況——箭頭字元在真實
# 資料中只會出現在降價標記，是可靠的判斷依據。
#
# 全語料庫（842 份樣本）掃描曾發現一個更嚴重的真實案例：商品名稱本身就含有
# 行銷用的「原價$1590」字樣（$ 前面沒有逗號，只是緊貼在中文字後面），例如
# "...原價$1590, $1190 ◆ ★ 熱賣"。若把「NAME 前面的逗號」也設成可選
# （之前 NAME_PRICE_PLAIN_PATTERN 曾經這樣做，是為了處理沒有箭頭的簡單案例
# 誤帶入的舊假設），regex 會把名稱內嵌的 "$1590" 誤判成價格起點，切出錯誤
# 的價格（1590 而非真正在賣的 1190）且把逗號之後的真正價格片段殘留進
# badges。真正安全的判斷依據是：
#   - 有箭頭（↘）時，箭頭本身就是可靠的價格標記，箭頭前的價格可以沒有逗號
#     （對應格式 2/3/4）；
#   - 沒有箭頭時，逗號是唯一能區分「這是價格起點」與「名稱裡剛好有個 $ 符號」
#     的依據，因此逗號必須是必要（mandatory），不可省略。
# 因此拆成兩個子規則，先試「有箭頭」規則（逗號可省略，但箭頭必要，且用
# `(?:...)+` 讓箭頭段可重複出現、只保留最後一次的擷取值，處理格式 4 的連續
# 降價），找不到才退回「無箭頭、逗號必要、純 $價錢」規則。
NAME_PRICE_ARROW_PATTERN = re.compile(
    r"^(.*?)\s*,?\s*(?:\$([\d,]+)|(\d[\d,]{2,}))(?:↘\s*,?\s*\$([\d,]+))+\s*(.*)$", re.S
)
# 另有一種與「↘ 降價」對稱的「↗ 漲價預告」格式："NAME, $現價↗$未來價 標記"
# （現價前有逗號，箭頭與未來價之間沒有逗號），全語料庫掃描出現超過 5 萬次，
# 常見於記憶體類商品（提醒買家即將漲價）。這裡取箭頭「前」的現價（也就是
# 目前實際在賣的價格），並把箭頭與未來價一併從 badges 中消掉，避免殘留
# "↗$3099" 這類價格片段污染 badges 欄位。掃描全語料庫確認 ↗ 與 ↘ 不會同時
# 出現在同一段文字，也沒有連續多次 ↗ 的情況，所以不需要像 ↘ 一樣用可重複
# 的 group。
NAME_PRICE_UP_ARROW_PATTERN = re.compile(
    r"^(.*?)\s*,?\s*\$([\d,]+)↗\s*,?\s*\$([\d,]+)\s*(.*)$", re.S
)
NAME_PRICE_PLAIN_PATTERN = re.compile(r"^(.*?),\s*\$([\d,]+)\s*(.*)$", re.S)
STATUS_KEYWORDS = ["現貨", "訂", "客訂", "拆封品"]
STATUS_BRACKET_PATTERN = re.compile(r"[【｛]([^】｝]*)[】｝]")


def split_name_price_badges(option_text: str) -> tuple[str, int, str]:
    text = option_text.strip()
    m = NAME_PRICE_ARROW_PATTERN.match(text)
    if m:
        name = m.group(1).strip()
        price = int(m.group(4).replace(",", ""))
        badges = m.group(5).strip()
        return name, price, badges
    m = NAME_PRICE_UP_ARROW_PATTERN.match(text)
    if m:
        name = m.group(1).strip()
        price = int(m.group(2).replace(",", ""))
        badges = m.group(4).strip()
        return name, price, badges
    m = NAME_PRICE_PLAIN_PATTERN.match(text)
    if not m:
        raise ParseError(f"無法從商品文字切出名稱/價格: {text!r}")
    name = m.group(1).strip()
    price = int(m.group(2).replace(",", ""))
    badges = m.group(3).strip()
    return name, price, badges


def extract_status(name: str) -> str | None:
    brackets = STATUS_BRACKET_PATTERN.findall(name)
    for content in reversed(brackets):
        if content in STATUS_KEYWORDS:
            return content
    return None
```

**（本區塊已依 Task 7 全語料庫回歸抽測發現的三個真實 bug 更新到最終狀態，
細節見 Task 7 小節的說明；原始 Task 6 只實作了格式 1/2。）**

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/parser/test_split_and_status.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/parser/html_parser.py tests/parser/test_split_and_status.py
git commit -m "feat: parser - 名稱/價格/後綴切分與狀態抽取"
```

---

## Task 7: Parser — 完整快照解析整合

**Files:**
- Modify: `src/coolpc/parser/html_parser.py`
- Test: `tests/parser/test_parse_html.py`

**Interfaces:**
- Consumes: `decode_html`, `parse_fetched_at`, `split_name_price_badges`, `extract_status`, `ParseError`, `ParsedProduct`, `ParsedSnapshot`（Task 5/6）
- Produces: `parse_products(soup: BeautifulSoup) -> list[ParsedProduct]`；`parse_html(raw_bytes: bytes) -> ParsedSnapshot`（**主要對外入口**，供 Task 9 ingest 使用）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/parser/test_parse_html.py
import pytest
from coolpc.parser.html_parser import parse_html
from coolpc.parser.models import ParseError

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"

def test_parse_html_full_snapshot():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)

    assert snapshot.fetched_at.year == 2026
    assert snapshot.fetched_at.month == 2
    assert snapshot.fetched_at.day == 1

    assert len(snapshot.products) > 5000

    categories = {p.category_name for p in snapshot.products}
    assert "顯示卡VGA" in categories
    assert "處理器 CPU" in categories

    vga = [p for p in snapshot.products if p.category_name == "顯示卡VGA"]
    assert len(vga) > 100
    for p in vga[:20]:
        assert p.price > 0
        assert "," not in p.name  # 名稱本體不應殘留切分用的逗號結構性錯誤
        assert "$" not in p.name

def test_parse_html_excludes_disabled_and_summary_options():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)
    for p in snapshot.products:
        assert "此商品為專業性產品" not in p.name
        assert not p.name.startswith("共有商品")

def test_parse_html_raises_parse_error_on_garbage():
    with pytest.raises(ParseError):
        parse_html(b"<html><body>not a coolpc page</body></html>")

def test_parse_html_does_not_duplicate_options_across_nested_optgroups():
    """真實 HTML 的 <optgroup> 沒有對應的 </optgroup> 結束標籤，lxml 會把後續
    每個 <optgroup> 都巢狀解析進前一個 <optgroup> 內，而不是視為兄弟節點。
    若用預設的 recursive=True 抓 <option>，同一個商品會被外層 optgroup 重複
    計入，導致單一份快照的商品數暴增到十萬筆等級（實際應為數千筆）。這裡
    驗證商品數量級合理，並且商品數應精確等於「未被停用且非彙總列(value=0)
    的 <option> 總數」（獨立於 parse_products 邏輯之外直接統計得出），確認
    沒有任何 <option> 被重複計入或漏算。"""
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    from coolpc.parser.html_parser import decode_html
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(decode_html(raw), "lxml")
    tbody = soup.find(id="tbdy")
    expected_candidate_count = 0
    for tr in tbody.find_all("tr", recursive=False):
        select = tr.find("select")
        if select is None:
            continue
        for optgroup in select.find_all("optgroup"):
            for opt in optgroup.find_all("option", recursive=False):
                if opt.has_attr("disabled") or opt.get("value") == "0":
                    continue
                expected_candidate_count += 1

    snapshot = parse_html(raw)

    # 修正前約 10 萬筆（每個 option 被多個外層 optgroup 重複計入），
    # 修正後應精確等於獨立統計出的候選 option 數量
    assert len(snapshot.products) == expected_candidate_count
    assert len(snapshot.products) < 20000
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/parser/test_parse_html.py -v`
Expected: FAIL，`ImportError: cannot import name 'parse_html'`

- [ ] **Step 3: 實作**

補在 `src/coolpc/parser/html_parser.py` 尾端：

```python
from coolpc.parser.models import ParsedProduct, ParsedSnapshot


def parse_products(soup: BeautifulSoup) -> list[ParsedProduct]:
    tbody = soup.find(id="tbdy")
    if tbody is None:
        raise ParseError("找不到 #tbdy 商品表格")

    products: list[ParsedProduct] = []
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        category_name = tds[1].get_text(strip=True)
        select = tr.find("select")
        if select is None:
            continue
        for optgroup in select.find_all("optgroup"):
            subcategory_name = optgroup.get("label", "").strip()
            for opt in optgroup.find_all("option", recursive=False):
                if opt.has_attr("disabled"):
                    continue
                if opt.get("value") == "0":
                    continue
                text = opt.get_text(strip=True)
                if ", $" not in text:
                    continue
                try:
                    name, price, badges = split_name_price_badges(text)
                except ParseError:
                    continue
                status = extract_status(name)
                products.append(ParsedProduct(
                    category_name=category_name,
                    subcategory_name=subcategory_name,
                    name=name,
                    price=price,
                    status=status,
                    badges=badges,
                ))
    return products


def parse_html(raw_bytes: bytes) -> ParsedSnapshot:
    text = decode_html(raw_bytes)
    soup = BeautifulSoup(text, "lxml")
    fetched_at = parse_fetched_at(soup)
    products = parse_products(soup)
    if not products:
        raise ParseError("解析結果沒有任何商品，HTML 結構可能已變更")
    return ParsedSnapshot(fetched_at=fetched_at, products=products)
```

**注意：`optgroup.find_all("option")` 這裡務必加上 `recursive=False`**
（原始草稿沒有這個參數，是 Step 5 全語料庫回歸抽測發現的第一個 bug，見下方
說明），否則單一份快照的商品數會暴增到十萬筆等級。

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/parser/test_parse_html.py -v`
Expected: PASS

- [ ] **Step 5: 用多份不同時期樣本做回歸抽測，確保解析穩定**

```bash
uv run python -c "
import glob
from coolpc.parser.html_parser import parse_html
files = sorted(glob.glob('/home/xthybot/coolpc/download/*.html'))
sample = [files[0], files[len(files)//4], files[len(files)//2], files[3*len(files)//4], files[-1]]
for f in sample:
    with open(f, 'rb') as fh:
        snap = parse_html(fh.read())
    print(f, snap.fetched_at, len(snap.products))
"
```

Expected: 5 行輸出，皆無例外，商品數量皆為合理量級（數千筆）。

**Step 5 實際執行結果：認真抽查後發現三個真實 bug，皆已修正並補上回歸測試
（詳見 `src/coolpc/parser/html_parser.py` 與 `tests/parser/` 內的說明註解與
測試案例）：**

1. **`parse_products` 的巢狀 `<optgroup>` 重複計算 bug（本 Task 新增程式碼
   本身的 bug）**：原價屋真實 HTML 的 `<optgroup>` 標籤沒有對應的
   `</optgroup>` 結束標籤。lxml 依 HTML5 規則本應在遇到下一個 `<optgroup>`
   時隱式關閉前一個（成為兄弟節點），但實測會把後續每個 `<optgroup>` 都
   巢狀解析進前一個 `<optgroup>` 內。原始草稿用預設的 `recursive=True`
   呼叫 `optgroup.find_all("option")`，導致同一個 `<option>` 被計入多個
   （外層）optgroup，單一份快照的商品數從應有的數千筆暴增到約 10 萬筆
   （超出 20 倍），且 `subcategory_name` 常被誤植為外層（更早出現）的
   分類名稱。修正方式：改用 `recursive=False`，只取「緊接在這個
   optgroup 開始標籤之後、下一個巢狀 optgroup 之前」的 `<option>`。
   已於 842 份樣本全部驗證：修正後的商品數精確等於獨立統計出的候選
   `<option>` 數量（無重複也無遺漏）。

2. **`split_name_price_badges`（Task 6 遺留）對第三種降價格式
   （原價無 `$` 前綴的裸數字，如「組合優惠」整機搭購方案）處理不到**：
   全語料庫掃描發現 4 種商品、842 份樣本中累計 425 次出現，例如
   "...125290↘, $124000 ◆ ★"。已改用「有箭頭 / 無箭頭」兩個子規則
   處理（見 Task 6 小節最新版 regex），並支援連續兩次降價
   （"...$3988↘, $3188↘$2988 ◆ ★" 需取最後一次價格 2988）。

3. **`split_name_price_badges`（Task 6 遺留）對「名稱本身含有行銷用
   `$` 字樣」誤判價格起點的嚴重 bug**：Task 6 審查時曾提出一個
   「未確認的理論風險」——NAME_PRICE_PATTERN 把逗號設為可選
   （`\s*,?\s*\$`）可能誤吃名稱裡剛好出現的裸 `$` 符號。全語料庫掃描
   證實這個風險**確實會發生**，例如
   "視博通 MW-III ... 原價$1590, $1190 ◆ ★ 熱賣" 會被誤判成
   price=1590（名稱內嵌的行銷用「原價$1590」），而不是真正在賣的
   1190，且逗號之後的真正價格片段殘留進 badges。這比前兩個 bug更嚴重，
   因為它直接導致**價格資料本身錯誤**，而不只是名稱/badges 欄位有雜訊。
   修正方式：拆成「有箭頭」（`NAME_PRICE_ARROW_PATTERN`，逗號可省略但箭頭
   必要——箭頭字元本身是可靠的價格標記）與「無箭頭」
   （`NAME_PRICE_PLAIN_PATTERN`，逗號恢復為必要）兩個子規則，因為沒有
   箭頭時逗號是唯一能區分「這是價格起點」與「名稱裡剛好有個 $ 符號」的
   依據。全語料庫驗證：修正後所有商品名稱中若仍含有 `$`（全語料庫僅 9
   筆，皆為「原價$X」這類合法行銷文字），其擷取出的價格都與人工核對的
   真實售價一致。

   附帶發現並修正一個同源、但影響較小（不影響價格正確性，只影響 badges
   欄位乾淨度）的第四個真實格式：與「↘ 降價」對稱的「↗ 漲價預告」格式
   （"NAME, $現價↗$未來價 標記"，常見於記憶體類商品，提醒買家即將漲價，
   全語料庫超過 5 萬次出現）。修正前這類商品的 badges 會殘留
   "↗$3099 ◆ ★" 之類的價格片段；修正後正確取箭頭前的現價，badges 乾淨。

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/parser/html_parser.py tests/parser/test_parse_html.py
git commit -m "feat: parser - 完整快照解析整合入口 parse_html"
```

之後另有一個 `fix:` commit 修正上述三個 Step 5 發現的 bug（含 Task 6
regex 的相應更新與新增回歸測試）。

---

## Task 8: Ingest — 單一商品比對/建立/更新

**Files:**
- Create: `src/coolpc/ingest/service.py`
- Test: `tests/ingest/test_ingest_product.py`

**Interfaces:**
- Consumes: `Category, Subcategory, Product, ProductName, PriceHistory`（Task 2）；`ParsedProduct`（Task 5）
- Produces: `get_or_create_category`, `get_or_create_subcategory`, `guess_brand`, `guess_model`, `ingest_product(session, parsed, category, subcategory, fetched_at, snapshot_id) -> tuple[Product, bool, int]`（`bool`=is_new，`int`=price_delta，新商品為 0）。供 Task 9 使用。

**不變量（供後續 Task 14 合併邏輯遵守）：** 合併後，來源商品名下的 `ProductName` 一律改掛到目標商品，因此依名稱查 `ProductName` 永遠直接對應到目前有效（未被合併）的商品，不需要沿 `merged_into_id` 鏈往上找。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/ingest/test_ingest_product.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Product, ProductName, PriceHistory
from coolpc.ingest.service import (
    get_or_create_category, get_or_create_subcategory, ingest_product,
    guess_brand, guess_model,
)
from coolpc.parser.models import ParsedProduct

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def test_ingest_new_product_creates_all_records():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1, 21, 40)
    cat = get_or_create_category(session, "顯示卡VGA")
    sub = get_or_create_subcategory(session, cat, "NVIDIA")
    parsed = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                            name="ASUS DUAL-RTX3050-O6G", price=7990, status=None, badges="◆ ★")
    product, is_new, delta = ingest_product(session, parsed, cat, sub, t0, snapshot_id=1)
    session.flush()

    assert is_new is True
    assert delta == 0
    assert product.current_price == 7990
    assert session.query(ProductName).filter_by(name="ASUS DUAL-RTX3050-O6G").count() == 1
    assert session.query(PriceHistory).filter_by(product_id=product.id).count() == 1

def test_ingest_existing_product_updates_price_and_reactivates():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1, 21, 40)
    t1 = datetime.datetime(2026, 2, 2, 0, 0)
    cat = get_or_create_category(session, "顯示卡VGA")
    sub = get_or_create_subcategory(session, cat, "NVIDIA")
    parsed = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                            name="ASUS DUAL-RTX3050-O6G", price=7990, status=None, badges="◆ ★")
    product, _, _ = ingest_product(session, parsed, cat, sub, t0, snapshot_id=1)
    session.flush()
    product.is_active = False  # 模擬曾經下架

    parsed2 = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                             name="ASUS DUAL-RTX3050-O6G", price=8490, status=None, badges="◆ ★ 熱賣")
    product2, is_new2, delta2 = ingest_product(session, parsed2, cat, sub, t1, snapshot_id=2)
    session.flush()

    assert is_new2 is False
    assert product2.id == product.id
    assert delta2 == 500
    assert product2.current_price == 8490
    assert product2.is_active is True
    assert product2.last_seen_at == t1
    assert product2.last_change_amount == 500
    assert round(product2.last_change_percent, 2) == round(500 / 7990 * 100, 2)
    assert session.query(ProductName).count() == 1  # 沒有新增歷史名稱
    assert session.query(PriceHistory).filter_by(product_id=product.id).count() == 2

def test_guess_brand_matches_known_prefix():
    assert guess_brand("ASUS DUAL-RTX3050-O6G") == "ASUS"
    assert guess_brand("微星 N730-2GD3V3") == "微星"
    assert guess_brand("不知名品牌的東西") is None

def test_guess_model_extracts_bracket_code():
    assert guess_model("ASUS【H-V500MV-31315U042W】i3-1315U") == "H-V500MV-31315U042W"
    assert guess_model("沒有型號代碼的商品") is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/ingest/test_ingest_product.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'coolpc.ingest.service'`

- [ ] **Step 3: 實作**

```python
# src/coolpc/ingest/service.py
from __future__ import annotations
import datetime
import re
from sqlalchemy.orm import Session
from coolpc.db.models import Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.parser.models import ParsedProduct

KNOWN_BRANDS = [
    "ASUS", "華碩", "微星", "MSI", "技嘉", "GIGABYTE", "酷碼", "ZOTAC", "INNO3D",
    "華擎", "ASRock", "INTEL", "NVIDIA", "Acer", "宏碁", "Lenovo", "聯想",
    "Synology", "HP", "AMD", "Kingston", "金士頓", "十銓", "威剛", "ADATA",
    "創見", "Transcend", "Seagate", "希捷", "WD", "威健", "Cooler Master",
]
MODEL_BRACKET_PATTERN = re.compile(r"[【｛]([A-Za-z0-9][A-Za-z0-9\-/. ]{2,})[】｝]")


def get_or_create_category(session: Session, name: str) -> Category:
    cat = session.query(Category).filter_by(name=name).one_or_none()
    if cat is None:
        cat = Category(name=name)
        session.add(cat)
        session.flush()
    return cat


def get_or_create_subcategory(session: Session, category: Category, name: str) -> Subcategory:
    sub = session.query(Subcategory).filter_by(category_id=category.id, name=name).one_or_none()
    if sub is None:
        sub = Subcategory(category_id=category.id, name=name)
        session.add(sub)
        session.flush()
    return sub


def guess_brand(name: str) -> str | None:
    for brand in KNOWN_BRANDS:
        if name.startswith(brand):
            return brand
    return None


def guess_model(name: str) -> str | None:
    m = MODEL_BRACKET_PATTERN.search(name)
    return m.group(1).strip() if m else None


def ingest_product(
    session: Session,
    parsed: ParsedProduct,
    category: Category,
    subcategory: Subcategory,
    fetched_at: datetime.datetime,
    snapshot_id: int,
) -> tuple[Product, bool, int]:
    existing_name = session.query(ProductName).filter_by(name=parsed.name).one_or_none()

    if existing_name is not None:
        product = session.get(Product, existing_name.product_id)
        price_delta = parsed.price - product.current_price
        product.last_change_amount = price_delta
        product.last_change_percent = (
            (price_delta / product.current_price * 100) if product.current_price else None
        )
        product.current_price = parsed.price
        product.current_status = parsed.status
        product.category_id = category.id
        product.subcategory_id = subcategory.id
        product.is_active = True
        product.last_seen_at = fetched_at
        existing_name.last_seen_at = fetched_at
        session.add(PriceHistory(
            product_id=product.id, price=parsed.price, status=parsed.status,
            badges=parsed.badges, scraped_at=fetched_at, snapshot_id=snapshot_id,
        ))
        return product, False, price_delta

    product = Product(
        category_id=category.id, subcategory_id=subcategory.id,
        current_name=parsed.name, brand=guess_brand(parsed.name), model=guess_model(parsed.name),
        current_status=parsed.status, current_price=parsed.price,
        is_active=True, first_seen_at=fetched_at, last_seen_at=fetched_at,
        created_at=fetched_at,
    )
    session.add(product)
    session.flush()
    session.add(ProductName(product_id=product.id, name=parsed.name,
                             first_seen_at=fetched_at, last_seen_at=fetched_at))
    session.add(PriceHistory(
        product_id=product.id, price=parsed.price, status=parsed.status,
        badges=parsed.badges, scraped_at=fetched_at, snapshot_id=snapshot_id,
    ))
    return product, True, 0
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/ingest/test_ingest_product.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/ingest && touch tests/ingest/__init__.py
git add src/coolpc/ingest/service.py tests/ingest/
git commit -m "feat: ingest - 單一商品比對/建立/更新邏輯"
```

---

## Task 9: Ingest — 完整快照接入（下架判斷 + 統計 + Transaction）

**Files:**
- Modify: `src/coolpc/ingest/service.py`
- Test: `tests/ingest/test_ingest_snapshot.py`

**Interfaces:**
- Consumes: `ingest_product` 等（Task 8）；`ParsedSnapshot`（Task 5）；`ScrapeSnapshot`（Task 2）
- Produces: `ingest_snapshot(session: Session, parsed: ParsedSnapshot, scrape_type: str, raw_html_path: str | None) -> ScrapeSnapshot`（**主要對外入口**）。供 Task 12（scraper）、Task 13（CLI 匯入）使用。呼叫端負責 `session.commit()`／例外時 `session.rollback()`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/ingest/test_ingest_snapshot.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Product
from coolpc.ingest.service import ingest_snapshot
from coolpc.parser.models import ParsedProduct, ParsedSnapshot

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _snap(fetched_at, products):
    return ParsedSnapshot(fetched_at=fetched_at, products=products)

def test_ingest_snapshot_counts_new_products():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    parsed = _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ])
    snap = ingest_snapshot(session, parsed, scrape_type="manual", raw_html_path="/x.html")
    session.commit()

    assert snap.total_products == 2
    assert snap.new_products == 2
    assert snap.delisted_products == 0
    assert snap.status == "success"
    assert session.query(Product).count() == 2

def test_ingest_snapshot_detects_price_change_and_delisting():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)

    snap1 = ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()
    assert snap1.new_products == 2

    # 第二次抓取：第一個商品漲價，第二個商品消失（應標記下架）
    snap2 = ingest_snapshot(session, _snap(t1, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 8490, None, "◆ ★ 熱賣"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()

    assert snap2.new_products == 0
    assert snap2.price_up_count == 1
    assert snap2.price_down_count == 0
    assert snap2.delisted_products == 1

    active = session.query(Product).filter_by(is_active=True).all()
    inactive = session.query(Product).filter_by(is_active=False).all()
    assert len(active) == 1
    assert active[0].current_name == "ASUS DUAL-RTX3050-O6G"
    assert len(inactive) == 1
    assert inactive[0].current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

def test_ingest_snapshot_reactivates_delisted_product():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)
    t2 = datetime.datetime(2026, 2, 1, 12, 0)

    ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()

    ingest_snapshot(session, _snap(t1, []), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    delisted = session.query(Product).filter_by(is_active=False).one()
    assert delisted.current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

    ingest_snapshot(session, _snap(t2, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    reactivated = session.query(Product).one()
    assert reactivated.is_active is True
    assert reactivated.last_seen_at == t2
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/ingest/test_ingest_snapshot.py -v`
Expected: FAIL，`ImportError: cannot import name 'ingest_snapshot'`

- [ ] **Step 3: 實作**

補在 `src/coolpc/ingest/service.py` 尾端：

```python
from coolpc.db.models import ScrapeSnapshot
from coolpc.parser.models import ParsedSnapshot


def ingest_snapshot(
    session: Session,
    parsed: ParsedSnapshot,
    scrape_type: str,
    raw_html_path: str | None,
) -> ScrapeSnapshot:
    snapshot = ScrapeSnapshot(
        fetched_at=parsed.fetched_at, scrape_type=scrape_type,
        raw_html_path=raw_html_path, status="success", error_message=None,
        created_at=datetime.datetime.utcnow(),
    )
    session.add(snapshot)
    session.flush()

    total = new = up = down = 0
    seen_product_ids: set[int] = set()

    for parsed_product in parsed.products:
        category = get_or_create_category(session, parsed_product.category_name)
        subcategory = get_or_create_subcategory(session, category, parsed_product.subcategory_name)
        product, is_new, price_delta = ingest_product(
            session, parsed_product, category, subcategory, parsed.fetched_at, snapshot.id,
        )
        seen_product_ids.add(product.id)
        total += 1
        if is_new:
            new += 1
        elif price_delta > 0:
            up += 1
        elif price_delta < 0:
            down += 1

    delisted = 0
    active_products = (
        session.query(Product)
        .filter(Product.is_active.is_(True), Product.merged_into_id.is_(None))
        .all()
    )
    for product in active_products:
        if product.id not in seen_product_ids:
            product.is_active = False
            delisted += 1

    snapshot.total_products = total
    snapshot.new_products = new
    snapshot.delisted_products = delisted
    snapshot.price_up_count = up
    snapshot.price_down_count = down
    return snapshot
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/ingest/test_ingest_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: 用兩份真實時序相近樣本做整合驗證**

```bash
uv run python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base
from coolpc.parser.html_parser import parse_html
from coolpc.ingest.service import ingest_snapshot

engine = create_engine('sqlite:///:memory:')
Base.metadata.create_all(engine)
session = Session(engine)

for path in ['/home/xthybot/coolpc/download/2026-02-01-21-40.html',
             '/home/xthybot/coolpc/download/2026-02-02-00-00.html']:
    with open(path, 'rb') as f:
        parsed = parse_html(f.read())
    snap = ingest_snapshot(session, parsed, scrape_type='import', raw_html_path=path)
    session.commit()
    print(path, snap.total_products, snap.new_products, snap.delisted_products,
          snap.price_up_count, snap.price_down_count)
"
```

Expected: 第二筆的 `new_products` 遠小於第一筆（大部分商品已存在），且無例外拋出。

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/ingest/service.py tests/ingest/test_ingest_snapshot.py
git commit -m "feat: ingest - 完整快照接入，含下架/重新上架與統計"
```

---

## Task 10: Matching — 名稱正規化與相似度候選

**Files:**
- Create: `src/coolpc/matching/similarity.py`
- Test: `tests/matching/test_similarity.py`

**Interfaces:**
- Consumes: `Product, SimilarityHint`（Task 2）
- Produces: `normalize_name(name: str) -> str`；`compute_similarity(a: str, b: str) -> float`；`SIMILARITY_THRESHOLD: float`；`refresh_similarity_hints(session, category_id=None, now=None) -> int`（新增筆數）。供 Task 22（管理介面「可能需要合併」列表）使用。**系統本身絕不依此自動合併，僅寫入候選供人工參考。**

- [ ] **Step 1: 寫失敗測試**

```python
# tests/matching/test_similarity.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint
from coolpc.matching.similarity import normalize_name, compute_similarity, refresh_similarity_hints

def test_normalize_name_strips_brackets_and_width():
    assert normalize_name("ＡＳＵＳ　RTX5070　【現貨】") == normalize_name("ASUS RTX5070")

def test_compute_similarity_high_for_near_identical():
    a = "ASUS RTX 5070 PRIME 12G"
    b = "ASUS RTX 5070 PRIME OC 12GB"
    score = compute_similarity(a, b)
    assert score > 0.7

def test_compute_similarity_low_for_unrelated():
    score = compute_similarity("ASUS RTX 5070 PRIME 12G", "Kingston 隨身碟 64GB")
    assert score < 0.3

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _make_product(session, cat, sub, name, is_active, t):
    p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                current_price=100, is_active=is_active, first_seen_at=t,
                last_seen_at=t, created_at=t)
    session.add(p)
    session.flush()
    return p

def test_refresh_similarity_hints_finds_renamed_product_pair():
    session = _session()
    t = datetime.datetime(2026, 2, 1)
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    _make_product(session, cat, sub, "ASUS RTX 5070 PRIME 12G", False, t)
    _make_product(session, cat, sub, "ASUS RTX 5070 PRIME OC 12GB", True, t)
    session.commit()

    created = refresh_similarity_hints(session, now=t)
    session.commit()

    assert created == 1
    hints = session.query(SimilarityHint).all()
    assert len(hints) == 1
    assert hints[0].score > 0.7

def test_refresh_similarity_hints_ignores_cross_category_pairs():
    session = _session()
    t = datetime.datetime(2026, 2, 1)
    cat1 = Category(name="顯示卡VGA")
    cat2 = Category(name="固態硬碟")
    sub1 = Subcategory(name="NVIDIA", category=cat1)
    sub2 = Subcategory(name="NAS碟", category=cat2)
    session.add_all([cat1, cat2, sub1, sub2])
    session.flush()
    _make_product(session, cat1, sub1, "ASUS RTX 5070 PRIME 12G", True, t)
    _make_product(session, cat2, sub2, "ASUS RTX 5070 PRIME OC 12GB", True, t)
    session.commit()

    created = refresh_similarity_hints(session, now=t)
    assert created == 0

def test_refresh_similarity_hints_does_not_duplicate_existing_pair():
    session = _session()
    t = datetime.datetime(2026, 2, 1)
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    _make_product(session, cat, sub, "ASUS RTX 5070 PRIME 12G", False, t)
    _make_product(session, cat, sub, "ASUS RTX 5070 PRIME OC 12GB", True, t)
    session.commit()

    first = refresh_similarity_hints(session, now=t)
    session.commit()
    second = refresh_similarity_hints(session, now=t)
    session.commit()
    assert first == 1
    assert second == 0
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/matching/test_similarity.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/matching/similarity.py
from __future__ import annotations
import datetime
import re
import unicodedata
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from coolpc.db.models import Product, SimilarityHint

BRACKET_PATTERN = re.compile(r"[【】｛｝()（）\[\]]")
WHITESPACE_PATTERN = re.compile(r"\s+")
SIMILARITY_THRESHOLD = 0.75


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    normalized = BRACKET_PATTERN.sub("", normalized)
    normalized = WHITESPACE_PATTERN.sub("", normalized)
    return normalized.strip().lower()


def compute_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def refresh_similarity_hints(
    session: Session, category_id: int | None = None,
    now: datetime.datetime | None = None,
) -> int:
    now = now or datetime.datetime.utcnow()
    query = session.query(Product).filter(Product.merged_into_id.is_(None))
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)
    products = query.all()

    by_category: dict[int, list[Product]] = {}
    for p in products:
        by_category.setdefault(p.category_id, []).append(p)

    existing_pairs = {
        (min(h.product_a_id, h.product_b_id), max(h.product_a_id, h.product_b_id))
        for h in session.query(SimilarityHint).all()
    }

    created = 0
    for group in by_category.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                p1, p2 = group[i], group[j]
                pair = (min(p1.id, p2.id), max(p1.id, p2.id))
                if pair in existing_pairs:
                    continue
                score = compute_similarity(p1.current_name, p2.current_name)
                if score >= SIMILARITY_THRESHOLD:
                    session.add(SimilarityHint(
                        product_a_id=pair[0], product_b_id=pair[1],
                        score=score, computed_at=now, dismissed=False,
                    ))
                    existing_pairs.add(pair)
                    created += 1
    return created
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/matching/test_similarity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/matching && touch tests/matching/__init__.py
git add src/coolpc/matching/ tests/matching/
git commit -m "feat: matching - 名稱正規化與相似度候選"
```

---

## Task 11: Scraper — HTTP 下載與原始 HTML 存檔

**Files:**
- Create: `src/coolpc/scraper/fetcher.py`
- Test: `tests/scraper/test_fetcher.py`

**Interfaces:**
- Consumes: 無
- Produces: `FetchError`；`get_evaluate_url() -> str`；`fetch_html(url=None, timeout=30.0, client=None) -> bytes`；`save_raw_html(raw_bytes, fetched_at, base_dir="data/raw_html") -> str`（回傳存檔路徑）。供 Task 12 使用。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/scraper/test_fetcher.py
import datetime
import httpx
import pytest
from coolpc.scraper.fetcher import fetch_html, save_raw_html, FetchError

def test_fetch_html_returns_body_on_success():
    def handler(request):
        return httpx.Response(200, content="<html>ok 原價屋</html>".encode("cp950"))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)
    assert "原價屋" in result.decode("cp950")

def test_fetch_html_raises_fetch_error_on_http_status_error():
    def handler(request):
        return httpx.Response(500)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)

def test_fetch_html_raises_fetch_error_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)

def test_save_raw_html_writes_file_under_date_dir(tmp_path):
    fetched_at = datetime.datetime(2026, 2, 1, 21, 40, 0)
    path = save_raw_html(b"hello", fetched_at, base_dir=str(tmp_path))
    assert path.endswith("2026-02-01-21-40-00.html")
    assert "2026" in path and "02" in path and "01" in path
    with open(path, "rb") as f:
        assert f.read() == b"hello"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/scraper/test_fetcher.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/scraper/fetcher.py
from __future__ import annotations
import datetime
import os
import httpx

DEFAULT_URL = "https://coolpc.com.tw/evaluate.php"


class FetchError(Exception):
    pass


def get_evaluate_url() -> str:
    return os.environ.get("COOLPC_EVALUATE_URL", DEFAULT_URL)


def fetch_html(url: str | None = None, timeout: float = 30.0,
                client: httpx.Client | None = None) -> bytes:
    target = url or get_evaluate_url()
    owns_client = client is None
    client = client or httpx.Client()
    try:
        try:
            response = client.get(target, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP 錯誤 {exc.response.status_code}: {target}") from exc
        except httpx.RequestError as exc:
            raise FetchError(f"網路請求失敗: {exc}") from exc
        return response.content
    finally:
        if owns_client:
            client.close()


def save_raw_html(raw_bytes: bytes, fetched_at: datetime.datetime,
                   base_dir: str = "data/raw_html") -> str:
    day_dir = os.path.join(base_dir, f"{fetched_at:%Y}", f"{fetched_at:%m}", f"{fetched_at:%d}")
    os.makedirs(day_dir, exist_ok=True)
    filename = f"{fetched_at:%Y-%m-%d-%H-%M-%S}.html"
    path = os.path.join(day_dir, filename)
    with open(path, "wb") as f:
        f.write(raw_bytes)
    return path
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/scraper/test_fetcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/scraper && touch tests/scraper/__init__.py
git add src/coolpc/scraper/fetcher.py tests/scraper/
git commit -m "feat: scraper - HTTP 下載與原始 HTML 存檔"
```

---

## Task 12: Scraper — 併發鎖與抓取整合流程

**Files:**
- Create: `src/coolpc/scraper/lock.py`
- Create: `src/coolpc/scraper/run.py`
- Test: `tests/scraper/test_lock.py`, `tests/scraper/test_run.py`

**Interfaces:**
- Consumes: `fetch_html, save_raw_html, FetchError`（Task 11）；`parse_html, ParseError`（Task 7）；`ingest_snapshot`（Task 9）；`get_engine, get_session_factory`（Task 3）；`ScrapeSnapshot`（Task 2）
- Produces: `ScraperLock`（context manager，`acquire()->bool`, `release()->None`）；`ScrapeSkipped` exception；`run_scrape(scrape_type="scheduled", session_factory=None, url=None, lock_path="data/scraper.lock", raw_html_base_dir="data/raw_html") -> ScrapeSnapshot`（**主要對外入口**）。供 Task 13（CLI）、Task 22（管理介面手動抓取）使用。

- [ ] **Step 1: 寫失敗測試（Lock）**

```python
# tests/scraper/test_lock.py
import os
from coolpc.scraper.lock import ScraperLock

def test_acquire_and_release(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    lock = ScraperLock(lock_path)
    assert lock.acquire() is True
    assert os.path.exists(lock_path)
    lock.release()
    assert not os.path.exists(lock_path)

def test_second_acquire_fails_while_held(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    lock1 = ScraperLock(lock_path)
    lock2 = ScraperLock(lock_path)
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()

def test_stale_lock_is_reclaimed(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    with open(lock_path, "w") as f:
        f.write("999999999")  # 不存在的 PID
    lock = ScraperLock(lock_path)
    assert lock.acquire() is True
    lock.release()

def test_context_manager_raises_when_locked(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    holder = ScraperLock(lock_path)
    holder.acquire()
    try:
        with __import__("pytest").raises(RuntimeError):
            with ScraperLock(lock_path):
                pass
    finally:
        holder.release()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/scraper/test_lock.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作 lock.py**

```python
# src/coolpc/scraper/lock.py
from __future__ import annotations
import os


class ScraperLock:
    def __init__(self, lock_path: str = "data/scraper.lock"):
        self.lock_path = lock_path
        self._acquired = False

    def acquire(self) -> bool:
        parent = os.path.dirname(self.lock_path) or "."
        os.makedirs(parent, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._is_stale():
                os.remove(self.lock_path)
                return self.acquire()
            return False
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        self._acquired = True
        return True

    def _is_stale(self) -> bool:
        try:
            with open(self.lock_path) as f:
                pid = int(f.read().strip())
        except (ValueError, FileNotFoundError):
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def release(self) -> None:
        if self._acquired and os.path.exists(self.lock_path):
            os.remove(self.lock_path)
        self._acquired = False

    def __enter__(self) -> "ScraperLock":
        if not self.acquire():
            raise RuntimeError("已有抓取程序正在執行中")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
```

- [ ] **Step 4: 執行測試確認通過（Lock）**

Run: `uv run pytest tests/scraper/test_lock.py -v`
Expected: PASS

- [ ] **Step 5: 寫失敗測試（run_scrape）**

```python
# tests/scraper/test_run.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base
from coolpc.scraper.run import run_scrape, ScrapeSkipped
from coolpc.scraper.lock import ScraperLock
from coolpc.scraper.fetcher import FetchError

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"

def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

def test_run_scrape_success(tmp_path, monkeypatch):
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    monkeypatch.setattr("coolpc.scraper.run.fetch_html", lambda url=None: raw)
    snapshot = run_scrape(
        scrape_type="manual",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "success"
    assert snapshot.total_products > 5000
    assert snapshot.raw_html_path is not None
    import os
    assert os.path.exists(snapshot.raw_html_path)

def test_run_scrape_records_failure_on_fetch_error(tmp_path, monkeypatch):
    def raise_fetch_error(url=None):
        raise FetchError("網路失敗")
    monkeypatch.setattr("coolpc.scraper.run.fetch_html", raise_fetch_error)
    snapshot = run_scrape(
        scrape_type="scheduled",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "failed"
    assert "網路失敗" in snapshot.error_message
    assert snapshot.raw_html_path is None

def test_run_scrape_saves_html_and_records_failure_on_parse_error(tmp_path, monkeypatch):
    monkeypatch.setattr("coolpc.scraper.run.fetch_html",
                         lambda url=None: b"<html><body>not coolpc</body></html>")
    snapshot = run_scrape(
        scrape_type="scheduled",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "failed"
    assert snapshot.raw_html_path is not None
    import os
    assert os.path.exists(snapshot.raw_html_path)

def test_run_scrape_skips_when_locked(tmp_path, monkeypatch):
    lock_path = str(tmp_path / "s.lock")
    holder = ScraperLock(lock_path)
    holder.acquire()
    try:
        monkeypatch.setattr("coolpc.scraper.run.fetch_html", lambda url=None: b"")
        try:
            run_scrape(scrape_type="manual", session_factory=_session_factory(),
                       lock_path=lock_path, raw_html_base_dir=str(tmp_path / "raw"))
            assert False, "應該要拋出 ScrapeSkipped"
        except ScrapeSkipped:
            pass
    finally:
        holder.release()
```

- [ ] **Step 6: 執行測試確認失敗**

Run: `uv run pytest tests/scraper/test_run.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 7: 實作 run.py**

```python
# src/coolpc/scraper/run.py
from __future__ import annotations
import datetime
from sqlalchemy.orm import sessionmaker, Session
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import ScrapeSnapshot
from coolpc.parser.html_parser import parse_html
from coolpc.parser.models import ParseError
from coolpc.ingest.service import ingest_snapshot
from coolpc.scraper.fetcher import fetch_html, save_raw_html, FetchError
from coolpc.scraper.lock import ScraperLock


class ScrapeSkipped(Exception):
    pass


def _record_failure(session_factory: sessionmaker[Session], scrape_type: str,
                     error_message: str, raw_html_path: str | None) -> ScrapeSnapshot:
    with session_factory() as session:
        snapshot = ScrapeSnapshot(
            fetched_at=datetime.datetime.utcnow(), scrape_type=scrape_type,
            raw_html_path=raw_html_path, status="failed", error_message=error_message,
            created_at=datetime.datetime.utcnow(),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot


def run_scrape(
    scrape_type: str = "scheduled",
    session_factory: sessionmaker[Session] | None = None,
    url: str | None = None,
    lock_path: str = "data/scraper.lock",
    raw_html_base_dir: str = "data/raw_html",
) -> ScrapeSnapshot:
    session_factory = session_factory or get_session_factory(get_engine())
    lock = ScraperLock(lock_path)
    if not lock.acquire():
        raise ScrapeSkipped("已有抓取程序正在執行中，本次跳過")
    try:
        try:
            raw_bytes = fetch_html(url=url)
        except FetchError as exc:
            return _record_failure(session_factory, scrape_type, str(exc), None)

        try:
            parsed = parse_html(raw_bytes)
        except ParseError as exc:
            raw_html_path = save_raw_html(raw_bytes, datetime.datetime.utcnow(),
                                           base_dir=raw_html_base_dir)
            return _record_failure(session_factory, scrape_type, str(exc), raw_html_path)

        raw_html_path = save_raw_html(raw_bytes, parsed.fetched_at, base_dir=raw_html_base_dir)

        with session_factory() as session:
            try:
                snapshot = ingest_snapshot(session, parsed, scrape_type, raw_html_path)
                session.commit()
                session.refresh(snapshot)
                return snapshot
            except Exception as exc:
                session.rollback()
                return _record_failure(session_factory, scrape_type, str(exc), raw_html_path)
    finally:
        lock.release()
```

- [ ] **Step 8: 執行測試確認通過**

Run: `uv run pytest tests/scraper/test_run.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/coolpc/scraper/lock.py src/coolpc/scraper/run.py tests/scraper/test_lock.py tests/scraper/test_run.py
git commit -m "feat: scraper - 併發鎖與抓取整合流程 run_scrape"
```

---

## Task 13: 歷史 HTML 匯入

**Files:**
- Modify: `src/coolpc/scraper/run.py`
- Test: `tests/scraper/test_import.py`

**Interfaces:**
- Consumes: `parse_html, ParseError`（Task 7）；`ingest_snapshot`（Task 9）；`_record_failure`（Task 12，內部函式）
- Produces: `import_html_file(path: str, session_factory=None) -> ScrapeSnapshot`；`import_html_dir(dir_path: str, session_factory=None) -> list[ScrapeSnapshot]`。供 Task 14（CLI）、Task 23（管理介面）使用。使用 HTML 內嵌估價時間，不使用匯入當下時間。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/scraper/test_import.py
import glob
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Product
from coolpc.scraper.run import import_html_file, import_html_dir

SAMPLE_DIR = "/home/xthybot/coolpc/download"

def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

def test_import_html_file_uses_html_embedded_time():
    sf = _session_factory()
    snapshot = import_html_file(f"{SAMPLE_DIR}/2026-02-01-21-40.html", session_factory=sf)
    assert snapshot.status == "success"
    assert (snapshot.fetched_at.year, snapshot.fetched_at.month, snapshot.fetched_at.day) == (2026, 2, 1)
    assert snapshot.scrape_type == "import"
    assert snapshot.raw_html_path == f"{SAMPLE_DIR}/2026-02-01-21-40.html"

def test_import_html_dir_processes_in_chronological_order(tmp_path):
    files = sorted(glob.glob(f"{SAMPLE_DIR}/*.html"))[:3]
    for f in files:
        shutil.copy(f, tmp_path)
    sf = _session_factory()
    snapshots = import_html_dir(str(tmp_path), session_factory=sf)
    assert len(snapshots) == 3
    assert all(s.status == "success" for s in snapshots)
    fetched_times = [s.fetched_at for s in snapshots]
    assert fetched_times == sorted(fetched_times)
    with sf() as session:
        assert session.query(Product).count() > 0

def test_import_html_file_records_failure_without_losing_existing_data():
    sf = _session_factory()
    ok = import_html_file(f"{SAMPLE_DIR}/2026-02-01-21-40.html", session_factory=sf)
    assert ok.status == "success"
    with sf() as session:
        before = session.query(Product).count()

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(b"<html><body>garbage</body></html>")
        bad_path = f.name
    try:
        failed = import_html_file(bad_path, session_factory=sf)
        assert failed.status == "failed"
    finally:
        os.remove(bad_path)

    with sf() as session:
        after = session.query(Product).count()
    assert after == before
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/scraper/test_import.py -v`
Expected: FAIL，`ImportError: cannot import name 'import_html_file'`

- [ ] **Step 3: 實作**

補在 `src/coolpc/scraper/run.py` 尾端：

```python
import glob
import os


def import_html_file(path: str, session_factory: sessionmaker[Session] | None = None) -> ScrapeSnapshot:
    session_factory = session_factory or get_session_factory(get_engine())
    with open(path, "rb") as f:
        raw_bytes = f.read()
    try:
        parsed = parse_html(raw_bytes)
    except ParseError as exc:
        return _record_failure(session_factory, "import", str(exc), path)

    with session_factory() as session:
        try:
            snapshot = ingest_snapshot(session, parsed, "import", path)
            session.commit()
            session.refresh(snapshot)
            return snapshot
        except Exception as exc:
            session.rollback()
            return _record_failure(session_factory, "import", str(exc), path)


def import_html_dir(dir_path: str,
                     session_factory: sessionmaker[Session] | None = None) -> list[ScrapeSnapshot]:
    session_factory = session_factory or get_session_factory(get_engine())
    files = sorted(glob.glob(os.path.join(dir_path, "**", "*.html"), recursive=True))
    return [import_html_file(path, session_factory=session_factory) for path in files]
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/scraper/test_import.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/scraper/run.py tests/scraper/test_import.py
git commit -m "feat: scraper - 歷史 HTML 匯入（單檔/整個目錄）"
```

---

## Task 14: CLI 入口

**Files:**
- Create: `src/coolpc/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_scrape, import_html_file, import_html_dir, ScrapeSkipped`（Task 12/13）
- Produces: `main(argv=None) -> int`，註冊為 `pyproject.toml` 的 `coolpc-scraper` 指令（Task 1 已設定 `[project.scripts]`）。子指令：`scrape [--manual]`、`import-html <path>`、`import-dir <path>`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_cli.py
from coolpc.cli import main
from coolpc.db.session import get_engine
from coolpc.db.models import Base

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"


def _init_db(tmp_path, monkeypatch):
    monkeypatch.setenv("COOLPC_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.chdir(tmp_path)
    Base.metadata.create_all(get_engine())


def test_cli_import_html_success_prints_summary(tmp_path, monkeypatch, capsys):
    _init_db(tmp_path, monkeypatch)
    exit_code = main(["import-html", SAMPLE])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[success]" in out

def test_cli_import_dir(tmp_path, monkeypatch, capsys):
    import shutil
    _init_db(tmp_path, monkeypatch)
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    shutil.copy(SAMPLE, html_dir)
    exit_code = main(["import-dir", str(html_dir)])
    assert exit_code == 0
    assert "[success]" in capsys.readouterr().out

def test_cli_scrape_returns_nonzero_on_fetch_failure(tmp_path, monkeypatch, capsys):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("COOLPC_EVALUATE_URL", "http://127.0.0.1:1/nonexistent")
    exit_code = main(["scrape", "--manual"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error" in err.lower() or "錯誤" in err or "失敗" in err
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/cli.py
from __future__ import annotations
import argparse
import sys
from coolpc.scraper.run import run_scrape, import_html_file, import_html_dir, ScrapeSkipped


def _print_snapshot(snapshot) -> None:
    print(
        f"[{snapshot.status}] fetched_at={snapshot.fetched_at} "
        f"total={snapshot.total_products} new={snapshot.new_products} "
        f"delisted={snapshot.delisted_products} "
        f"up={snapshot.price_up_count} down={snapshot.price_down_count}"
    )
    if snapshot.status == "failed":
        print(f"錯誤: {snapshot.error_message}", file=sys.stderr)


def cmd_scrape(args: argparse.Namespace) -> int:
    try:
        snapshot = run_scrape(scrape_type="manual" if args.manual else "scheduled")
    except ScrapeSkipped as exc:
        print(f"錯誤: {exc}", file=sys.stderr)
        return 1
    _print_snapshot(snapshot)
    return 0 if snapshot.status == "success" else 1


def cmd_import_html(args: argparse.Namespace) -> int:
    snapshot = import_html_file(args.path)
    _print_snapshot(snapshot)
    return 0 if snapshot.status == "success" else 1


def cmd_import_dir(args: argparse.Namespace) -> int:
    snapshots = import_html_dir(args.path)
    for snapshot in snapshots:
        _print_snapshot(snapshot)
    return 0 if all(s.status == "success" for s in snapshots) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coolpc-scraper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="執行一次抓取")
    p_scrape.add_argument("--manual", action="store_true", help="標記為手動抓取")
    p_scrape.set_defaults(func=cmd_scrape)

    p_import = sub.add_parser("import-html", help="匯入單一 HTML 檔案")
    p_import.add_argument("path")
    p_import.set_defaults(func=cmd_import_html)

    p_import_dir = sub.add_parser("import-dir", help="匯入整個目錄的 HTML")
    p_import_dir.add_argument("path")
    p_import_dir.set_defaults(func=cmd_import_dir)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: 確認 console script 可執行**

```bash
uv sync
uv run coolpc-scraper --help
```

Expected: 顯示 `scrape` / `import-html` / `import-dir` 三個子指令說明。

- [ ] **Step 6: Commit**

```bash
git add src/coolpc/cli.py tests/test_cli.py
git commit -m "feat: 新增 CLI 入口（scrape/import-html/import-dir）"
```

---

## Task 15: 合併 / Undo 合併 Service

**Files:**
- Create: `src/coolpc/merging/service.py`
- Test: `tests/merging/test_merge.py`

**Interfaces:**
- Consumes: `Product, ProductName, MergeLog`（Task 2，含 Task 15 新增的 `moved_name_ids`）
- Produces: `MergeError`；`merge_products(session, source_id, target_id, now=None) -> MergeLog`；`undo_merge(session, merge_log_id) -> None`。供 Task 23（管理介面）使用。

**設計原則：** `merge_products` 只搬移 `ProductName`（改掛 `product_id`）並設定 `source.merged_into_id`；**絕不搬動或改寫 `price_history`、`current_price` 等欄位**——查詢時用 `merged_into_id` 做聯集（Task 16 實作），這樣 Undo 只需精確逆轉「搬移 ProductName」與「清空 merged_into_id」兩件事，保證不遺失任何資料。管理員應選擇「目前仍在架上、持續更新的商品」作為 `target`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/merging/test_merge.py
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.merging.service import merge_products, undo_merge, MergeError

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _setup_two_products(session):
    t = datetime.datetime(2026, 2, 1)
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()

    source = Product(category_id=cat.id, subcategory_id=sub.id,
                      current_name="ASUS RTX 5070 PRIME 12G", current_price=18990,
                      is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
    target = Product(category_id=cat.id, subcategory_id=sub.id,
                      current_name="ASUS RTX 5070 PRIME OC 12GB", current_price=19990,
                      is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
    session.add_all([source, target])
    session.flush()
    session.add_all([
        ProductName(product_id=source.id, name="ASUS RTX 5070 PRIME 12G", first_seen_at=t, last_seen_at=t),
        ProductName(product_id=target.id, name="ASUS RTX 5070 PRIME OC 12GB", first_seen_at=t, last_seen_at=t),
    ])
    session.add_all([
        PriceHistory(product_id=source.id, price=18990, status=None, badges="", scraped_at=t, snapshot_id=1),
        PriceHistory(product_id=target.id, price=19990, status=None, badges="", scraped_at=t, snapshot_id=1),
    ])
    session.commit()
    return source, target

def test_merge_reassigns_names_and_marks_source():
    session = _session()
    source, target = _setup_two_products(session)

    merge_log = merge_products(session, source.id, target.id)
    session.commit()

    session.refresh(source)
    assert source.merged_into_id == target.id

    names = session.query(ProductName).all()
    assert all(n.product_id == target.id for n in names)
    assert {n.name for n in names} == {"ASUS RTX 5070 PRIME 12G", "ASUS RTX 5070 PRIME OC 12GB"}

    # 舊名稱搜尋仍要能找到合併後商品
    hit = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one()
    assert hit.product_id == target.id

    # 歷史價格完全沒被搬動或刪除
    assert session.query(PriceHistory).filter_by(product_id=source.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=target.id).count() == 1

def test_merge_same_id_raises():
    session = _session()
    source, target = _setup_two_products(session)
    with pytest.raises(MergeError):
        merge_products(session, source.id, source.id)

def test_merge_into_already_merged_target_raises():
    session = _session()
    source, target = _setup_two_products(session)
    merge_products(session, source.id, target.id)
    session.commit()

    t = datetime.datetime(2026, 2, 2)
    third = Product(category_id=target.category_id, subcategory_id=target.subcategory_id,
                     current_name="第三個商品", current_price=100, is_active=True,
                     first_seen_at=t, last_seen_at=t, created_at=t)
    session.add(third)
    session.commit()

    with pytest.raises(MergeError):
        merge_products(session, third.id, source.id)  # source 已被合併，不可再當 target

def test_undo_merge_restores_original_state():
    session = _session()
    source, target = _setup_two_products(session)
    merge_log = merge_products(session, source.id, target.id)
    session.commit()

    undo_merge(session, merge_log.id)
    session.commit()

    session.refresh(source)
    assert source.merged_into_id is None

    source_name = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one()
    target_name = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME OC 12GB").one()
    assert source_name.product_id == source.id
    assert target_name.product_id == target.id

    assert session.query(PriceHistory).filter_by(product_id=source.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=target.id).count() == 1

def test_undo_already_undone_raises():
    session = _session()
    source, target = _setup_two_products(session)
    merge_log = merge_products(session, source.id, target.id)
    session.commit()
    undo_merge(session, merge_log.id)
    session.commit()
    with pytest.raises(MergeError):
        undo_merge(session, merge_log.id)

def test_undo_with_multiple_names_only_restores_moved_ones():
    """target 原本就有自己的名稱，undo 後不能誤把 target 自己的名稱也搬走。"""
    session = _session()
    source, target = _setup_two_products(session)
    t = datetime.datetime(2026, 2, 3)
    # target 之後又多了一個新曾用名（模擬合併後 target 自己又改名一次）
    session.add(ProductName(product_id=target.id, name="ASUS RTX 5070 PRIME OC 12GB V2",
                             first_seen_at=t, last_seen_at=t))
    session.commit()

    merge_log = merge_products(session, source.id, target.id)
    session.commit()
    undo_merge(session, merge_log.id)
    session.commit()

    assert session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME OC 12GB V2").one().product_id == target.id
    assert session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one().product_id == source.id
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/merging/test_merge.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/merging/service.py
from __future__ import annotations
import datetime
import json
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName, MergeLog


class MergeError(Exception):
    pass


def merge_products(session: Session, source_id: int, target_id: int,
                    now: datetime.datetime | None = None) -> MergeLog:
    now = now or datetime.datetime.utcnow()
    if source_id == target_id:
        raise MergeError("來源與目標商品不可相同")

    source = session.get(Product, source_id)
    target = session.get(Product, target_id)
    if source is None or target is None:
        raise MergeError("來源或目標商品不存在")
    if source.merged_into_id is not None:
        raise MergeError("來源商品已被合併過，請先 Undo 再重新合併")
    if target.merged_into_id is not None:
        raise MergeError("目標商品本身已被合併到其他商品，請改選最終商品作為目標")

    names = session.query(ProductName).filter_by(product_id=source.id).all()
    moved_ids = [n.id for n in names]
    for n in names:
        n.product_id = target.id

    source.merged_into_id = target.id

    merge_log = MergeLog(
        source_product_id=source.id, target_product_id=target.id,
        merged_at=now, moved_name_ids=json.dumps(moved_ids),
    )
    session.add(merge_log)
    session.flush()
    return merge_log


def undo_merge(session: Session, merge_log_id: int) -> None:
    merge_log = session.get(MergeLog, merge_log_id)
    if merge_log is None:
        raise MergeError("找不到合併紀錄")
    if merge_log.undone_at is not None:
        raise MergeError("此合併已經被 Undo 過")

    source = session.get(Product, merge_log.source_product_id)
    if source is None or source.merged_into_id != merge_log.target_product_id:
        raise MergeError("合併狀態異常，無法 Undo")

    moved_ids = json.loads(merge_log.moved_name_ids)
    if moved_ids:
        session.query(ProductName).filter(ProductName.id.in_(moved_ids)).update(
            {"product_id": source.id}, synchronize_session=False
        )
    source.merged_into_id = None
    merge_log.undone_at = datetime.datetime.utcnow()
    session.flush()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/merging/test_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/merging && touch tests/merging/__init__.py
git add src/coolpc/merging/ tests/merging/
git commit -m "feat: merging - 商品合併與 Undo 合併"
```

---

## Task 16: Stats Service — 價格統計計算

**Files:**
- Create: `src/coolpc/stats/service.py`
- Test: `tests/stats/test_stats.py`

**Interfaces:**
- Consumes: `Product, PriceHistory`（Task 2）
- Produces: `ProductStats` dataclass；`get_merged_group_product_ids(session, product_id) -> list[int]`；`get_price_history(session, product_id, start=None, end=None) -> list[PriceHistory]`；`compute_product_stats(session, product_id, now=None) -> ProductStats`。供 Task 18（`/api/products/{id}/stats`、`/prices`）、Task 19（列表頁漲跌顯示）、Task 21（比較頁）使用。**這是唯一計算統計的地方**，所有頁面/API 共用，確保合併商品的歷史價格聯集邏輯只實作一次。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/stats/test_stats.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, PriceHistory
from coolpc.stats.service import compute_product_stats, get_price_history

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _make_product(session, cat, sub, name, price, t):
    p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                current_price=price, is_active=True, first_seen_at=t,
                last_seen_at=t, created_at=t)
    session.add(p)
    session.flush()
    return p

def test_compute_product_stats_change_and_ranges():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    p = _make_product(session, cat, sub, "商品A", 9000, now)

    prices = [
        (now - datetime.timedelta(days=95), 10000),
        (now - datetime.timedelta(days=40), 8000),
        (now - datetime.timedelta(days=10), 9500),
        (now - datetime.timedelta(days=1), 8500),
        (now, 9000),
    ]
    for i, (t, price) in enumerate(prices):
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=i))
    session.commit()

    stats = compute_product_stats(session, p.id, now=now)
    assert stats.current_price == 9000
    assert stats.previous_price == 8500
    assert stats.change_amount == 500
    assert round(stats.change_percent, 2) == round(500 / 8500 * 100, 2)
    assert (stats.low_7d, stats.high_7d) == (8500, 9000)
    assert (stats.low_30d, stats.high_30d) == (8500, 9500)
    assert (stats.low_90d, stats.high_90d) == (8000, 9500)
    assert stats.all_time_low == 8000
    assert stats.all_time_high == 10000

def test_compute_product_stats_first_seen_has_no_previous_price():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    p = _make_product(session, cat, sub, "商品B", 5000, now)
    session.add(PriceHistory(product_id=p.id, price=5000, status=None, badges="",
                              scraped_at=now, snapshot_id=1))
    session.commit()

    stats = compute_product_stats(session, p.id, now=now)
    assert stats.previous_price is None
    assert stats.change_amount is None
    assert stats.all_time_low == 5000
    assert stats.all_time_high == 5000

def test_compute_product_stats_includes_merged_source_history():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    source = _make_product(session, cat, sub, "舊名", 7000, now - datetime.timedelta(days=5))
    target = _make_product(session, cat, sub, "新名", 9000, now)
    session.add(PriceHistory(product_id=source.id, price=7000, status=None, badges="",
                              scraped_at=now - datetime.timedelta(days=5), snapshot_id=1))
    session.add(PriceHistory(product_id=target.id, price=9000, status=None, badges="",
                              scraped_at=now, snapshot_id=2))
    session.commit()
    source.merged_into_id = target.id
    session.commit()

    stats = compute_product_stats(session, target.id, now=now)
    assert stats.all_time_low == 7000
    assert stats.all_time_high == 9000

    history = get_price_history(session, target.id)
    assert len(history) == 2
    assert {h.product_id for h in history} == {source.id, target.id}
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/stats/test_stats.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/stats/service.py
from __future__ import annotations
import datetime
from dataclasses import dataclass
from sqlalchemy import func
from sqlalchemy.orm import Session
from coolpc.db.models import Product, PriceHistory


@dataclass
class ProductStats:
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_7d: int | None
    high_7d: int | None
    low_30d: int | None
    high_30d: int | None
    low_90d: int | None
    high_90d: int | None
    all_time_low: int
    all_time_high: int


def get_merged_group_product_ids(session: Session, product_id: int) -> list[int]:
    source_ids = [
        row[0] for row in
        session.query(Product.id).filter(Product.merged_into_id == product_id).all()
    ]
    return [product_id, *source_ids]


def get_price_history(
    session: Session, product_id: int,
    start: datetime.datetime | None = None, end: datetime.datetime | None = None,
) -> list[PriceHistory]:
    group_ids = get_merged_group_product_ids(session, product_id)
    query = session.query(PriceHistory).filter(PriceHistory.product_id.in_(group_ids))
    if start is not None:
        query = query.filter(PriceHistory.scraped_at >= start)
    if end is not None:
        query = query.filter(PriceHistory.scraped_at <= end)
    return query.order_by(PriceHistory.scraped_at.asc()).all()


def _min_max(session: Session, group_ids: list[int],
             since: datetime.datetime | None) -> tuple[int | None, int | None]:
    query = session.query(func.min(PriceHistory.price), func.max(PriceHistory.price)).filter(
        PriceHistory.product_id.in_(group_ids)
    )
    if since is not None:
        query = query.filter(PriceHistory.scraped_at >= since)
    return query.one()


def compute_product_stats(session: Session, product_id: int,
                           now: datetime.datetime | None = None) -> ProductStats:
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"商品不存在: {product_id}")
    now = now or datetime.datetime.utcnow()
    group_ids = get_merged_group_product_ids(session, product_id)

    recent = (
        session.query(PriceHistory)
        .filter(PriceHistory.product_id.in_(group_ids))
        .order_by(PriceHistory.scraped_at.desc())
        .limit(2)
        .all()
    )
    previous_price = recent[1].price if len(recent) > 1 else None
    change_amount = None
    change_percent = None
    if previous_price is not None:
        change_amount = product.current_price - previous_price
        change_percent = (change_amount / previous_price * 100) if previous_price else None

    low_7d, high_7d = _min_max(session, group_ids, now - datetime.timedelta(days=7))
    low_30d, high_30d = _min_max(session, group_ids, now - datetime.timedelta(days=30))
    low_90d, high_90d = _min_max(session, group_ids, now - datetime.timedelta(days=90))
    all_time_low, all_time_high = _min_max(session, group_ids, None)

    return ProductStats(
        current_price=product.current_price, previous_price=previous_price,
        change_amount=change_amount, change_percent=change_percent,
        low_7d=low_7d, high_7d=high_7d, low_30d=low_30d, high_30d=high_30d,
        low_90d=low_90d, high_90d=high_90d,
        all_time_low=all_time_low if all_time_low is not None else product.current_price,
        all_time_high=all_time_high if all_time_high is not None else product.current_price,
    )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/stats/test_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/stats && touch tests/stats/__init__.py
git add src/coolpc/stats/ tests/stats/
git commit -m "feat: stats - 價格統計計算（含合併商品聯集）"
```

---

## Task 17: Search Service — 搜尋/篩選（公開與管理共用）

**Files:**
- Create: `src/coolpc/search/__init__.py`
- Create: `src/coolpc/search/service.py`
- Test: `tests/search/test_search.py`

**Interfaces:**
- Consumes: `Product, ProductName`（Task 2）
- Produces: `SearchFilters` dataclass（`q, category_id, subcategory_id, brand, min_price, max_price, is_active, recent_change, min_change_percent, max_change_percent, sort, limit, offset`）；`search_products(session, filters: SearchFilters) -> tuple[list[Product], int]`（商品清單, 總筆數）。供 Task 18（`/api/products`）、Task 23（管理介面商品搜尋）使用。

**設計變更說明（取代原先以 FTS5 做關鍵字搜尋的設計）：** Task 4 建立 `products_fts` 時發現 SQLite FTS5 內建 tokenizer（`unicode61`／`trigram`）都無法正確處理任意長度的中文子字串查詢（`unicode61` 會把連續中文字黏成一個 token；`trigram` 要求查詢字串至少 3 字），Task 4 為了讓自己的測試（2 字中文查詢）通過而改用 2-gram 索引，但這代表「查詢端」若要沿用 `MATCH`，還需要對查詢字串做對應的 bigram 切分才能正確比對 3 字以上的中文詞——這已超出原計畫範圍。改用 `ProductName.name LIKE '%'||q||'%'` 直接做子字串查詢：對這個系統的資料量級（數千到數萬筆商品名稱）而言，即使 `LIKE '%...%'` 無法用到索引、需要全表掃描，效能仍然足夠（毫秒等級），且對中英文查詢（任意長度）都保證正確，不必處理 tokenizer 的邊界案例。`products_fts` 虛擬表本身維持已完成、已測試的狀態留在資料庫中（Task 4 的工作不需要撤銷），只是本任務起不再依賴它做搜尋。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/search/test_search.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _add(session, cat, sub, name, price, is_active, t, brand=None, model=None, last_change_amount=None):
    p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name, brand=brand,
                model=model, current_price=price, is_active=is_active, first_seen_at=t,
                last_seen_at=t, created_at=t, last_change_amount=last_change_amount)
    session.add(p)
    session.flush()
    session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
    return p

def test_search_by_keyword_matches_two_char_chinese_substring():
    session = _session()
    cat = Category(name="固態硬碟")
    sub = Subcategory(name="NAS碟", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "Synology HAT3300 4TB【限搭NAS主機】", 6890, True, t)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(q="限搭"))
    assert total == 1
    assert results[0].current_name.startswith("Synology")

def test_search_by_keyword_matches_three_plus_char_chinese_phrase():
    """驗證 Task 4 的 FTS5 bigram 限制（僅支援 2 字查詢）不會影響本服務——
    LIKE 子字串比對對任意長度中文詞都要正確。"""
    session = _session()
    cat = Category(name="固態硬碟")
    sub = Subcategory(name="NAS碟", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "Synology HAT3300 4TB【限搭NAS主機】", 6890, True, t)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(q="限搭NAS主機"))
    assert total == 1
    assert results[0].current_name.startswith("Synology")

def test_search_by_keyword_matches_old_name():
    """舊名稱搜尋：查詢字串比對 product_names 全部歷史名稱，不只 current_name。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    p = _add(session, cat, sub, "ASUS RTX 5070 PRIME OC 12GB", 19990, True, t)
    session.add(ProductName(product_id=p.id, name="ASUS RTX 5070 PRIME 12G", first_seen_at=t, last_seen_at=t))
    session.commit()

    results, total = search_products(session, SearchFilters(q="ASUS RTX 5070 PRIME 12G"))
    assert total == 1
    assert results[0].id == p.id

def test_search_by_price_range_and_category():
    session = _session()
    cat1 = Category(name="顯示卡VGA")
    cat2 = Category(name="固態硬碟")
    sub1 = Subcategory(name="NVIDIA", category=cat1)
    sub2 = Subcategory(name="NAS碟", category=cat2)
    session.add_all([cat1, cat2, sub1, sub2])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat1, sub1, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat1, sub1, "微星 RTX3050 VENTUS 2X E 6G OC", 7990, True, t)
    _add(session, cat2, sub2, "Synology HAT3300 4TB", 6890, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(
        category_id=cat1.id, min_price=10000,
    ))
    assert total == 1
    assert results[0].current_name.startswith("ASUS")

def test_search_by_model_substring():
    session = _session()
    cat = Category(name="品牌小主機、AIO｜VR虛擬")
    sub = Subcategory(name="ASUS", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS【H-V500MV-31315U042W】i3-1315U", 13990, True, t,
         model="H-V500MV-31315U042W")
    _add(session, cat, sub, "ASUS【H-S503MER-714700001X】i7-14700", 33990, True, t,
         model="H-S503MER-714700001X")
    session.commit()

    results, total = search_products(session, SearchFilters(model="H-V500MV"))
    assert total == 1
    assert results[0].model == "H-V500MV-31315U042W"

def test_search_excludes_merged_away_products():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    source = _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, False, t)
    target = _add(session, cat, sub, "ASUS RTX 5070 PRIME OC 12GB", 19990, True, t)
    session.commit()
    source.merged_into_id = target.id
    session.commit()

    results, total = search_products(session, SearchFilters())
    assert total == 1
    assert results[0].id == target.id

def test_search_filters_recent_price_up():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "漲價商品", 9000, True, t, last_change_amount=500)
    _add(session, cat, sub, "降價商品", 9000, True, t, last_change_amount=-300)
    session.commit()

    up, up_total = search_products(session, SearchFilters(recent_change="up"))
    down, down_total = search_products(session, SearchFilters(recent_change="down"))
    assert up_total == 1 and up[0].current_name == "漲價商品"
    assert down_total == 1 and down[0].current_name == "降價商品"

def test_search_pagination():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    for i in range(5):
        _add(session, cat, sub, f"商品{i}", 1000 + i, True, t)
    session.commit()

    page1, total = search_products(session, SearchFilters(limit=2, offset=0, sort="name_asc"))
    page2, _ = search_products(session, SearchFilters(limit=2, offset=2, sort="name_asc"))
    assert total == 5
    assert len(page1) == 2 and len(page2) == 2
    assert {p.id for p in page1}.isdisjoint({p.id for p in page2})
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/search/test_search.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/search/service.py
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName


@dataclass
class SearchFilters:
    q: str | None = None
    category_id: int | None = None
    subcategory_id: int | None = None
    brand: str | None = None
    model: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    is_active: bool | None = None
    recent_change: str | None = None  # "up" | "down" | None
    min_change_percent: float | None = None
    max_change_percent: float | None = None
    sort: str = "last_seen_desc"
    limit: int = 50
    offset: int = 0


_SORT_MAP = {
    "last_seen_desc": Product.last_seen_at.desc(),
    "price_asc": Product.current_price.asc(),
    "price_desc": Product.current_price.desc(),
    "name_asc": Product.current_name.asc(),
}


def search_products(session: Session, filters: SearchFilters) -> tuple[list[Product], int]:
    query = session.query(Product).filter(Product.merged_into_id.is_(None))

    if filters.q:
        matched_ids = [
            row[0] for row in
            session.query(ProductName.product_id)
            .filter(ProductName.name.like(f"%{filters.q}%"))
            .distinct()
            .all()
        ]
        if not matched_ids:
            return [], 0
        query = query.filter(Product.id.in_(matched_ids))

    if filters.category_id is not None:
        query = query.filter(Product.category_id == filters.category_id)
    if filters.subcategory_id is not None:
        query = query.filter(Product.subcategory_id == filters.subcategory_id)
    if filters.brand:
        query = query.filter(Product.brand == filters.brand)
    if filters.model:
        query = query.filter(Product.model.like(f"%{filters.model}%"))
    if filters.min_price is not None:
        query = query.filter(Product.current_price >= filters.min_price)
    if filters.max_price is not None:
        query = query.filter(Product.current_price <= filters.max_price)
    if filters.is_active is not None:
        query = query.filter(Product.is_active == filters.is_active)
    if filters.recent_change == "up":
        query = query.filter(Product.last_change_amount > 0)
    elif filters.recent_change == "down":
        query = query.filter(Product.last_change_amount < 0)
    if filters.min_change_percent is not None:
        query = query.filter(Product.last_change_percent >= filters.min_change_percent)
    if filters.max_change_percent is not None:
        query = query.filter(Product.last_change_percent <= filters.max_change_percent)

    total = query.count()
    query = query.order_by(_SORT_MAP.get(filters.sort, Product.last_seen_at.desc()))
    query = query.offset(filters.offset).limit(filters.limit)
    return query.all(), total
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/search/test_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p tests/search && touch tests/search/__init__.py
git add src/coolpc/search/ tests/search/
git commit -m "feat: search - 商品搜尋/篩選服務（公開與管理共用）"
```

---

## Task 18: Public API — App 骨架 + `/api/categories` + `/api/products`

**Files:**
- Create: `src/coolpc/public_api/__init__.py`（已於 Task 1 建立空檔）
- Create: `src/coolpc/public_api/dependencies.py`
- Create: `src/coolpc/public_api/schemas.py`
- Create: `src/coolpc/public_api/routers/__init__.py`
- Create: `src/coolpc/public_api/routers/api.py`
- Create: `src/coolpc/public_api/app.py`
- Test: `tests/public_api/test_products_api.py`

**Interfaces:**
- Consumes: `get_engine, get_session_factory`（Task 3）；`Category, Subcategory, Product`（Task 2）；`SearchFilters, search_products`（Task 17）；`compute_product_stats`（Task 16）
- Produces: `get_session()`（FastAPI dependency，供全部 public_api 路由使用）；`app`（FastAPI instance，Task 20 起繼續掛路由，Task 27 systemd 用 `uvicorn coolpc.public_api.app:app` 啟動）；Pydantic schemas `CategoryOut, ProductListItem, ProductListPage`（供 Task 19 沿用相同風格）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_products_api.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_list_categories_returns_seeded_categories():
    client, Session_ = _make_client()
    with Session_() as session:
        session.add(Category(name="顯示卡VGA"))
        session.commit()

    resp = client.get("/api/categories")
    assert resp.status_code == 200
    assert any(c["name"] == "顯示卡VGA" for c in resp.json())


def _seed_product(Session_, name, price, category_name="顯示卡VGA", subcategory_name="NVIDIA"):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = session.query(Category).filter_by(name=category_name).one_or_none() or Category(name=category_name)
        session.add(cat)
        session.flush()
        sub = Subcategory(name=subcategory_name, category=cat)
        session.add(sub)
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                    current_price=price, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()
        return p.id


def test_list_products_returns_items_with_stats():
    client, Session_ = _make_client()
    _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)

    resp = client.get("/api/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"] == "ASUS RTX 5070 PRIME 12G"
    assert data["items"][0]["current_price"] == 18990
    assert data["items"][0]["is_active"] is True


def test_list_products_filters_by_fts_query():
    client, Session_ = _make_client()
    _seed_product(Session_, "Synology HAT3300 4TB【限搭NAS主機】", 6890,
                   category_name="固態硬碟", subcategory_name="NAS碟")
    _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)

    resp = client.get("/api/products", params={"q": "限搭"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"].startswith("Synology")


def test_list_products_filters_by_category_and_price():
    client, Session_ = _make_client()
    vga_id = _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)
    _seed_product(Session_, "微星 RTX3050 VENTUS 2X E 6G OC", 7990)

    with Session_() as session:
        vga_cat_id = session.get(Product, vga_id).category_id

    resp = client.get("/api/products", params={"category_id": vga_cat_id, "min_price": 10000})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"].startswith("ASUS")


def test_list_products_filters_by_change_percent_range():
    client, Session_ = _make_client()
    with Session_() as session:
        t = datetime.datetime(2026, 2, 1)
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        big_jump = Product(category_id=cat.id, subcategory_id=sub.id, current_name="漲很多",
                           current_price=1100, last_change_amount=100, last_change_percent=10.0,
                           is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        small_jump = Product(category_id=cat.id, subcategory_id=sub.id, current_name="漲一點點",
                             current_price=1010, last_change_amount=10, last_change_percent=1.0,
                             is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([big_jump, small_jump])
        session.commit()

    resp = client.get("/api/products", params={"min_change_percent": 5})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"] == "漲很多"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_products_api.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/public_api/dependencies.py
from __future__ import annotations
from collections.abc import Iterator
from sqlalchemy.orm import Session
from coolpc.db.session import get_engine, get_session_factory

_session_factory = None


def get_session() -> Iterator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory(get_engine())
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
```

```python
# src/coolpc/public_api/schemas.py
from __future__ import annotations
import datetime
from pydantic import BaseModel


class CategoryOut(BaseModel):
    id: int
    name: str


class SubcategoryOut(BaseModel):
    id: int
    name: str
    category_id: int


class ProductListItem(BaseModel):
    id: int
    current_name: str
    category_name: str
    subcategory_name: str
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_30d: int | None
    high_30d: int | None
    is_active: bool
    last_seen_at: datetime.datetime


class ProductListPage(BaseModel):
    items: list[ProductListItem]
    total: int
    limit: int
    offset: int
```

```python
# src/coolpc/public_api/routers/api.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session
from coolpc.public_api import schemas
from coolpc.db.models import Category, Subcategory, Product
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats

router = APIRouter(prefix="/api")


@router.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(session: Session = Depends(get_session)):
    categories = session.query(Category).order_by(Category.id).all()
    return [schemas.CategoryOut(id=c.id, name=c.name) for c in categories]


def _to_list_item(session: Session, product: Product) -> schemas.ProductListItem:
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    return schemas.ProductListItem(
        id=product.id, current_name=product.current_name,
        category_name=category.name, subcategory_name=subcategory.name,
        current_price=product.current_price, previous_price=stats.previous_price,
        change_amount=stats.change_amount, change_percent=stats.change_percent,
        low_30d=stats.low_30d, high_30d=stats.high_30d,
        is_active=product.is_active, last_seen_at=product.last_seen_at,
    )


@router.get("/products", response_model=schemas.ProductListPage)
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    brand: str | None = None,
    model: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    is_active: bool | None = None,
    recent_change: str | None = None,
    min_change_percent: float | None = None,
    max_change_percent: float | None = None,
    sort: str = "last_seen_desc",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    filters = SearchFilters(
        q=q, category_id=category_id, subcategory_id=subcategory_id, brand=brand, model=model,
        min_price=min_price, max_price=max_price, is_active=is_active,
        recent_change=recent_change, min_change_percent=min_change_percent,
        max_change_percent=max_change_percent, sort=sort, limit=limit, offset=offset,
    )
    products, total = search_products(session, filters)
    items = [_to_list_item(session, p) for p in products]
    return schemas.ProductListPage(items=items, total=total, limit=limit, offset=offset)
```

```python
# src/coolpc/public_api/app.py
from __future__ import annotations
from fastapi import FastAPI
from coolpc.public_api.routers import api as api_router

app = FastAPI(title="原價屋歷史價格查詢")
app.include_router(api_router.router)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_products_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p src/coolpc/public_api/routers tests/public_api
touch src/coolpc/public_api/routers/__init__.py tests/public_api/__init__.py
git add src/coolpc/public_api/ tests/public_api/
git commit -m "feat: public_api - app 骨架、/api/categories、/api/products"
```

---

## Task 19: Public API — 商品詳細 / 歷史價格 / 統計

**Files:**
- Modify: `src/coolpc/public_api/schemas.py`
- Modify: `src/coolpc/public_api/routers/api.py`
- Test: `tests/public_api/test_product_detail_api.py`

**Interfaces:**
- Consumes: `compute_product_stats, get_price_history`（Task 16）；`ProductName`（Task 2）
- Produces: `schemas.ProductStatsOut, schemas.ProductDetail, schemas.PricePoint`；`GET /api/products/{id}`、`GET /api/products/{id}/prices?start&end&days`、`GET /api/products/{id}/stats`。供 Task 22（商品詳細頁）沿用同一批 schema。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_product_detail_api.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_get_product_detail_includes_historical_names_and_stats():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 v2",
                    current_price=19990, is_active=True, first_seen_at=t0, last_seen_at=t1, created_at=t0)
        session.add(p)
        session.flush()
        session.add_all([
            ProductName(product_id=p.id, name="ASUS RTX 5070", first_seen_at=t0, last_seen_at=t0),
            ProductName(product_id=p.id, name="ASUS RTX 5070 v2", first_seen_at=t1, last_seen_at=t1),
        ])
        session.add_all([
            PriceHistory(product_id=p.id, price=18990, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=p.id, price=19990, status=None, badges="", scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        pid = p.id

    resp = client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_name"] == "ASUS RTX 5070 v2"
    assert set(data["historical_names"]) == {"ASUS RTX 5070", "ASUS RTX 5070 v2"}
    assert data["change_amount"] == 1000
    assert data["stats"]["all_time_low"] == 18990


def test_get_product_detail_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/api/products/999")
    assert resp.status_code == 404


def test_get_product_prices_returns_ordered_series():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="X",
                    current_price=200, is_active=True, first_seen_at=t0, last_seen_at=t1, created_at=t0)
        session.add(p)
        session.flush()
        session.add_all([
            PriceHistory(product_id=p.id, price=100, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=p.id, price=200, status=None, badges="", scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        pid = p.id

    resp = client.get(f"/api/products/{pid}/prices")
    data = resp.json()
    assert len(data) == 2
    assert data[0]["price"] == 100
    assert data[1]["price"] == 200


def test_get_product_stats_endpoint():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="X",
                    current_price=500, is_active=True, first_seen_at=t0, last_seen_at=t0, created_at=t0)
        session.add(p)
        session.flush()
        session.add(PriceHistory(product_id=p.id, price=500, status=None, badges="",
                                  scraped_at=t0, snapshot_id=1))
        session.commit()
        pid = p.id

    resp = client.get(f"/api/products/{pid}/stats")
    assert resp.status_code == 200
    assert resp.json()["all_time_low"] == 500
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_product_detail_api.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

補在 `src/coolpc/public_api/schemas.py` 尾端：

```python
class ProductStatsOut(BaseModel):
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_7d: int | None
    high_7d: int | None
    low_30d: int | None
    high_30d: int | None
    low_90d: int | None
    high_90d: int | None
    all_time_low: int
    all_time_high: int


class ProductDetail(BaseModel):
    id: int
    current_name: str
    historical_names: list[str]
    category_name: str
    subcategory_name: str
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    is_active: bool
    stats: ProductStatsOut


class PricePoint(BaseModel):
    scraped_at: datetime.datetime
    price: int
```

補在 `src/coolpc/public_api/routers/api.py` 尾端（並在檔案頂端加入新的 import）：

```python
import datetime as dt
from fastapi import HTTPException
from coolpc.db.models import ProductName
from coolpc.stats.service import get_price_history


@router.get("/products/{product_id}", response_model=schemas.ProductDetail)
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if product is None or product.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="商品不存在")
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    names = [
        n.name for n in
        session.query(ProductName).filter_by(product_id=product.id)
        .order_by(ProductName.first_seen_at).all()
    ]
    return schemas.ProductDetail(
        id=product.id, current_name=product.current_name, historical_names=names,
        category_name=category.name, subcategory_name=subcategory.name,
        current_price=product.current_price, previous_price=stats.previous_price,
        change_amount=stats.change_amount, change_percent=stats.change_percent,
        first_seen_at=product.first_seen_at, last_seen_at=product.last_seen_at,
        is_active=product.is_active,
        stats=schemas.ProductStatsOut(**stats.__dict__),
    )


@router.get("/products/{product_id}/prices", response_model=list[schemas.PricePoint])
def get_product_prices(
    product_id: int,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    days: int | None = None,
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    effective_start = start
    if days is not None and start is None:
        effective_start = dt.datetime.utcnow() - dt.timedelta(days=days)
    history = get_price_history(session, product_id, start=effective_start, end=end)
    return [schemas.PricePoint(scraped_at=h.scraped_at, price=h.price) for h in history]


@router.get("/products/{product_id}/stats", response_model=schemas.ProductStatsOut)
def get_product_stats(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    stats = compute_product_stats(session, product_id)
    return schemas.ProductStatsOut(**stats.__dict__)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_product_detail_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/public_api/schemas.py src/coolpc/public_api/routers/api.py tests/public_api/test_product_detail_api.py
git commit -m "feat: public_api - 商品詳細/歷史價格/統計端點"
```

---

## Task 20: Public API — `/api/compare`

**Files:**
- Modify: `src/coolpc/public_api/schemas.py`
- Modify: `src/coolpc/public_api/routers/api.py`
- Test: `tests/public_api/test_compare_api.py`

**Interfaces:**
- Consumes: `compute_product_stats, get_price_history`（Task 16）
- Produces: `schemas.CompareItem, schemas.ComparePricePoint, schemas.CompareResult`；`GET /api/compare?ids=1,2,3`（2–5 個商品，`ids` 為逗號分隔字串）。供 Task 23（比較頁前端）使用。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_compare_api.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def _seed(Session_, name, price, t):
    with Session_() as session:
        cat = session.query(Category).filter_by(name="顯示卡VGA").one_or_none() or Category(name="顯示卡VGA")
        session.add(cat)
        session.flush()
        sub = session.query(Subcategory).filter_by(category_id=cat.id, name="NVIDIA").one_or_none()
        if sub is None:
            sub = Subcategory(name="NVIDIA", category=cat)
            session.add(sub)
            session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                    current_price=price, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()
        return p.id


def test_compare_rejects_too_few_ids():
    client, Session_ = _make_client()
    pid = _seed(Session_, "A", 100, datetime.datetime(2026, 2, 1))
    resp = client.get("/api/compare", params={"ids": str(pid)})
    assert resp.status_code == 400


def test_compare_rejects_too_many_ids():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    ids = [_seed(Session_, f"P{i}", 100 + i, t) for i in range(6)]
    resp = client.get("/api/compare", params={"ids": ",".join(str(i) for i in ids)})
    assert resp.status_code == 400


def test_compare_returns_items_and_series():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    id1 = _seed(Session_, "ASUS RTX 5070 PRIME 12G", 18990, t)
    id2 = _seed(Session_, "微星 RTX3050 VENTUS 2X E 6G OC", 7990, t)

    resp = client.get("/api/compare", params={"ids": f"{id1},{id2}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert {i["id"] for i in data["items"]} == {id1, id2}
    assert len(data["series"]) == 2


def test_compare_404_when_product_missing():
    client, Session_ = _make_client()
    pid = _seed(Session_, "A", 100, datetime.datetime(2026, 2, 1))
    resp = client.get("/api/compare", params={"ids": f"{pid},99999"})
    assert resp.status_code == 404
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_compare_api.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

補在 `src/coolpc/public_api/schemas.py` 尾端：

```python
class CompareItem(BaseModel):
    id: int
    current_name: str
    current_price: int
    low_7d: int | None
    low_30d: int | None
    high_30d: int | None
    all_time_low: int
    all_time_high: int
    change_amount: int | None
    change_percent: float | None


class ComparePricePoint(BaseModel):
    product_id: int
    scraped_at: datetime.datetime
    price: int


class CompareResult(BaseModel):
    items: list[CompareItem]
    series: list[ComparePricePoint]
```

補在 `src/coolpc/public_api/routers/api.py` 尾端：

```python
@router.get("/compare", response_model=schemas.CompareResult)
def compare_products(ids: str, session: Session = Depends(get_session)):
    try:
        product_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 格式錯誤，需為逗號分隔的整數")
    if not (2 <= len(product_ids) <= 5):
        raise HTTPException(status_code=400, detail="比較商品數量需介於 2 到 5 個之間")

    items: list[schemas.CompareItem] = []
    series: list[schemas.ComparePricePoint] = []
    for pid in product_ids:
        product = session.get(Product, pid)
        if product is None or product.merged_into_id is not None:
            raise HTTPException(status_code=404, detail=f"商品不存在: {pid}")
        stats = compute_product_stats(session, pid)
        items.append(schemas.CompareItem(
            id=product.id, current_name=product.current_name, current_price=product.current_price,
            low_7d=stats.low_7d, low_30d=stats.low_30d, high_30d=stats.high_30d,
            all_time_low=stats.all_time_low, all_time_high=stats.all_time_high,
            change_amount=stats.change_amount, change_percent=stats.change_percent,
        ))
        for h in get_price_history(session, pid):
            series.append(schemas.ComparePricePoint(product_id=pid, scraped_at=h.scraped_at, price=h.price))

    return schemas.CompareResult(items=items, series=series)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_compare_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/public_api/schemas.py src/coolpc/public_api/routers/api.py tests/public_api/test_compare_api.py
git commit -m "feat: public_api - /api/compare 商品比較端點"
```

---

## Task 21: 公開前端 — Base Template + 搜尋/列表頁

**Files:**
- Create: `src/coolpc/public_api/templates/base.html`
- Create: `src/coolpc/public_api/templates/search.html`
- Create: `src/coolpc/public_api/routers/pages.py`
- Modify: `src/coolpc/public_api/app.py`
- Test: `tests/public_api/test_search_page.py`

**Interfaces:**
- Consumes: `SearchFilters, search_products`（Task 17）；`compute_product_stats`（Task 16）；`Category, Subcategory`（Task 2）
- Produces: `GET /`（搜尋+列表頁，`templates/base.html` 供 Task 22/23 的頁面 extend）。修改 `app.py` 掛載 Jinja2Templates 與 `pages` router。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_search_page.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_search_page_renders_seeded_product():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                    current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=18990, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "顯示卡VGA" in resp.text
    assert "18,990" in resp.text


def test_search_page_pagination_link_preserves_query():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        for i in range(35):
            name = f"ASUS 商品{i}"
            p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                        current_price=1000 + i, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/", params={"sort": "price_desc", "page": 1})
    assert resp.status_code == 200
    assert "sort=price_desc" in resp.text
    assert "page=2" in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_search_page.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

```html
<!-- src/coolpc/public_api/templates/base.html -->
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}原價屋歷史價格查詢{% endblock %}</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", "微軟正黑體", sans-serif; margin: 0; background: #f7f7f8; color: #1a1a1a; }
    header { background: #1f2937; color: #fff; padding: 12px 20px; display: flex; gap: 20px; align-items: center; }
    header a { color: #fff; text-decoration: none; font-weight: 600; }
    main { max-width: 1100px; margin: 20px auto; padding: 0 16px; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 14px; }
    th { background: #f1f5f9; }
    .up { color: #b91c1c; }
    .down { color: #15803d; }
    .inactive { color: #9ca3af; }
    form.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; background: #fff; padding: 12px; border-radius: 6px; }
    form.filters input, form.filters select { padding: 6px; }
    .pagination { margin-top: 16px; display: flex; gap: 8px; align-items: center; }
    a { color: #2563eb; }
  </style>
</head>
<body>
<header>
  <a href="/">商品搜尋</a>
  <a href="/compare">商品比較</a>
</header>
<main>
{% block content %}{% endblock %}
</main>
</body>
</html>
```

```html
<!-- src/coolpc/public_api/templates/search.html -->
{% extends "base.html" %}
{% block title %}商品搜尋 - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<form class="filters" method="get" action="/">
  <input type="text" name="q" placeholder="搜尋商品名稱/舊名稱/關鍵字" value="{{ query.q }}">
  <select name="category_id">
    <option value="">全部分類</option>
    {% for c in categories %}
    <option value="{{ c.id }}" {% if query.category_id == c.id %}selected{% endif %}>{{ c.name }}</option>
    {% endfor %}
  </select>
  <input type="text" name="brand" placeholder="品牌" value="{{ query.brand or '' }}">
  <input type="text" name="model" placeholder="型號" value="{{ query.model or '' }}">
  <input type="number" name="min_price" placeholder="最低價格" value="{{ query.min_price or '' }}">
  <input type="number" name="max_price" placeholder="最高價格" value="{{ query.max_price or '' }}">
  <select name="is_active">
    <option value="">在售/下架</option>
    <option value="true" {% if query.is_active == True %}selected{% endif %}>僅在售</option>
    <option value="false" {% if query.is_active == False %}selected{% endif %}>僅下架</option>
  </select>
  <select name="recent_change">
    <option value="">漲跌</option>
    <option value="up" {% if query.recent_change == "up" %}selected{% endif %}>最近漲價</option>
    <option value="down" {% if query.recent_change == "down" %}selected{% endif %}>最近降價</option>
  </select>
  <input type="number" step="0.1" name="min_change_percent" placeholder="最小漲跌幅 %" value="{{ query.min_change_percent if query.min_change_percent is not none else '' }}">
  <input type="number" step="0.1" name="max_change_percent" placeholder="最大漲跌幅 %" value="{{ query.max_change_percent if query.max_change_percent is not none else '' }}">
  <select name="sort">
    <option value="last_seen_desc" {% if query.sort == "last_seen_desc" %}selected{% endif %}>最近更新</option>
    <option value="price_asc" {% if query.sort == "price_asc" %}selected{% endif %}>價格低到高</option>
    <option value="price_desc" {% if query.sort == "price_desc" %}selected{% endif %}>價格高到低</option>
    <option value="name_asc" {% if query.sort == "name_asc" %}selected{% endif %}>名稱排序</option>
  </select>
  <button type="submit">搜尋</button>
</form>

<p>共 {{ total }} 筆結果</p>

<table>
  <thead>
    <tr>
      <th>商品名稱</th><th>分類</th><th>現價</th><th>上次價格</th><th>漲跌</th>
      <th>30天最低</th><th>30天最高</th><th>狀態</th><th>最後更新</th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr class="{% if not row.product.is_active %}inactive{% endif %}">
      <td><a href="/products/{{ row.product.id }}">{{ row.product.current_name }}</a></td>
      <td>{{ row.category.name }}</td>
      <td>${{ "{:,}".format(row.product.current_price) }}</td>
      <td>{% if row.stats.previous_price %}${{ "{:,}".format(row.stats.previous_price) }}{% else %}-{% endif %}</td>
      <td class="{% if row.stats.change_amount and row.stats.change_amount > 0 %}up{% elif row.stats.change_amount and row.stats.change_amount < 0 %}down{% endif %}">
        {% if row.stats.change_amount %}{{ "%+d"|format(row.stats.change_amount) }} ({{ "%.1f"|format(row.stats.change_percent) }}%){% else %}-{% endif %}
      </td>
      <td>{% if row.stats.low_30d %}${{ "{:,}".format(row.stats.low_30d) }}{% else %}-{% endif %}</td>
      <td>{% if row.stats.high_30d %}${{ "{:,}".format(row.stats.high_30d) }}{% else %}-{% endif %}</td>
      <td>{{ "在售" if row.product.is_active else "已下架" }}</td>
      <td>{{ row.product.last_seen_at.strftime("%Y-%m-%d %H:%M") }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<div class="pagination">
  {% if page > 1 %}<a href="/?{{ query_string }}&page={{ page - 1 }}">上一頁</a>{% endif %}
  <span>第 {{ page }} / {{ total_pages }} 頁</span>
  {% if page < total_pages %}<a href="/?{{ query_string }}&page={{ page + 1 }}">下一頁</a>{% endif %}
</div>
{% endblock %}
```

```python
# src/coolpc/public_api/routers/pages.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session
from coolpc.db.models import Category, Subcategory
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 30


@router.get("/")
def search_page(
    request: Request,
    q: str | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    brand: str | None = None,
    model: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    is_active: bool | None = None,
    recent_change: str | None = None,
    min_change_percent: float | None = None,
    max_change_percent: float | None = None,
    sort: str = "last_seen_desc",
    page: int = 1,
    session: Session = Depends(get_session),
):
    page = max(page, 1)
    filters = SearchFilters(
        q=q, category_id=category_id, subcategory_id=subcategory_id, brand=brand, model=model,
        min_price=min_price, max_price=max_price, is_active=is_active,
        recent_change=recent_change, min_change_percent=min_change_percent,
        max_change_percent=max_change_percent,
        sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
    )
    products, total = search_products(session, filters)

    rows = []
    for p in products:
        rows.append({
            "product": p,
            "category": session.get(Category, p.category_id),
            "stats": compute_product_stats(session, p.id),
        })

    query_params = {k: v for k, v in {
        "q": q, "category_id": category_id, "subcategory_id": subcategory_id,
        "brand": brand, "model": model,
        "min_price": min_price, "max_price": max_price, "is_active": is_active,
        "recent_change": recent_change, "min_change_percent": min_change_percent,
        "max_change_percent": max_change_percent, "sort": sort,
    }.items() if v not in (None, "")}

    return templates.TemplateResponse("search.html", {
        "request": request, "rows": rows,
        "categories": session.query(Category).order_by(Category.name).all(),
        "query": {
            "q": q or "", "category_id": category_id, "subcategory_id": subcategory_id,
            "brand": brand, "model": model,
            "min_price": min_price, "max_price": max_price, "is_active": is_active,
            "recent_change": recent_change, "min_change_percent": min_change_percent,
            "max_change_percent": max_change_percent, "sort": sort,
        },
        "query_string": urlencode(query_params),
        "page": page, "total_pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), "total": total,
    })
```

修改 `src/coolpc/public_api/app.py`：

```python
# src/coolpc/public_api/app.py
from __future__ import annotations
from fastapi import FastAPI
from coolpc.public_api.routers import api as api_router
from coolpc.public_api.routers import pages as pages_router

app = FastAPI(title="原價屋歷史價格查詢")
app.include_router(api_router.router)
app.include_router(pages_router.router)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_search_page.py -v`
Expected: PASS

- [ ] **Step 5: 手動啟動服務確認畫面**

```bash
COOLPC_DB_PATH=/tmp/coolpc_dev.db uv run python -c "
from coolpc.db.session import get_engine
from coolpc.db.models import Base
Base.metadata.create_all(get_engine('/tmp/coolpc_dev.db'))
"
COOLPC_DB_PATH=/tmp/coolpc_dev.db uv run coolpc-scraper import-html /home/xthybot/coolpc/download/2026-02-01-21-40.html
COOLPC_DB_PATH=/tmp/coolpc_dev.db uv run uvicorn coolpc.public_api.app:app --port 33690 &
sleep 2
curl -s http://127.0.0.1:33690/ | grep -o "共 [0-9]* 筆結果"
kill %1
```

Expected: 顯示「共 N 筆結果」，N 為真實樣本商品數量（數千）。

- [ ] **Step 6: Commit**

```bash
mkdir -p src/coolpc/public_api/templates
git add src/coolpc/public_api/templates/ src/coolpc/public_api/routers/pages.py src/coolpc/public_api/app.py tests/public_api/test_search_page.py
git commit -m "feat: public frontend - base template 與搜尋/列表頁"
```

---

## Task 22: 公開前端 — 商品詳細頁 + 價格走勢圖（Chart.js）

**Files:**
- Create: `src/coolpc/public_api/templates/product_detail.html`
- Modify: `src/coolpc/public_api/routers/pages.py`
- Test: `tests/public_api/test_product_detail_page.py`

**Interfaces:**
- Consumes: `compute_product_stats, get_price_history`（Task 16）；`ProductName`（Task 2）；`GET /api/products/{id}/prices`（Task 19，前端 JS 用 `fetch` 呼叫做圖表區間切換）
- Produces: `GET /products/{id}`（商品詳細頁）。供 Task 23（比較頁「快速加入比較」連結）沿用同一個 `same_category_products` 概念。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_product_detail_page.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_product_detail_page_renders_history_and_chart():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 v2",
                    current_price=19990, is_active=True, first_seen_at=t0, last_seen_at=t1, created_at=t0)
        session.add(p)
        session.flush()
        session.add_all([
            ProductName(product_id=p.id, name="ASUS RTX 5070", first_seen_at=t0, last_seen_at=t0),
            ProductName(product_id=p.id, name="ASUS RTX 5070 v2", first_seen_at=t1, last_seen_at=t1),
        ])
        session.add_all([
            PriceHistory(product_id=p.id, price=18990, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=p.id, price=19990, status=None, badges="", scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        pid = p.id

    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 v2" in resp.text
    assert "ASUS RTX 5070" in resp.text  # 舊名稱要顯示
    assert 'id="priceChart"' in resp.text
    assert "chart.js" in resp.text.lower()
    assert "18,990" in resp.text  # 歷史價格列表出現舊價格


def test_product_detail_page_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/products/999")
    assert resp.status_code == 404


def test_product_detail_page_shows_same_category_quick_compare():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A卡",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B卡",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        pid = p1.id

    resp = client.get(f"/products/{pid}")
    assert "B卡" in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_product_detail_page.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

```html
<!-- src/coolpc/public_api/templates/product_detail.html -->
{% extends "base.html" %}
{% block title %}{{ product.current_name }} - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<h1>{{ product.current_name }}</h1>
<p>分類：{{ category.name }} / {{ subcategory.name }}　狀態：{{ "在售" if product.is_active else "已下架" }}</p>
<p>歷史名稱：{{ historical_names | join("、") }}</p>
<p>第一次出現：{{ product.first_seen_at.strftime("%Y-%m-%d %H:%M") }}　最後一次出現：{{ product.last_seen_at.strftime("%Y-%m-%d %H:%M") }}</p>

<table>
  <tr><th>目前價格</th><td>${{ "{:,}".format(product.current_price) }}</td></tr>
  <tr><th>上次價格</th><td>{% if stats.previous_price %}${{ "{:,}".format(stats.previous_price) }}{% else %}-{% endif %}</td></tr>
  <tr><th>漲跌</th><td>{% if stats.change_amount %}{{ "%+d"|format(stats.change_amount) }} ({{ "%.1f"|format(stats.change_percent) }}%){% else %}-{% endif %}</td></tr>
  <tr><th>7 天最低 / 最高</th><td>{{ stats.low_7d or "-" }} / {{ stats.high_7d or "-" }}</td></tr>
  <tr><th>30 天最低 / 最高</th><td>{{ stats.low_30d or "-" }} / {{ stats.high_30d or "-" }}</td></tr>
  <tr><th>90 天最低 / 最高</th><td>{{ stats.low_90d or "-" }} / {{ stats.high_90d or "-" }}</td></tr>
  <tr><th>歷史最低 / 最高</th><td>${{ "{:,}".format(stats.all_time_low) }} / ${{ "{:,}".format(stats.all_time_high) }}</td></tr>
</table>

<h2>價格走勢</h2>
<div>
  <button data-range="7">7天</button>
  <button data-range="30">30天</button>
  <button data-range="90">90天</button>
  <button data-range="all">全部</button>
  自訂：<input type="date" id="rangeStart"> ~ <input type="date" id="rangeEnd">
  <button id="rangeCustom" type="button">套用</button>
</div>
<canvas id="priceChart" height="100"></canvas>

<h2>加入比較</h2>
<select id="compareAdd">
  <option value="">選擇同分類商品加入比較...</option>
  {% for p in same_category_products %}
  <option value="{{ p.id }}">{{ p.current_name }}</option>
  {% endfor %}
</select>
<button type="button" onclick="addCompare()">加入比較</button>

<h2>歷史價格列表</h2>
<table>
  <thead><tr><th>時間</th><th>價格</th></tr></thead>
  <tbody>
    {% for h in history %}
    <tr><td>{{ h.scraped_at.strftime("%Y-%m-%d %H:%M") }}</td><td>${{ "{:,}".format(h.price) }}</td></tr>
    {% endfor %}
  </tbody>
</table>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
const productId = {{ product.id }};
let priceChart;

async function loadPrices(params) {
  const url = new URL(`/api/products/${productId}/prices`, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v) url.searchParams.set(k, v);
  }
  const resp = await fetch(url);
  const data = await resp.json();
  const labels = data.map(d => d.scraped_at);
  const prices = data.map(d => d.price);
  if (priceChart) {
    priceChart.data.labels = labels;
    priceChart.data.datasets[0].data = prices;
    priceChart.update();
  } else {
    const ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: [{ label: '價格 (TWD)', data: prices, borderColor: '#2563eb', fill: false }] },
      options: {
        scales: {
          x: { title: { display: true, text: '日期 / 時間' } },
          y: { title: { display: true, text: '價格 TWD' } },
        },
      },
    });
  }
}

document.querySelectorAll('button[data-range]').forEach(btn => {
  btn.addEventListener('click', () => {
    const range = btn.dataset.range;
    loadPrices(range === 'all' ? {} : { days: range });
  });
});

document.getElementById('rangeCustom').addEventListener('click', () => {
  const startVal = document.getElementById('rangeStart').value;
  const endVal = document.getElementById('rangeEnd').value;
  // <input type=date> 只給日期，結束日要補到當天 23:59:59 才不會漏掉當天資料
  loadPrices({
    start: startVal ? `${startVal}T00:00:00` : '',
    end: endVal ? `${endVal}T23:59:59` : '',
  });
});

function addCompare() {
  const sel = document.getElementById('compareAdd');
  if (!sel.value) return;
  window.location.href = `/compare?ids=${productId},${sel.value}`;
}

loadPrices({ days: 30 });
</script>
{% endblock %}
```

補在 `src/coolpc/public_api/routers/pages.py` 尾端（並在檔案頂端加入 import）：

```python
from fastapi import HTTPException
from coolpc.db.models import Product, ProductName
from coolpc.stats.service import get_price_history


@router.get("/products/{product_id}")
def product_detail_page(request: Request, product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if product is None or product.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="商品不存在")
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    names = [
        n.name for n in
        session.query(ProductName).filter_by(product_id=product.id)
        .order_by(ProductName.first_seen_at).all()
    ]
    history = list(reversed(get_price_history(session, product.id)))
    same_category = (
        session.query(Product)
        .filter(Product.category_id == product.category_id, Product.id != product.id,
                Product.merged_into_id.is_(None))
        .order_by(Product.last_seen_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("product_detail.html", {
        "request": request, "product": product, "category": category, "subcategory": subcategory,
        "stats": stats, "historical_names": names, "history": history,
        "same_category_products": same_category,
    })
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_product_detail_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/public_api/templates/product_detail.html src/coolpc/public_api/routers/pages.py tests/public_api/test_product_detail_page.py
git commit -m "feat: public frontend - 商品詳細頁與 Chart.js 價格走勢圖"
```

---

## Task 23: 公開前端 — 商品比較頁

**Files:**
- Create: `src/coolpc/public_api/templates/compare.html`
- Modify: `src/coolpc/public_api/routers/pages.py`
- Test: `tests/public_api/test_compare_page.py`

**Interfaces:**
- Consumes: `compute_product_stats`（Task 16）；`GET /api/products/{id}/prices`（Task 19，前端 JS fetch 取多商品資料畫在同一張圖）
- Produces: `GET /compare?ids=1,2,3`（2–5 個商品比較頁）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/public_api/test_compare_page.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_compare_page_without_ids_shows_form_only():
    client, _ = _make_client()
    resp = client.get("/compare")
    assert resp.status_code == 200
    assert "商品比較" in resp.text


def test_compare_page_shows_error_for_invalid_count():
    client, _ = _make_client()
    resp = client.get("/compare", params={"ids": "1"})
    assert resp.status_code == 200
    assert "請選擇 2 到 5 個商品" in resp.text


def test_compare_page_renders_table_and_chart_for_valid_ids():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A卡", current_price=1000,
                     is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B卡", current_price=2000,
                     is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.flush()
        session.add(PriceHistory(product_id=p1.id, price=1000, status=None, badges="", scraped_at=t, snapshot_id=1))
        session.add(PriceHistory(product_id=p2.id, price=2000, status=None, badges="", scraped_at=t, snapshot_id=1))
        session.commit()
        id1, id2 = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{id1},{id2}"})
    assert resp.status_code == 200
    assert "A卡" in resp.text and "B卡" in resp.text
    assert 'id="compareChart"' in resp.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/public_api/test_compare_page.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

```html
<!-- src/coolpc/public_api/templates/compare.html -->
{% extends "base.html" %}
{% block title %}商品比較 - 原價屋歷史價格查詢{% endblock %}
{% block content %}
<h1>商品比較</h1>
<form method="get" action="/compare">
  <input type="text" name="ids" placeholder="輸入商品 ID，以逗號分隔，如 1,2,3" value="{{ ids }}">
  <button type="submit">比較</button>
</form>

{% if error %}<p style="color:#b91c1c">{{ error }}</p>{% endif %}

{% if items %}
<table>
  <thead>
    <tr>
      <th>商品</th><th>現價</th><th>7天最低</th><th>30天最低</th><th>30天最高</th>
      <th>歷史最低</th><th>歷史最高</th><th>最近漲跌</th>
    </tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td><a href="/products/{{ item.product.id }}">{{ item.product.current_name }}</a></td>
      <td>${{ "{:,}".format(item.product.current_price) }}</td>
      <td>{{ item.stats.low_7d or "-" }}</td>
      <td>{{ item.stats.low_30d or "-" }}</td>
      <td>{{ item.stats.high_30d or "-" }}</td>
      <td>${{ "{:,}".format(item.stats.all_time_low) }}</td>
      <td>${{ "{:,}".format(item.stats.all_time_high) }}</td>
      <td>{% if item.stats.change_amount %}{{ "%+d"|format(item.stats.change_amount) }} ({{ "%.1f"|format(item.stats.change_percent) }}%){% else %}-{% endif %}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<canvas id="compareChart" height="100"></canvas>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script>
const productIds = [{% for item in items %}{{ item.product.id }}{% if not loop.last %},{% endif %}{% endfor %}];
const colors = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed'];

async function loadCompareChart() {
  const seriesList = [];
  for (const pid of productIds) {
    const resp = await fetch(`/api/products/${pid}/prices`);
    seriesList.push(await resp.json());
  }
  const labelSet = new Set();
  seriesList.forEach(series => series.forEach(pt => labelSet.add(pt.scraped_at)));
  const labels = Array.from(labelSet).sort();

  const datasets = seriesList.map((series, i) => {
    const priceByTime = Object.fromEntries(series.map(pt => [pt.scraped_at, pt.price]));
    return {
      label: `商品 ${productIds[i]}`,
      data: labels.map(l => (l in priceByTime ? priceByTime[l] : null)),
      borderColor: colors[i % colors.length],
      spanGaps: true,
      fill: false,
    };
  });

  const ctx = document.getElementById('compareChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: { labels: labels, datasets: datasets },
    options: {
      scales: {
        x: { title: { display: true, text: '日期 / 時間' } },
        y: { title: { display: true, text: '價格 TWD' } },
      },
    },
  });
}
loadCompareChart();
</script>
{% endif %}
{% endblock %}
```

補在 `src/coolpc/public_api/routers/pages.py` 尾端：

```python
@router.get("/compare")
def compare_page(request: Request, ids: str | None = None, session: Session = Depends(get_session)):
    items = []
    error = None
    if ids:
        try:
            product_ids = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            product_ids = []
            error = "ids 格式錯誤，請輸入逗號分隔的商品 ID"
        if error is None and not (2 <= len(product_ids) <= 5):
            error = "請選擇 2 到 5 個商品進行比較"
        if error is None:
            for pid in product_ids:
                product = session.get(Product, pid)
                if product is None or product.merged_into_id is not None:
                    error = f"商品不存在: {pid}"
                    items = []
                    break
                items.append({"product": product, "stats": compute_product_stats(session, pid)})

    return templates.TemplateResponse("compare.html", {
        "request": request, "items": items, "ids": ids or "", "error": error,
    })
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/public_api/test_compare_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/public_api/templates/compare.html src/coolpc/public_api/routers/pages.py tests/public_api/test_compare_page.py
git commit -m "feat: public frontend - 商品比較頁"
```

---

## Task 24: 管理介面 — App 骨架 + 抓取狀態 Dashboard + 手動抓取 + HTML 封存瀏覽

**Files:**
- Create: `src/coolpc/admin_api/dependencies.py`（重用 Task 18 的 `get_session` 邏輯，直接 re-export）
- Create: `src/coolpc/admin_api/routers/__init__.py`
- Create: `src/coolpc/admin_api/routers/dashboard.py`
- Create: `src/coolpc/admin_api/app.py`
- Create: `src/coolpc/admin_api/templates/base.html`, `dashboard.html`, `html_archive_list.html`, `html_archive_view.html`
- Test: `tests/admin_api/test_dashboard.py`

**Interfaces:**
- Consumes: `get_session`（Task 18，經 `coolpc.public_api.dependencies` re-export）；`run_scrape, ScrapeSkipped`（Task 12）；`ScrapeSnapshot`（Task 2）；`decode_html`（Task 5）
- Produces: `admin_app`（FastAPI instance，Task 27 systemd 用 `uvicorn coolpc.admin_api.app:app` 啟動）；`GET /`（dashboard）；`POST /scrape`（手動抓取）；`GET /html-archive`、`GET /html-archive/{snapshot_id}`。供 Task 25（合併頁）、Task 26（相似度候選頁）掛在同一個 `admin_app` 底下。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/admin_api/test_dashboard.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, ScrapeSnapshot
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_dashboard_shows_recent_snapshots():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        session.add(ScrapeSnapshot(
            fetched_at=t, scrape_type="scheduled", raw_html_path="/x/2026-02-01.html",
            status="success", total_products=5000, new_products=10, delisted_products=3,
            price_up_count=20, price_down_count=15, created_at=t,
        ))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "success" in resp.text
    assert "5000" in resp.text


def test_manual_scrape_triggers_run_scrape_and_redirects(monkeypatch):
    client, Session_ = _make_client()
    called = {}

    def fake_run_scrape(scrape_type="scheduled", **kwargs):
        called["scrape_type"] = scrape_type
        return ScrapeSnapshot(
            fetched_at=datetime.datetime(2026, 2, 1), scrape_type=scrape_type,
            raw_html_path=None, status="success", total_products=1, new_products=1,
            delisted_products=0, price_up_count=0, price_down_count=0,
            created_at=datetime.datetime(2026, 2, 1),
        )

    monkeypatch.setattr("coolpc.admin_api.routers.dashboard.run_scrape", fake_run_scrape)
    resp = client.post("/scrape", follow_redirects=False)
    assert resp.status_code == 303
    assert called["scrape_type"] == "manual"


def test_html_archive_list_and_view(tmp_path):
    client, Session_ = _make_client()
    html_path = tmp_path / "sample.html"
    html_path.write_bytes("<html>測試內容 <script>alert(1)</script></html>".encode("cp950"))
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        snap = ScrapeSnapshot(
            fetched_at=t, scrape_type="manual", raw_html_path=str(html_path),
            status="success", total_products=1, created_at=t,
        )
        session.add(snap)
        session.commit()
        sid = snap.id

    list_resp = client.get("/html-archive")
    assert list_resp.status_code == 200
    assert str(html_path) in list_resp.text

    view_resp = client.get(f"/html-archive/{sid}")
    assert view_resp.status_code == 200
    assert "測試內容" in view_resp.text
    assert "<script>alert(1)</script>" not in view_resp.text  # 必須被跳脫，不可執行

def test_html_archive_view_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/html-archive/999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/admin_api/test_dashboard.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 實作**

```python
# src/coolpc/admin_api/dependencies.py
from coolpc.public_api.dependencies import get_session

__all__ = ["get_session"]
```

```html
<!-- src/coolpc/admin_api/templates/base.html -->
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}原價屋管理介面{% endblock %}</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", "微軟正黑體", sans-serif; margin: 0; background: #f7f7f8; color: #1a1a1a; }
    header { background: #111827; color: #fff; padding: 12px 20px; display: flex; gap: 20px; }
    header a { color: #fff; text-decoration: none; font-weight: 600; }
    main { max-width: 1100px; margin: 20px auto; padding: 0 16px; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 14px; word-break: break-all; }
    th { background: #f1f5f9; }
    .status-success { color: #15803d; }
    .status-failed { color: #b91c1c; }
    .status-partial { color: #d97706; }
    button { padding: 6px 12px; cursor: pointer; }
  </style>
</head>
<body>
<header>
  <a href="/">抓取狀態</a>
  <a href="/html-archive">原始 HTML</a>
  <a href="/products">商品搜尋</a>
  <a href="/similarity-hints">可能需要合併</a>
</header>
<main>
{% block content %}{% endblock %}
</main>
</body>
</html>
```

```html
<!-- src/coolpc/admin_api/templates/dashboard.html -->
{% extends "base.html" %}
{% block title %}抓取狀態 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>抓取狀態</h1>
<form method="post" action="/scrape">
  <button type="submit">手動執行抓取</button>
</form>
<table>
  <thead>
    <tr><th>估價時間</th><th>類型</th><th>狀態</th><th>商品總數</th><th>新商品</th><th>下架</th><th>漲價</th><th>降價</th><th>錯誤訊息</th></tr>
  </thead>
  <tbody>
    {% for s in snapshots %}
    <tr>
      <td>{{ s.fetched_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td>{{ s.scrape_type }}</td>
      <td class="status-{{ s.status }}">{{ s.status }}</td>
      <td>{{ s.total_products }}</td>
      <td>{{ s.new_products }}</td>
      <td>{{ s.delisted_products }}</td>
      <td>{{ s.price_up_count }}</td>
      <td>{{ s.price_down_count }}</td>
      <td>{{ s.error_message or "" }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

```html
<!-- src/coolpc/admin_api/templates/html_archive_list.html -->
{% extends "base.html" %}
{% block title %}原始 HTML 封存 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>原始 HTML 封存</h1>
<table>
  <thead><tr><th>估價時間</th><th>類型</th><th>狀態</th><th>檔案路徑</th></tr></thead>
  <tbody>
    {% for s in snapshots %}
    <tr>
      <td><a href="/html-archive/{{ s.id }}">{{ s.fetched_at.strftime("%Y-%m-%d %H:%M") }}</a></td>
      <td>{{ s.scrape_type }}</td>
      <td>{{ s.status }}</td>
      <td>{{ s.raw_html_path }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

```html
<!-- src/coolpc/admin_api/templates/html_archive_view.html -->
{% extends "base.html" %}
{% block title %}HTML 內容 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>{{ snapshot.fetched_at.strftime("%Y-%m-%d %H:%M") }} 原始 HTML</h1>
<p>路徑：{{ snapshot.raw_html_path }}</p>
<pre style="white-space:pre-wrap;word-break:break-all;background:#fff;padding:12px;max-height:600px;overflow:auto;">{{ content }}</pre>
{% endblock %}
```

```python
# src/coolpc/admin_api/routers/dashboard.py
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.db.models import ScrapeSnapshot
from coolpc.scraper.run import run_scrape, ScrapeSkipped
from coolpc.parser.html_parser import decode_html

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    snapshots = (
        session.query(ScrapeSnapshot).order_by(ScrapeSnapshot.created_at.desc()).limit(20).all()
    )
    return templates.TemplateResponse("dashboard.html", {"request": request, "snapshots": snapshots})


@router.post("/scrape")
def trigger_scrape():
    try:
        run_scrape(scrape_type="manual")
    except ScrapeSkipped:
        pass
    return RedirectResponse(url="/", status_code=303)


@router.get("/html-archive")
def html_archive_list(request: Request, session: Session = Depends(get_session)):
    snapshots = (
        session.query(ScrapeSnapshot)
        .filter(ScrapeSnapshot.raw_html_path.isnot(None))
        .order_by(ScrapeSnapshot.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse("html_archive_list.html", {"request": request, "snapshots": snapshots})


@router.get("/html-archive/{snapshot_id}")
def html_archive_view(request: Request, snapshot_id: int, session: Session = Depends(get_session)):
    snapshot = session.get(ScrapeSnapshot, snapshot_id)
    if snapshot is None or not snapshot.raw_html_path:
        raise HTTPException(status_code=404, detail="找不到原始 HTML")
    with open(snapshot.raw_html_path, "rb") as f:
        raw = f.read()
    content = decode_html(raw)
    return templates.TemplateResponse("html_archive_view.html", {
        "request": request, "snapshot": snapshot, "content": content,
    })
```

```python
# src/coolpc/admin_api/app.py
from __future__ import annotations
from fastapi import FastAPI
from coolpc.admin_api.routers import dashboard as dashboard_router

app = FastAPI(title="原價屋管理介面")
app.include_router(dashboard_router.router)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/admin_api/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p src/coolpc/admin_api/routers src/coolpc/admin_api/templates tests/admin_api
touch src/coolpc/admin_api/routers/__init__.py tests/admin_api/__init__.py
git add src/coolpc/admin_api/ tests/admin_api/
git commit -m "feat: admin_api - app 骨架、抓取狀態 dashboard、手動抓取、HTML 封存瀏覽"
```

---

## Task 25: 管理介面 — 商品搜尋 + 合併 + Undo 合併

**Files:**
- Create: `src/coolpc/admin_api/routers/products.py`
- Create: `src/coolpc/admin_api/templates/products.html`, `merge.html`
- Modify: `src/coolpc/admin_api/app.py`
- Test: `tests/admin_api/test_merge_page.py`

**Interfaces:**
- Consumes: `SearchFilters, search_products`（Task 17）；`merge_products, undo_merge, MergeError`（Task 15）
- Produces: `GET /products`（管理端商品搜尋，顯示商品 ID 供合併操作使用）；`GET /merge`（合併表單 + 合併紀錄列表）；`POST /merge`；`POST /merge/{merge_log_id}/undo`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/admin_api/test_merge_page.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, MergeLog
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def _seed_two_products(Session_):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                         current_price=18990, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                         current_price=19990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([source, target])
        session.flush()
        session.add_all([
            ProductName(product_id=source.id, name=source.current_name, first_seen_at=t, last_seen_at=t),
            ProductName(product_id=target.id, name=target.current_name, first_seen_at=t, last_seen_at=t),
        ])
        session.commit()
        return source.id, target.id


def test_product_search_page_shows_id_and_name():
    client, Session_ = _make_client()
    source_id, _ = _seed_two_products(Session_)
    resp = client.get("/products")
    assert resp.status_code == 200
    assert str(source_id) in resp.text
    assert "ASUS RTX 5070 PRIME 12G" in resp.text


def test_merge_form_success_then_undo_flow():
    client, Session_ = _make_client()
    source_id, target_id = _seed_two_products(Session_)

    resp = client.post("/merge", data={"source_id": source_id, "target_id": target_id},
                        follow_redirects=False)
    assert resp.status_code == 303
    assert "message" in resp.headers["location"]

    merge_page = client.get("/merge")
    assert "已合併" in merge_page.text
    assert "ASUS RTX 5070 PRIME 12G" in merge_page.text

    with Session_() as session:
        log = session.query(MergeLog).one()
        log_id = log.id

    undo_resp = client.post(f"/merge/{log_id}/undo", follow_redirects=False)
    assert undo_resp.status_code == 303

    merge_page_after = client.get("/merge")
    assert "已復原" in merge_page_after.text


def test_merge_same_source_and_target_shows_error():
    client, Session_ = _make_client()
    source_id, _ = _seed_two_products(Session_)
    resp = client.post("/merge", data={"source_id": source_id, "target_id": source_id},
                        follow_redirects=False)
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/admin_api/test_merge_page.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

```html
<!-- src/coolpc/admin_api/templates/products.html -->
{% extends "base.html" %}
{% block title %}商品搜尋 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>商品搜尋</h1>
<form method="get" action="/products">
  <input type="text" name="q" placeholder="搜尋商品名稱/舊名稱" value="{{ query.q }}">
  <select name="category_id">
    <option value="">全部分類</option>
    {% for c in categories %}
    <option value="{{ c.id }}" {% if query.category_id == c.id %}selected{% endif %}>{{ c.name }}</option>
    {% endfor %}
  </select>
  <button type="submit">搜尋</button>
</form>
<p>共 {{ total }} 筆（僅顯示前 100 筆）</p>
<table>
  <thead><tr><th>ID</th><th>商品名稱</th><th>現價</th><th>狀態</th><th>最後更新</th></tr></thead>
  <tbody>
    {% for p in products %}
    <tr>
      <td>{{ p.id }}</td>
      <td>{{ p.current_name }}</td>
      <td>${{ "{:,}".format(p.current_price) }}</td>
      <td>{{ "在售" if p.is_active else "已下架" }}</td>
      <td>{{ p.last_seen_at.strftime("%Y-%m-%d %H:%M") }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<p>複製要合併的商品 ID，到 <a href="/merge">合併商品</a> 頁面操作。</p>
{% endblock %}
```

```html
<!-- src/coolpc/admin_api/templates/merge.html -->
{% extends "base.html" %}
{% block title %}合併商品 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>合併商品</h1>
{% if message %}<p style="color:#15803d">{{ message }}</p>{% endif %}
{% if error %}<p style="color:#b91c1c">{{ error }}</p>{% endif %}

<form method="post" action="/merge">
  來源商品 ID（將被合併，舊名稱仍可搜尋）：<input type="number" name="source_id" required>
  目標商品 ID（合併後保留的主商品，請選擇目前仍持續更新的商品）：<input type="number" name="target_id" required>
  <button type="submit">合併</button>
</form>

<h2>合併紀錄</h2>
<table>
  <thead><tr><th>時間</th><th>來源</th><th>目標</th><th>狀態</th><th>操作</th></tr></thead>
  <tbody>
    {% for row in log_rows %}
    <tr>
      <td>{{ row.log.merged_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td>{{ row.source.current_name if row.source else "?" }} (#{{ row.log.source_product_id }})</td>
      <td>{{ row.target.current_name if row.target else "?" }} (#{{ row.log.target_product_id }})</td>
      <td>{{ "已復原" if row.log.undone_at else "已合併" }}</td>
      <td>
        {% if not row.log.undone_at %}
        <form method="post" action="/merge/{{ row.log.id }}/undo" style="display:inline">
          <button type="submit">Undo</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

```python
# src/coolpc/admin_api/routers/products.py
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.db.models import Category, MergeLog, Product
from coolpc.search.service import SearchFilters, search_products
from coolpc.merging.service import merge_products, undo_merge, MergeError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/products")
def product_search(
    request: Request, q: str | None = None, category_id: int | None = None,
    is_active: bool | None = None, session: Session = Depends(get_session),
):
    filters = SearchFilters(q=q, category_id=category_id, is_active=is_active, limit=100)
    products, total = search_products(session, filters)
    return templates.TemplateResponse("products.html", {
        "request": request, "products": products, "total": total,
        "categories": session.query(Category).order_by(Category.name).all(),
        "query": {"q": q or "", "category_id": category_id},
    })


@router.get("/merge")
def merge_form(request: Request, message: str | None = None, error: str | None = None,
               session: Session = Depends(get_session)):
    logs = session.query(MergeLog).order_by(MergeLog.merged_at.desc()).limit(50).all()
    log_rows = [
        {"log": log, "source": session.get(Product, log.source_product_id),
         "target": session.get(Product, log.target_product_id)}
        for log in logs
    ]
    return templates.TemplateResponse("merge.html", {
        "request": request, "message": message, "error": error, "log_rows": log_rows,
    })


@router.post("/merge")
def do_merge(source_id: int = Form(...), target_id: int = Form(...),
             session: Session = Depends(get_session)):
    try:
        merge_products(session, source_id, target_id)
        session.commit()
        return RedirectResponse(url="/merge?message=合併成功", status_code=303)
    except MergeError as exc:
        session.rollback()
        return RedirectResponse(url=f"/merge?error={exc}", status_code=303)


@router.post("/merge/{merge_log_id}/undo")
def do_undo(merge_log_id: int, session: Session = Depends(get_session)):
    try:
        undo_merge(session, merge_log_id)
        session.commit()
        return RedirectResponse(url="/merge?message=已復原合併", status_code=303)
    except MergeError as exc:
        session.rollback()
        return RedirectResponse(url=f"/merge?error={exc}", status_code=303)
```

修改 `src/coolpc/admin_api/app.py`：

```python
# src/coolpc/admin_api/app.py
from __future__ import annotations
from fastapi import FastAPI
from coolpc.admin_api.routers import dashboard as dashboard_router
from coolpc.admin_api.routers import products as products_router

app = FastAPI(title="原價屋管理介面")
app.include_router(dashboard_router.router)
app.include_router(products_router.router)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/admin_api/test_merge_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/admin_api/routers/products.py src/coolpc/admin_api/templates/products.html src/coolpc/admin_api/templates/merge.html src/coolpc/admin_api/app.py tests/admin_api/test_merge_page.py
git commit -m "feat: admin_api - 商品搜尋、合併、Undo 合併"
```

---

## Task 26: 管理介面 — 可能需要合併的商品（相似度候選）

**Files:**
- Create: `src/coolpc/admin_api/routers/similarity.py`
- Create: `src/coolpc/admin_api/templates/similarity_hints.html`
- Modify: `src/coolpc/admin_api/app.py`
- Test: `tests/admin_api/test_similarity_hints.py`

**Interfaces:**
- Consumes: `refresh_similarity_hints`（Task 10）；`SimilarityHint, Product`（Task 2）
- Produces: `GET /similarity-hints`；`POST /similarity-hints/refresh`；`POST /similarity-hints/{hint_id}/dismiss`。此頁只顯示候選並連結到 Task 25 的 `/merge` 頁面供人工確認，**本身不執行合併**。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/admin_api/test_similarity_hints.py
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session


def _make_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_similarity_hints_page_lists_candidates():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add(SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.85,
                                    computed_at=t, dismissed=False))
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "85%" in resp.text


def test_similarity_hints_refresh_creates_new_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.commit()

    resp = client.post("/similarity-hints/refresh", follow_redirects=False)
    assert resp.status_code == 303
    resp2 = client.get("/similarity-hints")
    assert "ASUS RTX 5070 PRIME 12G" in resp2.text


def test_dismiss_hint_removes_it_from_list():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品A獨特字串",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8, computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id = hint.id

    before = client.get("/similarity-hints")
    assert "商品A獨特字串" in before.text

    resp = client.post(f"/similarity-hints/{hint_id}/dismiss", follow_redirects=False)
    assert resp.status_code == 303
    after = client.get("/similarity-hints")
    assert "商品A獨特字串" not in after.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/admin_api/test_similarity_hints.py -v`
Expected: FAIL，404（route 不存在）

- [ ] **Step 3: 實作**

```html
<!-- src/coolpc/admin_api/templates/similarity_hints.html -->
{% extends "base.html" %}
{% block title %}可能需要合併的商品 - 原價屋管理介面{% endblock %}
{% block content %}
<h1>可能需要合併的商品</h1>
<form method="post" action="/similarity-hints/refresh">
  <button type="submit">重新計算相似度候選</button>
</form>
<p>以下為系統依名稱相似度找出的候選，僅供參考，請至 <a href="/merge">合併商品</a> 頁面手動確認後才會實際合併。</p>
<table>
  <thead><tr><th>相似度</th><th>商品 A</th><th>商品 B</th><th>操作</th></tr></thead>
  <tbody>
    {% for row in rows %}
    <tr>
      <td>{{ "%.0f"|format(row.hint.score * 100) }}%</td>
      <td>#{{ row.a.id }} {{ row.a.current_name }}</td>
      <td>#{{ row.b.id }} {{ row.b.current_name }}</td>
      <td>
        <form method="post" action="/similarity-hints/{{ row.hint.id }}/dismiss" style="display:inline">
          <button type="submit">不是同一商品，忽略</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

```python
# src/coolpc/admin_api/routers/similarity.py
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.db.models import Product, SimilarityHint
from coolpc.matching.similarity import refresh_similarity_hints

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/similarity-hints")
def similarity_hints_page(request: Request, session: Session = Depends(get_session)):
    hints = (
        session.query(SimilarityHint)
        .filter(SimilarityHint.dismissed.is_(False))
        .order_by(SimilarityHint.score.desc())
        .limit(100)
        .all()
    )
    rows = []
    for h in hints:
        pa = session.get(Product, h.product_a_id)
        pb = session.get(Product, h.product_b_id)
        if pa is None or pb is None or pa.merged_into_id is not None or pb.merged_into_id is not None:
            continue
        rows.append({"hint": h, "a": pa, "b": pb})
    return templates.TemplateResponse("similarity_hints.html", {"request": request, "rows": rows})


@router.post("/similarity-hints/refresh")
def refresh_hints(session: Session = Depends(get_session)):
    refresh_similarity_hints(session)
    session.commit()
    return RedirectResponse(url="/similarity-hints", status_code=303)


@router.post("/similarity-hints/{hint_id}/dismiss")
def dismiss_hint(hint_id: int, session: Session = Depends(get_session)):
    hint = session.get(SimilarityHint, hint_id)
    if hint is not None:
        hint.dismissed = True
        session.commit()
    return RedirectResponse(url="/similarity-hints", status_code=303)
```

修改 `src/coolpc/admin_api/app.py`：

```python
# src/coolpc/admin_api/app.py
from __future__ import annotations
from fastapi import FastAPI
from coolpc.admin_api.routers import dashboard as dashboard_router
from coolpc.admin_api.routers import products as products_router
from coolpc.admin_api.routers import similarity as similarity_router

app = FastAPI(title="原價屋管理介面")
app.include_router(dashboard_router.router)
app.include_router(products_router.router)
app.include_router(similarity_router.router)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/admin_api/test_similarity_hints.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/coolpc/admin_api/routers/similarity.py src/coolpc/admin_api/templates/similarity_hints.html src/coolpc/admin_api/app.py tests/admin_api/test_similarity_hints.py
git commit -m "feat: admin_api - 可能需要合併的商品（相似度候選）頁面"
```

---

## Task 27: systemd 部署檔案

**Files:**
- Create: `deploy/coolpc-scraper.service`
- Create: `deploy/coolpc-scraper.timer`
- Create: `deploy/coolpc-public.service`
- Create: `deploy/coolpc-admin.service`
- Test: `tests/test_deploy_files.py`

**Interfaces:**
- Consumes: `coolpc-scraper` console script（Task 14）；`coolpc.public_api.app:app`（Task 18）；`coolpc.admin_api.app:app`（Task 24）
- Produces: 四份 systemd unit 檔案，供 Task 29 README 的部署指令引用。**部署路徑約定** `/opt/coolpc-price-history`，執行使用者約定為 `coolpc`（README 會說明如何建立）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_deploy_files.py
import configparser
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent.parent / "deploy"


def _parse(filename: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(strict=False)
    cfg.read(DEPLOY_DIR / filename, encoding="utf-8")
    return cfg


def test_scraper_service_is_oneshot_and_calls_scrape():
    cfg = _parse("coolpc-scraper.service")
    assert cfg["Service"]["Type"] == "oneshot"
    assert "coolpc-scraper scrape" in cfg["Service"]["ExecStart"]


def test_scraper_timer_runs_every_6_hours_and_survives_reboot():
    cfg = _parse("coolpc-scraper.timer")
    assert cfg["Timer"]["OnCalendar"] == "*-*-* 0/6:00:00"
    assert cfg["Timer"]["Persistent"] == "true"
    assert cfg["Install"]["WantedBy"] == "timers.target"


def test_public_service_listens_on_33690():
    cfg = _parse("coolpc-public.service")
    assert "0.0.0.0" in cfg["Service"]["ExecStart"]
    assert "33690" in cfg["Service"]["ExecStart"]
    assert "coolpc.public_api.app:app" in cfg["Service"]["ExecStart"]
    assert cfg["Install"]["WantedBy"] == "multi-user.target"


def test_admin_service_listens_on_33691():
    cfg = _parse("coolpc-admin.service")
    assert "0.0.0.0" in cfg["Service"]["ExecStart"]
    assert "33691" in cfg["Service"]["ExecStart"]
    assert "coolpc.admin_api.app:app" in cfg["Service"]["ExecStart"]
    assert cfg["Install"]["WantedBy"] == "multi-user.target"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_deploy_files.py -v`
Expected: FAIL，`FileNotFoundError` 或找不到對應 section

- [ ] **Step 3: 實作**

```ini
# deploy/coolpc-scraper.service
[Unit]
Description=CoolPC 價格歷史抓取（單次執行）
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=coolpc
Group=coolpc
WorkingDirectory=/opt/coolpc-price-history
Environment=COOLPC_DB_PATH=/opt/coolpc-price-history/data/coolpc.db
ExecStart=/opt/coolpc-price-history/.venv/bin/coolpc-scraper scrape
```

```ini
# deploy/coolpc-scraper.timer
[Unit]
Description=每 6 小時觸發一次 CoolPC 價格抓取

[Timer]
OnCalendar=*-*-* 0/6:00:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

```ini
# deploy/coolpc-public.service
[Unit]
Description=CoolPC 公開價格查詢服務
After=network.target

[Service]
Type=simple
User=coolpc
Group=coolpc
WorkingDirectory=/opt/coolpc-price-history
Environment=COOLPC_DB_PATH=/opt/coolpc-price-history/data/coolpc.db
ExecStart=/opt/coolpc-price-history/.venv/bin/uvicorn coolpc.public_api.app:app --host 0.0.0.0 --port 33690
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# deploy/coolpc-admin.service
[Unit]
Description=CoolPC 管理介面服務
After=network.target

[Service]
Type=simple
User=coolpc
Group=coolpc
WorkingDirectory=/opt/coolpc-price-history
Environment=COOLPC_DB_PATH=/opt/coolpc-price-history/data/coolpc.db
ExecStart=/opt/coolpc-price-history/.venv/bin/uvicorn coolpc.admin_api.app:app --host 0.0.0.0 --port 33691
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_deploy_files.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add deploy/ tests/test_deploy_files.py
git commit -m "feat: 新增 systemd 部署檔案（scraper timer、public/admin service）"
```

---

## Task 28: 整合回歸測試（真實 HTML 語料）

**Files:**
- Create: `tests/test_regression_real_html.py`

**Interfaces:**
- Consumes: `parse_html`（Task 7）；`ingest_snapshot`（Task 9）；全部真實樣本 `/home/xthybot/coolpc/download/*.html`；實際的 Alembic migration chain（Task 3+4，用 `alembic upgrade head` 而非 `Base.metadata.create_all` 建庫，確保驗證的是正式環境真正會跑的 schema，包含 Task 4 實際的 bigram FTS5 觸發器）
- Produces: 一份端對端回歸測試，驗證解析→接入的完整流程在真實資料上長期運作不出錯、不遺失資料、FTS 索引與比對邏輯正確運作。

**注意（延續 Task 4 的裁決）：** Task 4 為了讓中文子字串搜尋正確，把每筆 `product_names` 索引成「整串原文 + 每個重疊 2-gram」多筆 `products_fts` 記錄，不是 1 筆對 1 筆。本任務原本假設 `products_fts` 筆數會等於 `product_names` 筆數，這個假設不成立，下方測試已改為驗證「觸發器有確實產生記錄且不遺漏」而非精確筆數相等。同時本測試改為透過真正的 `alembic upgrade head`（跟 Task 4 自己的測試一樣用 subprocess 跑）建立資料庫，而不是手刻一個簡化版觸發器，這樣才是真正驗證 Task 4 實際寫的觸發器邏輯，而不是驗證一份重複但過時的複製品。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_regression_real_html.py
import glob
import os
import subprocess
import sys
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName, PriceHistory, Category
from coolpc.parser.html_parser import parse_html
from coolpc.ingest.service import ingest_snapshot

SAMPLE_DIR = "/home/xthybot/coolpc/download"


def _session(tmp_path):
    db_path = tmp_path / "regression.db"
    env = os.environ.copy()
    env["COOLPC_DB_PATH"] = str(db_path)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    engine = create_engine(f"sqlite:///{db_path}")
    return Session(engine)


def test_import_real_chronological_sequence_without_errors_or_data_loss(tmp_path):
    files = sorted(glob.glob(f"{SAMPLE_DIR}/*.html"))[:40]
    assert len(files) == 40

    session = _session(tmp_path)
    snapshots = []
    for path in files:
        with open(path, "rb") as f:
            parsed = parse_html(f.read())  # 全部必須成功解析，不拋例外
        snap = ingest_snapshot(session, parsed, scrape_type="import", raw_html_path=path)
        session.commit()
        snapshots.append(snap)

    assert all(s.status == "success" for s in snapshots)

    # 中文無亂碼：已知分類名稱必須正確出現
    category_names = {c.name for c in session.query(Category).all()}
    assert "顯示卡VGA" in category_names
    assert "處理器 CPU" in category_names

    # 比對邏輯正確運作：總商品數不應隨快照數量線性暴增
    # （若比對失效、每次都誤判成新商品，數量會遠超單一快照商品數的合理倍數）
    total_products = session.query(Product).count()
    assert total_products < snapshots[-1].total_products * 3

    # 價格歷史正確累積：應有商品累積超過一筆價格紀錄
    counts = (
        session.query(PriceHistory.product_id, func.count(PriceHistory.id))
        .group_by(PriceHistory.product_id).all()
    )
    assert any(count > 1 for _, count in counts)

    # 舊名稱不會消失
    assert session.query(ProductName).count() >= total_products

    # FTS5 觸發器在真實批次匯入規模下仍正確同步（不只是 Task 4 的小規模單元測試）。
    # Task 4 的觸發器把每個名稱索引成「整串原文 + 每個重疊 2-gram」多筆記錄，
    # 不是 1:1，所以這裡驗證「每個名稱至少有對應記錄」而非精確筆數相等。
    fts_count = session.execute(text("SELECT COUNT(*) FROM products_fts")).scalar()
    product_names_count = session.query(ProductName).count()
    assert fts_count >= product_names_count
    distinct_indexed_products = session.execute(
        text("SELECT COUNT(DISTINCT product_id) FROM products_fts")
    ).scalar()
    assert distinct_indexed_products == session.query(Product).count()

    # 統計數字內部一致
    for s in snapshots:
        assert 0 <= s.new_products <= s.total_products
        assert s.delisted_products >= 0
        assert s.price_up_count >= 0
        assert s.price_down_count >= 0
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_regression_real_html.py -v`
Expected: 依當前實作情況可能已經 PASS（因為所有底層模組已完成）；若 FAIL，依錯誤訊息定位是 parser/ingest 哪個環節的既有實作有誤並修正。

- [ ] **Step 3: 若有失敗，修正對應模組**

這個任務不預期新增產品程式碼——若失敗，代表 Task 5–9 的某個既有函式在真實大規模資料上有邊界案例沒處理好（例如某種商品文字格式沒被 `split_name_price_badges` 涵蓋）。回到對應檔案修正，而不是在此檔案內加規則。

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_regression_real_html.py -v`
Expected: PASS

- [ ] **Step 5: 額外執行一次全量真實語料匯入，建立高信心（非自動化測試，手動驗證）**

```bash
rm -f /tmp/coolpc_full_regression.db
COOLPC_DB_PATH=/tmp/coolpc_full_regression.db uv run alembic upgrade head
time COOLPC_DB_PATH=/tmp/coolpc_full_regression.db uv run coolpc-scraper import-dir /home/xthybot/coolpc/download 2>&1 | tail -30
```

Expected: 全部 842 筆皆為 `[success]`，過程中無未捕捉例外。執行時間依硬體可能需數分鐘，屬正常現象。

- [ ] **Step 6: Commit**

```bash
git add tests/test_regression_real_html.py
git commit -m "test: 新增真實 HTML 語料端對端回歸測試"
```

---

## Task 29: README — 部署與使用說明

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 全部前述任務的最終使用者操作介面（CLI 指令、systemd unit 名稱、環境變數、port）
- Produces: 完整部署文件，供使用者依此在 Ubuntu Server 上從零安裝、啟動、排程、手動操作。

- [ ] **Step 1: 覆寫 README.md**

```markdown
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

會在 `data/coolpc.db` 建立所有資料表與 FTS5 全文索引。`data/raw_html/` 目錄
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
```

- [ ] **Step 2: 確認 README 內的指令與實際 pyproject.toml / deploy/ 內容一致**

檢查 `[project.scripts]`（Task 1）、`deploy/*.service` 的 port 與路徑（Task 27）
是否與 README 描述的指令完全吻合，如有落差就地修正 README。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: 完成部署與使用說明 README"
```
