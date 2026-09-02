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
