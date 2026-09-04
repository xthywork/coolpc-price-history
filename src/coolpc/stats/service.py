from __future__ import annotations
import datetime
from dataclasses import dataclass
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from coolpc.db.models import Product, PriceHistory


@dataclass
class ProductStats:
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_7d: int | None
    high_7d: int | None
    low_30d: int | None
    high_30d: int | None
    low_90d: int | None
    high_90d: int | None
    all_time_low: int
    all_time_high: int


def get_merged_group_product_ids(session: Session, product_id: int) -> list[int]:
    """回傳與 product_id 屬於同一個合併群組的所有商品 id（含自己）。

    以廣度優先方式遞迴展開：不只找出「直接合併進 product_id 的商品」，
    還要繼續找出「合併進那些商品的商品」，直到不再有新的成員加入為止。
    這是為了正確處理合併鏈（A 併入 B，之後 B 又併入 C）——如果只找一層，
    從 C 查詢群組會漏掉 A，導致 A 的價格歷史從所有統計/歷史端點消失。
    """
    group = {product_id}
    frontier = {product_id}
    while frontier:
        rows = session.query(Product.id).filter(Product.merged_into_id.in_(frontier)).all()
        new_ids = {r[0] for r in rows} - group
        if not new_ids:
            break
        group |= new_ids
        frontier = new_ids
    return sorted(group)


def get_price_history(
    session: Session, product_id: int,
    start: datetime.datetime | None = None, end: datetime.datetime | None = None,
) -> list[PriceHistory]:
    group_ids = get_merged_group_product_ids(session, product_id)
    query = session.query(PriceHistory).filter(PriceHistory.product_id.in_(group_ids))
    if start is not None:
        query = query.filter(PriceHistory.scraped_at >= start)
    if end is not None:
        query = query.filter(PriceHistory.scraped_at <= end)
    return query.order_by(PriceHistory.scraped_at.asc()).all()


def _min_max(session: Session, group_ids: list[int],
             since: datetime.datetime | None) -> tuple[int | None, int | None]:
    query = session.query(func.min(PriceHistory.price), func.max(PriceHistory.price)).filter(
        PriceHistory.product_id.in_(group_ids)
    )
    if since is not None:
        query = query.filter(PriceHistory.scraped_at >= since)
    return query.one()


def compute_product_stats(session: Session, product_id: int,
                           now: datetime.datetime | None = None) -> ProductStats:
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"商品不存在: {product_id}")
    now = now or datetime.datetime.utcnow()
    group_ids = get_merged_group_product_ids(session, product_id)

    recent = (
        session.query(PriceHistory)
        .filter(PriceHistory.product_id.in_(group_ids))
        .order_by(PriceHistory.scraped_at.desc())
        .limit(2)
        .all()
    )
    previous_price = recent[1].price if len(recent) > 1 else None
    change_amount = None
    change_percent = None
    if previous_price is not None:
        change_amount = product.current_price - previous_price
        change_percent = (change_amount / previous_price * 100) if previous_price else None

    low_7d, high_7d = _min_max(session, group_ids, now - datetime.timedelta(days=7))
    low_30d, high_30d = _min_max(session, group_ids, now - datetime.timedelta(days=30))
    low_90d, high_90d = _min_max(session, group_ids, now - datetime.timedelta(days=90))
    all_time_low, all_time_high = _min_max(session, group_ids, None)

    return ProductStats(
        current_price=product.current_price, previous_price=previous_price,
        change_amount=change_amount, change_percent=change_percent,
        low_7d=low_7d, high_7d=high_7d, low_30d=low_30d, high_30d=high_30d,
        low_90d=low_90d, high_90d=high_90d,
        all_time_low=all_time_low if all_time_low is not None else product.current_price,
        all_time_high=all_time_high if all_time_high is not None else product.current_price,
    )


def get_merged_groups(session: Session, root_ids: list[int]) -> dict[int, list[int]]:
    """一次算出多個商品各自的合併群組，回傳 {root_id: [群組成員 id]}。

    功能上等同於對每個 id 各呼叫一次 get_merged_group_product_ids()，但那樣
    做在搜尋結果頁會變成每列一次（甚至多次）查詢；這裡改成每展開一層只發
    一次查詢，整批商品共用，層數通常是 1 到 2 層就收斂。
    """
    if not root_ids:
        return {}
    groups: dict[int, set[int]] = {rid: {rid} for rid in root_ids}
    owner: dict[int, int] = {rid: rid for rid in root_ids}
    frontier = set(root_ids)
    while frontier:
        rows = session.query(Product.id, Product.merged_into_id).filter(
            Product.merged_into_id.in_(frontier)
        ).all()
        next_frontier: set[int] = set()
        for product_id, parent_id in rows:
            # 已經歸屬於某個群組的商品不重複收，避免合併成環時無限迴圈
            if product_id in owner:
                continue
            root = owner.get(parent_id)
            if root is None:
                continue
            owner[product_id] = root
            groups[root].add(product_id)
            next_frontier.add(product_id)
        frontier = next_frontier
    return {root: sorted(members) for root, members in groups.items()}


def _sample(prices: list[int], max_points: int) -> list[int]:
    """把價格點等距取樣到最多 max_points 點。迷你走勢圖只有幾十像素寬，
    多給的點在畫面上完全看不出差別，卻會讓回應大上一個數量級。"""
    if len(prices) <= max_points:
        return prices
    step = (len(prices) - 1) / (max_points - 1)
    sampled = [prices[round(i * step)] for i in range(max_points)]
    # 取樣不能弄丟最後一筆：那是目前價格，走勢圖的終點必須是它
    sampled[-1] = prices[-1]
    return sampled


def get_sparkline_points(
    session: Session, product_ids: list[int], days: int, max_points: int = 32,
) -> dict[int, list[int]]:
    """批次取出多個商品的近期價格點，供搜尋結果的迷你走勢圖使用。

    先取最近 days 天的資料；在這段期間內完全沒有價格點的商品（例如早就
    下架、歷史停在幾個月前的商品）改取它自己最後 max_points 筆，這樣列表
    上每一列都畫得出走勢，而不是對半數商品留白。整批只發兩次查詢。
    """
    if not product_ids:
        return {}
    groups = get_merged_groups(session, product_ids)
    member_to_root = {
        member: root for root, members in groups.items() for member in members
    }
    since = datetime.datetime.now() - datetime.timedelta(days=days)
    rows = session.query(
        PriceHistory.product_id, PriceHistory.price,
    ).filter(
        PriceHistory.product_id.in_(member_to_root.keys()),
        PriceHistory.scraped_at >= since,
    ).order_by(PriceHistory.scraped_at.asc()).all()

    collected: dict[int, list[int]] = {pid: [] for pid in product_ids}
    for member_id, price in rows:
        root = member_to_root.get(member_id)
        if root is not None:
            collected[root].append(price)

    stale_roots = [pid for pid, prices in collected.items() if len(prices) < 2]
    if stale_roots:
        stale_members = [
            member for member, root in member_to_root.items() if root in stale_roots
        ]
        ranked = select(
            PriceHistory.product_id, PriceHistory.price, PriceHistory.scraped_at,
            func.row_number().over(
                partition_by=PriceHistory.product_id,
                order_by=PriceHistory.scraped_at.desc(),
            ).label("rn"),
        ).where(PriceHistory.product_id.in_(stale_members)).subquery()
        tail_rows = session.execute(
            select(ranked.c.product_id, ranked.c.price)
            .where(ranked.c.rn <= max_points)
            .order_by(ranked.c.scraped_at.asc())
        ).all()
        for member_id, price in tail_rows:
            root = member_to_root.get(member_id)
            if root is not None:
                collected[root].append(price)

    return {pid: _sample(prices, max_points) for pid, prices in collected.items()}
