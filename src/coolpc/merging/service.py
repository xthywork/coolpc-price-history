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
