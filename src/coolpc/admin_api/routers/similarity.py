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
    return templates.TemplateResponse(request, "similarity_hints.html", {"rows": rows})


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
