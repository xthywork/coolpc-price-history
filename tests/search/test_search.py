import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products, search_products_and

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _add(session, cat, sub, name, price, is_active, t, brand=None, model=None):
    p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name, brand=brand,
                model=model, current_price=price, is_active=is_active, first_seen_at=t,
                last_seen_at=t, created_at=t)
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


def test_search_by_keyword_with_space_matches_literal_space_in_name():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat, sub, "Synology HAT3300 4TB【限搭NAS主機】", 6890, True, t)
    session.commit()

    # 名稱本身就含空白，"RTX 5070" 拆成 "RTX"/"5070" 兩個 token（預設 AND
    # 語意）仍要能各自比對到、進而找到這個商品；另一個商品完全不含這兩個
    # token，確保不會被誤配到。
    results, total = search_products(session, SearchFilters(q="RTX 5070"))
    assert total == 1
    assert "5070" in results[0].current_name


def test_search_by_keyword_with_space_means_or_only_when_explicitly_requested():
    """空白分隔預設是 AND；只有明確傳入 q_match="or" 才會退回 OR 語意
    （較寬鬆的瀏覽/篩選情境，非預設）。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat, sub, "MSI RTX 5080 GAMING 16G", 28990, True, t)
    _add(session, cat, sub, "Synology DS923+", 15990, True, t)
    session.commit()

    # 預設 AND 語意：沒有任何商品同時包含 "RTX" 又包含 "5090"，查不到
    default_results, default_total = search_products(session, SearchFilters(q="RTX 5090"))
    assert default_total == 0
    assert default_results == []

    # 明確要求 OR 語意時，"RTX" 這個 token 應該比對到兩張顯卡
    or_results, or_total = search_products(session, SearchFilters(q="RTX 5090", q_match="or"))
    names = {p.current_name for p in or_results}
    assert or_total == 2
    assert "ASUS RTX 5070 PRIME 12G" in names
    assert "MSI RTX 5080 GAMING 16G" in names
    assert "Synology DS923+" not in names


def test_search_default_and_finds_non_contiguous_tokens_but_excludes_wrong_model():
    """搜尋「ZOTAC 3050」要能找到「ZOTAC RTX3050 ECO SOLO」（3050 沒有以
    獨立單字出現，是夾在 RTX3050 裡面），但不能找到「ZOTAC GT730 2GB Zone
    Edition」（完全沒有 3050）——驗證預設 AND 語意不要求整段字串連續出現，
    只要求每個片段各自命中。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ZOTAC RTX3050 ECO SOLO", 6490, True, t)
    _add(session, cat, sub, "ZOTAC GT730 2GB Zone Edition", 2490, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(q="ZOTAC 3050"))
    assert total == 1
    assert results[0].current_name == "ZOTAC RTX3050 ECO SOLO"


def test_search_products_and_requires_all_tokens_across_names():
    """AND 語意：每個 token 都要在該商品的某個歷史名稱比對到，但不必是
    同一列——同一商品底下，目前名稱跟歷史（改名前）名稱都算數。這裡刻意
    讓其中一個 token 只出現在改名前的歷史名稱、不出現在目前名稱，證明
    AND 是跨列彙整判斷，不是只看目前名稱。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    # 目前名稱是 5070，改名前的舊名稱是 5060——"5060" 這個 token 只存在
    # 於歷史名稱列，不存在於目前名稱列。
    target = _add(session, cat, sub, "ASUS RTX 5070 PRIME OC 12GB", 19990, True, t)
    session.add(ProductName(product_id=target.id, name="ASUS RTX 5060 PRIME OC 12GB", first_seen_at=t, last_seen_at=t))
    _add(session, cat, sub, "MSI RTX 5080 GAMING 16G", 28990, True, t)
    session.commit()

    results = search_products_and(session, "ASUS 5060")
    assert len(results) == 1
    assert results[0].id == target.id


def test_search_products_and_returns_empty_when_only_some_tokens_match():
    """只有部分 token 命中時（AND 語意）不應回傳該商品。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "MSI RTX 5080 GAMING 16G", 28990, True, t)
    session.commit()

    results = search_products_and(session, "ASUS RTX 5070 PRIME 12G")
    assert results == []


def test_search_sort_by_brand_puts_null_brand_last():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "無品牌商品", 1000, True, t, brand=None)
    _add(session, cat, sub, "ZOTAC商品", 1000, True, t, brand="ZOTAC")
    _add(session, cat, sub, "ASUS商品", 1000, True, t, brand="ASUS")
    session.commit()

    results, total = search_products(session, SearchFilters(sort="brand_asc"))
    assert total == 3
    assert [p.brand for p in results] == ["ASUS", "ZOTAC", None]


def test_search_sort_by_status_puts_active_first():
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "下架商品", 1000, False, t)
    _add(session, cat, sub, "上架商品", 1000, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(sort="status_active_first"))
    assert total == 2
    assert [p.is_active for p in results] == [True, False]


def test_search_sort_by_category_respects_custom_sort_order():
    session = _session()
    cat_first = Category(name="Z分類", sort_order=1)
    sub_first = Subcategory(name="子1", category=cat_first)
    cat_second = Category(name="A分類", sort_order=2)
    sub_second = Subcategory(name="子2", category=cat_second)
    session.add_all([cat_first, sub_first, cat_second, sub_second])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat_second, sub_second, "第二分類的商品", 1000, True, t)
    _add(session, cat_first, sub_first, "第一分類的商品", 1000, True, t)
    session.commit()

    results, total = search_products(session, SearchFilters(sort="category_asc"))
    assert total == 2
    # 依 sort_order（1 在前），而不是分類名稱字母順序（"A分類" 應該會先出現）
    assert [p.current_name for p in results] == ["第一分類的商品", "第二分類的商品"]


def test_search_products_q_match_and_requires_both_words():
    """q_match="and" 時，空白分隔的兩個字串必須同時命中，不是 OR。"""
    session = _session()
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()
    t = datetime.datetime(2026, 2, 1)
    _add(session, cat, sub, "ASUS RTX 5070 PRIME 12G", 18990, True, t)
    _add(session, cat, sub, "MSI RTX 5080 GAMING 16G", 28990, True, t)
    _add(session, cat, sub, "Synology DS923+", 15990, True, t)
    session.commit()

    # 明確用 OR 語意查，"RTX 5090" 應該因為 "RTX" 這個 token 命中兩張顯卡
    or_results, or_total = search_products(session, SearchFilters(q="RTX 5090", q_match="or"))
    assert or_total == 2

    # 改用 AND 語意查同樣的字串，因為沒有任何商品同時包含 "RTX" 又包含
    # "5090"，應該完全查不到（不會像 OR 語意那樣回傳兩張顯卡）
    and_results, and_total = search_products(session, SearchFilters(q="RTX 5090", q_match="and"))
    assert and_total == 0
    assert and_results == []

    # 兩個字串都真的同時出現在同一個商品時，AND 語意才要找到它
    and_results2, and_total2 = search_products(session, SearchFilters(q="RTX 5070", q_match="and"))
    assert and_total2 == 1
    assert and_results2[0].current_name == "ASUS RTX 5070 PRIME 12G"
