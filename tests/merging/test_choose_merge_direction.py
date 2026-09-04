import datetime
from coolpc.db.models import Product
from coolpc.merging.service import choose_merge_direction


def _product(id_, is_active, last_seen_at):
    p = Product(
        current_name=f"p{id_}", category_id=1, subcategory_id=1, current_price=100,
        is_active=is_active, last_seen_at=last_seen_at,
        created_at=last_seen_at,
    )
    p.id = id_
    return p


def test_choose_merge_direction_prefers_active_as_target():
    t = datetime.datetime(2026, 2, 1)
    a = _product(1, is_active=False, last_seen_at=t)
    b = _product(2, is_active=True, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is a
    assert target is b


def test_choose_merge_direction_prefers_active_as_target_reversed_args():
    t = datetime.datetime(2026, 2, 1)
    a = _product(1, is_active=True, last_seen_at=t)
    b = _product(2, is_active=False, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a


def test_choose_merge_direction_prefers_newer_last_seen_when_both_active():
    a = _product(1, is_active=True, last_seen_at=datetime.datetime(2026, 2, 1))
    b = _product(2, is_active=True, last_seen_at=datetime.datetime(2026, 2, 5))
    source, target = choose_merge_direction(a, b)
    assert source is a
    assert target is b


def test_choose_merge_direction_prefers_newer_last_seen_when_both_inactive():
    a = _product(1, is_active=False, last_seen_at=datetime.datetime(2026, 2, 5))
    b = _product(2, is_active=False, last_seen_at=datetime.datetime(2026, 2, 1))
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a


def test_choose_merge_direction_tie_break_by_smaller_id():
    t = datetime.datetime(2026, 2, 1)
    a = _product(5, is_active=True, last_seen_at=t)
    b = _product(9, is_active=True, last_seen_at=t)
    source, target = choose_merge_direction(a, b)
    assert source is b
    assert target is a
