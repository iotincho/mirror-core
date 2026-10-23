"""Bounded SQL projections. Never load User OAuth relationships or private documents."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, String, and_, case, cast, func, literal, or_, select, update

from src.adapters.storage.postgres.accounts import User
from src.administration.config import get_admin_settings
from src.administration.models import DocumentMetric, InventoryState, MetricCoverage, UserActivity
from src.administration.schemas import (
    ActivityPoint,
    ActivitySeries,
    Coverage,
    DashboardSummary,
    ProcessingCounts,
    Sources,
    UserList,
    UserRead,
)
from src.processing.models import ProcessingRecord

ZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def period_start(now, days):
    today = now.astimezone(ZONE).date()
    first = today - timedelta(days=days - 1)
    return datetime.combine(first, datetime.min.time(), ZONE).astimezone(UTC)


class AdministrationRepository:
    def __init__(self, session, max_age=300, now=None):
        self.session = session
        self.now = now or datetime.now(UTC)
        self.fresh_since = self.now - timedelta(seconds=max_age)

    def fresh_inventory(self):
        return and_(InventoryState.complete.is_(True), InventoryState.synced_at >= self.fresh_since)

    def user_projection(self):
        notes = (
            select(DocumentMetric.user_id, func.count().label("notes"))
            .where(DocumentMetric.deleted.is_(False))
            .group_by(DocumentMetric.user_id)
            .subquery()
        )
        activity = (
            select(UserActivity.user_id, func.max(UserActivity.last_seen_at).label("last_seen"))
            .group_by(UserActivity.user_id)
            .subquery()
        )
        return (
            select(
                User.id,
                User.email,
                User.is_active,
                User.laboratory_enabled,
                literal(get_admin_settings().personal_axes_enabled).label(
                    "laboratory_global_enabled"
                ),
                User.created_at,
                activity.c.last_seen.label("last_activity_at"),
                case((self.fresh_inventory(), func.coalesce(notes.c.notes, 0)), else_=None).label(
                    "notes_count"
                ),
            )
            .outerjoin(notes, notes.c.user_id == User.id)
            .outerjoin(activity, activity.c.user_id == User.id)
            .outerjoin(InventoryState, InventoryState.user_id == User.id)
        )

    async def list_users(self, page, per_page, sort, order, q, is_active):
        projection = self.user_projection().subquery()
        filters = []
        if q:
            # Escape SQL LIKE wildcards: search is literal, not an accidental pattern language.
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(
                or_(
                    projection.c.email.ilike(f"%{escaped}%", escape="\\"),
                    cast(projection.c.id, String).ilike(f"%{escaped}%", escape="\\"),
                )
            )
        if is_active is not None:
            filters.append(projection.c.is_active == is_active)
        total = await self.session.scalar(
            select(func.count()).select_from(projection).where(*filters)
        )
        column = projection.c[sort]
        direction = column.asc() if order == "asc" else column.desc()
        rows = await self.session.execute(
            select(projection)
            .where(*filters)
            .order_by(direction.nulls_last(), projection.c.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return UserList(items=[UserRead(**row) for row in rows.mappings()], total=total)

    async def user(self, user_id):
        result = await self.session.execute(self.user_projection().where(User.id == user_id))
        row = result.mappings().one_or_none()
        return UserRead(**row) if row else None

    async def set_laboratory_access(self, user_id, enabled):
        result = await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(laboratory_enabled=enabled)
            .returning(User.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.user(user_id)

    async def inventory_coverage(self):
        total = await self.session.scalar(select(func.count()).select_from(User))
        fresh = await self.session.scalar(
            select(func.count()).select_from(InventoryState).where(self.fresh_inventory())
        )
        synced = await self.session.scalar(select(func.min(InventoryState.synced_at)))
        # Unknown arrival/provenance must not silently become zero new notes.
        unknown = await self.session.scalar(
            select(func.count())
            .select_from(DocumentMetric)
            .where(or_(DocumentMetric.arrived_at.is_(None), DocumentMetric.kind.is_(None)))
        )
        complete = total == fresh
        return complete, synced, complete and unknown == 0

    async def summary(self, days):
        start = period_start(self.now, days)
        users = (
            await self.session.execute(
                select(func.count(User.id), func.count(User.id).filter(User.is_active.is_(True)))
            )
        ).one()
        complete, synced, notes_complete = await self.inventory_coverage()
        since = await self.session.scalar(
            select(MetricCoverage.since).where(MetricCoverage.name == "app_access")
        )
        accesses = (
            await self.session.scalar(
                select(func.count(func.distinct(UserActivity.user_id))).where(
                    UserActivity.day >= start.astimezone(ZONE).date(),
                    UserActivity.last_seen_at <= self.now,
                )
            )
            if since
            else None
        )
        total_notes = (
            await self.session.scalar(
                select(func.count())
                .select_from(DocumentMetric)
                .where(DocumentMetric.deleted.is_(False))
            )
            if complete
            else None
        )
        counts = (
            dict(
                (
                    await self.session.execute(
                        select(DocumentMetric.kind, func.count())
                        .where(
                            DocumentMetric.arrived_at >= start,
                            DocumentMetric.arrived_at <= self.now,
                        )
                        .group_by(DocumentMetric.kind)
                    )
                ).all()
            )
            if notes_complete
            else {}
        )
        writers = (
            await self.session.scalar(
                select(func.count(func.distinct(DocumentMetric.user_id))).where(
                    DocumentMetric.arrived_at >= start,
                    DocumentMetric.arrived_at <= self.now,
                    DocumentMetric.kind.in_(["writing", "audio"]),
                )
            )
            if notes_complete
            else None
        )
        processing = dict(
            (
                await self.session.execute(
                    select(ProcessingRecord.status, func.count())
                    .where(
                        ProcessingRecord.parent_processing_id.is_(None),
                        ProcessingRecord.workflow != "extractor",
                        ProcessingRecord.created_at >= start,
                        ProcessingRecord.created_at <= self.now,
                    )
                    .group_by(ProcessingRecord.status)
                )
            ).all()
        )
        return DashboardSummary(
            period_days=days,
            updated_at=self.now,
            users_total=users[0],
            users_active=users[1],
            users_accessed=accesses,
            users_wrote=writers,
            notes_total=total_notes,
            notes_created=counts.get("writing", 0) + counts.get("audio", 0)
            if notes_complete
            else None,
            notes_by_source=Sources(
                **{
                    kind: counts.get(kind, 0) if notes_complete else None
                    for kind in ("writing", "audio", "imported")
                }
            ),
            processing=ProcessingCounts(
                completed=processing.get("completed", 0),
                failed=processing.get("failed", 0),
                pending=sum(
                    processing.get(status, 0) for status in ("queued", "waiting", "retrying")
                ),
                running=processing.get("running", 0),
            ),
            coverage=Coverage(
                activity_since=since,
                documents_complete=complete,
                inventory_synced_at=synced,
                notes_complete=notes_complete,
            ),
        )

    async def activity(self, days):
        start = period_start(self.now, days)
        since = await self.session.scalar(
            select(MetricCoverage.since).where(MetricCoverage.name == "app_access")
        )
        _, _, notes_complete = await self.inventory_coverage()
        accessed = (
            dict(
                (
                    await self.session.execute(
                        select(UserActivity.day, func.count())
                        .where(
                            UserActivity.day >= start.astimezone(ZONE).date(),
                            UserActivity.last_seen_at <= self.now,
                        )
                        .group_by(UserActivity.day)
                    )
                ).all()
            )
            if since
            else {}
        )
        local_day = cast(
            func.timezone("America/Argentina/Buenos_Aires", DocumentMetric.arrived_at), Date
        )
        writers = (
            dict(
                (
                    await self.session.execute(
                        select(local_day, func.count(func.distinct(DocumentMetric.user_id)))
                        .where(
                            DocumentMetric.arrived_at >= start,
                            DocumentMetric.arrived_at <= self.now,
                            DocumentMetric.kind.in_(["writing", "audio"]),
                        )
                        .group_by(local_day)
                    )
                ).all()
            )
            if notes_complete
            else {}
        )
        first = start.astimezone(ZONE).date()
        return ActivitySeries(
            items=[
                ActivityPoint(
                    date=day,
                    accessed=accessed.get(day, 0)
                    if since and day >= since.astimezone(ZONE).date()
                    else None,
                    wrote=writers.get(day, 0) if notes_complete else None,
                )
                for day in (first + timedelta(days=index) for index in range(days))
            ]
        )
