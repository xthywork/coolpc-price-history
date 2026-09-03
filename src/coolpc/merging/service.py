from __future__ import annotations
import datetime
import json
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName, MergeLog


class MergeError(Exception):
    pass


def choose_merge_direction(a: Product, b: Product) -> tuple[Product, Product]:
    """回傳 (source, target)。這是決定性規則，不做任何名稱/相似度判斷：
    兩商品只有一個仍在上架中，該商品當 target；否則（都上架或都下架）
    以 last_seen_at 較新者當 target；完全同分以 id 較小者當 target。"""
    if a.is_active and not b.is_active:
        target, source = a, b
    elif b.is_active and not a.is_active:
        target, source = b, a
    elif a.last_seen_at != b.last_seen_at:
        target, source = (a, b) if a.last_seen_at > b.last_seen_at else (b, a)
    else:
        target, source = (a, b) if a.id < b.id else (b, a)
    return source, target


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
        still_owned_by_target = session.query(ProductName.id).filter(
            ProductName.id.in_(moved_ids),
            ProductName.product_id == merge_log.target_product_id,
        ).count()
        if still_owned_by_target != len(moved_ids):
            raise MergeError("此合併之後又有其他合併動作影響了這些商品名稱，請先 Undo 較新的合併")
        session.query(ProductName).filter(ProductName.id.in_(moved_ids)).update(
            {"product_id": source.id}, synchronize_session=False
        )
    source.merged_into_id = None
    merge_log.undone_at = datetime.datetime.utcnow()
    session.flush()
