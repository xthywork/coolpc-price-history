from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, aliased
from coolpc.admin_api.dependencies import get_session
from coolpc.db.models import Product, SimilarityHint
from coolpc.matching.similarity import refresh_similarity_hints
from coolpc.merging.service import choose_merge_direction, merge_products, MergeError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/similarity-hints")
def similarity_hints_page(request: Request, message: str | None = None,
                           session: Session = Depends(get_session)):
    # 已合併走的商品要在 SQL 層、LIMIT 之前就排除，否則分數高但已失效的候選
    # 會佔掉 LIMIT 100 視窗裡的名額，把排在後面、分數較低但仍然有效的候選
    # 擠出畫面之外（而且這些被擠掉的 hint 從未被標記 dismissed，永遠卡住）。
    ProductA = aliased(Product)
    ProductB = aliased(Product)
    hints = (
        session.query(SimilarityHint, ProductA, ProductB)
        .join(ProductA, SimilarityHint.product_a_id == ProductA.id)
        .join(ProductB, SimilarityHint.product_b_id == ProductB.id)
        .filter(SimilarityHint.dismissed.is_(False))
        .filter(ProductA.merged_into_id.is_(None))
        .filter(ProductB.merged_into_id.is_(None))
        .order_by(SimilarityHint.score.desc())
        .limit(100)
        .all()
    )
    rows = []
    for h, pa, pb in hints:
        # 商品理論上不會被實際刪除（本專案只標記 inactive，不刪列），這裡僅作
        # 防禦性保留；merged_into_id 的過濾已經在上面的 SQL JOIN 完成。
        if pa is None or pb is None or pa.merged_into_id is not None or pb.merged_into_id is not None:
            continue
        rows.append({"hint": h, "a": pa, "b": pb})
    return templates.TemplateResponse(request, "similarity_hints.html", {"rows": rows, "message": message})


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


@router.post("/similarity-hints/batch-merge")
async def batch_merge_hints(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    hint_ids = [int(v) for v in form.getlist("hint_ids")]
    merged = 0
    skipped = 0
    for hint_id in hint_ids:
        hint = session.get(SimilarityHint, hint_id)
        if hint is None:
            skipped += 1
            continue
        pa = session.get(Product, hint.product_a_id)
        pb = session.get(Product, hint.product_b_id)
        if pa is None or pb is None or pa.merged_into_id is not None or pb.merged_into_id is not None:
            skipped += 1
            continue
        source, target = choose_merge_direction(pa, pb)
        try:
            merge_products(session, source.id, target.id)
            hint.dismissed = True
            merged += 1
        except MergeError:
            skipped += 1
    session.commit()
    qs = urlencode({"message": f"已合併 {merged} 組，略過 {skipped} 組"})
    return RedirectResponse(url=f"/similarity-hints?{qs}", status_code=303)


@router.post("/similarity-hints/batch-dismiss")
async def batch_dismiss_hints(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    hint_ids = [int(v) for v in form.getlist("hint_ids")]
    count = 0
    for hint_id in hint_ids:
        hint = session.get(SimilarityHint, hint_id)
        if hint is not None:
            hint.dismissed = True
            count += 1
    session.commit()
    qs = urlencode({"message": f"已忽略 {count} 組"})
    return RedirectResponse(url=f"/similarity-hints?{qs}", status_code=303)
