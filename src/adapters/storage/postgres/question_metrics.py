"""Fenced provider receipts and aggregate SQL without questions, notes or owner identifiers."""

from datetime import UTC, timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.invitation_models import Invitation
from src.adapters.storage.postgres.invitation_question_models import InvitationFeedback
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.question_metric_models import (
    QuestionPreparationMetric,
    QuestionProviderCall,
)
from src.adapters.storage.postgres.state import database_errors
from src.core.processing.errors import LeaseLost, WorkflowFailure


async def ensure_metric(session, job):
    await session.execute(
        insert(QuestionPreparationMetric)
        .values(
            processing_id=job.id,
            user_id=job.user_id,
            model=job.config.get("model", "unconfigured"),
            created_at=job.created_at,
            due_at=job.expires_at,
        )
        .on_conflict_do_nothing()
    )


async def fenced_job(session, context):
    job = await session.scalar(
        select(ProcessingRecord).where(ProcessingRecord.id == context.record.id).with_for_update()
    )
    now = await session.scalar(select(func.clock_timestamp()))
    if (
        not job
        or job.user_id != context.record.user_id
        or job.resource_id != context.record.resource_id
        or job.workflow != "question_preparation"
        or job.fencing_token != context.record.fencing_token
        or job.lease_owner != context.record.lease_owner
        or job.status != "running"
        or job.lease_expires_at <= now
    ):
        raise LeaseLost()
    return job, now


class PostgresQuestionMetrics:
    def __init__(self, sessions, max_calls_per_day=1000):
        self.sessions = sessions
        self.max_calls_per_day = max_calls_per_day

    async def start_call(self, context):
        async with database_errors(), self.sessions.begin() as session:
            job, now = await fenced_job(session, context)
            if job.expires_at <= now:
                raise WorkflowFailure("question_preparation_expired")
            day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(f"daily-question-calls:{day.date()}", 0)
                    )
                )
            )
            used = await session.scalar(
                select(func.count())
                .select_from(QuestionProviderCall)
                .where(QuestionProviderCall.started_at >= day)
            )
            if used >= self.max_calls_per_day:
                raise WorkflowFailure("question_daily_call_limit")
            await ensure_metric(session, job)
            created = await session.scalar(
                insert(QuestionProviderCall)
                .values(
                    processing_id=job.id,
                    fencing_token=job.fencing_token,
                    started_at=now,
                    reserved_input_tokens=job.config["max_input_tokens"],
                    reserved_output_tokens=job.config["max_output_tokens"],
                )
                .on_conflict_do_nothing()
                .returning(QuestionProviderCall.fencing_token)
            )
            if created is None:
                raise WorkflowFailure("question_call_already_started")
            return job.fencing_token

    async def complete_call(self, context, token, usage, elapsed_ms):
        async with database_errors(), self.sessions.begin() as session:
            job, now = await fenced_job(session, context)
            row = await session.get(QuestionProviderCall, (job.id, token), with_for_update=True)
            if row is None or row.finished_at is not None:
                return
            row.finished_at, row.elapsed_ms = now, max(0, int(elapsed_ms))
            for field in ("input_tokens", "output_tokens"):
                value = usage.get(field)
                setattr(
                    row,
                    field,
                    value
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    else None,
                )

    async def cleanup(self):
        async with database_errors(), self.sessions.begin() as session:
            expired = (
                select(QuestionPreparationMetric.processing_id)
                .where(QuestionPreparationMetric.created_at < func.now() - timedelta(days=90))
                .order_by(QuestionPreparationMetric.created_at)
                .limit(500)
            )
            await session.execute(
                delete(QuestionPreparationMetric).where(
                    QuestionPreparationMetric.processing_id.in_(expired)
                )
            )

    async def aggregate(self, days):
        if not 1 <= days <= 30:
            raise ValueError("invalid_metrics_period")
        since = func.now() - timedelta(days=days)
        metric, calls = QuestionPreparationMetric, QuestionProviderCall
        safe_codes = (
            "prepared",
            "catalog",
            "not_ready",
            "invalid_artifact",
            "source_busy",
            "original_storage_unavailable",
            "no_eligible_personal",
        )
        async with database_errors(), self.sessions() as session:
            preparation = list(
                (
                    await session.execute(
                        select(
                            metric.model,
                            func.count().label("accepted"),
                            func.count()
                            .filter(metric.ready_at <= metric.due_at)
                            .label("ready_in_time"),
                        )
                        .where(metric.created_at >= since)
                        .group_by(metric.model)
                    )
                ).mappings()
            )
            code = case(
                (metric.decision.in_(safe_codes), metric.decision), else_="pending_or_other"
            )
            decisions = dict(
                (
                    await session.execute(
                        select(code, func.count()).where(metric.created_at >= since).group_by(code)
                    )
                ).all()
            )
            provider = list(
                (
                    await session.execute(
                        select(
                            metric.model,
                            func.count().label("started"),
                            func.count()
                            .filter(calls.finished_at.is_(None))
                            .label("unknown_outcome"),
                            func.count()
                            .filter(calls.input_tokens.is_(None) | calls.output_tokens.is_(None))
                            .label("unknown_usage"),
                            func.sum(calls.input_tokens).label("known_input_tokens"),
                            func.sum(calls.output_tokens).label("known_output_tokens"),
                            func.sum(calls.reserved_input_tokens).label("reserved_input_tokens"),
                            func.sum(calls.reserved_output_tokens).label("reserved_output_tokens"),
                            func.percentile_cont(0.95)
                            .within_group(calls.elapsed_ms)
                            .label("latency_p95_ms"),
                        )
                        .select_from(calls)
                        .join(metric, metric.processing_id == calls.processing_id)
                        .where(calls.started_at >= since)
                        .group_by(metric.model)
                    )
                ).mappings()
            )
            states = dict(
                (
                    await session.execute(
                        select(ProcessingRecord.status, func.count())
                        .join(metric, metric.processing_id == ProcessingRecord.id)
                        .where(metric.created_at >= since)
                        .group_by(ProcessingRecord.status)
                    )
                ).all()
            )
            allowed_errors = (
                "question_provider_failed",
                "question_provider_incomplete",
                "question_provider_configuration",
                "question_preparation_failed",
                "question_preparation_expired",
                "question_context_budget",
                "question_evidence_unavailable",
                "question_evidence_changed",
                "question_topic_inventory_limit",
                "question_call_already_started",
                "question_daily_call_limit",
                "workspace_unavailable",
                "workflow_internal_error",
            )
            error_code = case(
                (ProcessingRecord.error_code.in_(allowed_errors), ProcessingRecord.error_code),
                else_="other",
            )
            failures = dict(
                (
                    await session.execute(
                        select(error_code, func.count())
                        .join(metric, metric.processing_id == ProcessingRecord.id)
                        .where(metric.created_at >= since, ProcessingRecord.error_code.is_not(None))
                        .group_by(error_code)
                    )
                ).all()
            )
            feedback = dict(
                (
                    await session.execute(
                        select(InvitationFeedback.value, func.count())
                        .join(Invitation, Invitation.id == InvitationFeedback.invitation_id)
                        .where(
                            InvitationFeedback.recorded_at >= since, Invitation.kind == "scheduled"
                        )
                        .group_by(InvitationFeedback.value)
                    )
                ).all()
            )
            initials = dict(
                (
                    await session.execute(
                        select(Invitation.source, func.count())
                        .where(Invitation.created_at >= since, Invitation.kind == "scheduled")
                        .group_by(Invitation.source)
                    )
                ).all()
            )
        return dict(
            days=days,
            preparations=[dict(row) for row in preparation],
            decisions=decisions,
            provider_calls=[dict(row) for row in provider],
            job_states=states,
            failures=failures,
            initial_sources=initials,
            explicit_feedback=feedback,
            cost_usd=None,
            cost_note="Use per-model token usage and current tariffs; unknown usage is not zero.",
        )
