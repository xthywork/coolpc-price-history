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
