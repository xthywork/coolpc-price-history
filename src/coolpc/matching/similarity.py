from __future__ import annotations
import datetime
import re
import unicodedata
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from coolpc.db.models import Product, SimilarityHint

BRACKET_PATTERN = re.compile(r"[【\[(（][^】\])）]*[】\])）]")
WHITESPACE_PATTERN = re.compile(r"\s+")
SIMILARITY_THRESHOLD = 0.75


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    normalized = BRACKET_PATTERN.sub("", normalized)
    normalized = WHITESPACE_PATTERN.sub("", normalized)
    return normalized.strip().lower()


def compute_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def refresh_similarity_hints(
    session: Session, category_id: int | None = None,
    now: datetime.datetime | None = None,
) -> int:
    now = now or datetime.datetime.utcnow()
    query = session.query(Product).filter(Product.merged_into_id.is_(None))
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)
    products = query.all()

    by_category: dict[int, list[Product]] = {}
    for p in products:
        by_category.setdefault(p.category_id, []).append(p)

    existing_pairs = {
        (min(h.product_a_id, h.product_b_id), max(h.product_a_id, h.product_b_id))
        for h in session.query(SimilarityHint).all()
    }

    created = 0
    for group in by_category.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                p1, p2 = group[i], group[j]
                pair = (min(p1.id, p2.id), max(p1.id, p2.id))
                if pair in existing_pairs:
                    continue
                score = compute_similarity(p1.current_name, p2.current_name)
                if score >= SIMILARITY_THRESHOLD:
                    session.add(SimilarityHint(
                        product_a_id=pair[0], product_b_id=pair[1],
                        score=score, computed_at=now, dismissed=False,
                    ))
                    existing_pairs.add(pair)
                    created += 1
    return created
