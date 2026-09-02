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
    return templates.TemplateResponse(request, "dashboard.html", {"snapshots": snapshots})


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
    return templates.TemplateResponse(request, "html_archive_list.html", {"snapshots": snapshots})


@router.get("/html-archive/{snapshot_id}")
def html_archive_view(request: Request, snapshot_id: int, session: Session = Depends(get_session)):
    snapshot = session.get(ScrapeSnapshot, snapshot_id)
    if snapshot is None or not snapshot.raw_html_path:
        raise HTTPException(status_code=404, detail="找不到原始 HTML")
    with open(snapshot.raw_html_path, "rb") as f:
        raw = f.read()
    content = decode_html(raw)
    return templates.TemplateResponse(request, "html_archive_view.html", {
        "snapshot": snapshot, "content": content,
    })
