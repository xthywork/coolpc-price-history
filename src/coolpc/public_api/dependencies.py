from __future__ import annotations
from collections.abc import Iterator
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import Product

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


def _is_visible(product: Product | None) -> bool:
    """商品存在，且沒有被合併掉（合併掉的來源商品對外一律視為不存在）。"""
    return product is not None and product.merged_into_id is None


def get_visible_product(product_id: int, session: Session = Depends(get_session)) -> Product:
    """單一路徑參數 product_id 的公開端點共用依賴：找不到，或已被合併掉的
    商品一律回 404。這個檢查原本在 api.py/pages.py 六個地方各自複製一份，
    是 Task 19 修過一次、後續任務又得防禦性重複的模式，抽成共用依賴讓
    未來新端點結構上不可能忘記這個檢查。"""
    product = session.get(Product, product_id)
    if not _is_visible(product):
        raise HTTPException(status_code=404, detail="商品不存在")
    return product
