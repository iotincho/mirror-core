"""PostgreSQL unit of work; rules and temporal decisions remain in application/core."""

from contextlib import asynccontextmanager

from pydantic import ValidationError
from sqlalchemy import case, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import Invitation
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.adapters.storage.postgres.journal_models import (
    JournalInvitationRecord,
    JournalReceiptRecord,
    JournalRevisionRecord,
    JournalRunRecord,
    JournalStageRecord,
    JournalTemplateRecord,
)
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.journals.contracts import EntryReference, ResponseJournalContext
from src.core.journals.errors import JournalError, JournalStorageUnavailable
from src.core.journals.models import JournalRun, JournalTemplate
from src.core.journals.ports import MutationReceipt, OwnerAccess


@asynccontextmanager
async def journal_database_errors():
    try:
        yield
    except IntegrityError as error:
        cause = getattr(error.orig, "__cause__", None)
        if getattr(cause, "constraint_name", None) == "uq_journal_active_owner":
            raise JournalError("journal_active_conflict") from None
        raise JournalStorageUnavailable() from None
    except SQLAlchemyError:
        raise JournalStorageUnavailable() from None


def parse_stored(model, payload):
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise JournalStorageUnavailable() from None


class PostgresJournals:
    def __init__(self, sessions, *, read_only=False):
        self.sessions, self.read_only = sessions, read_only

    @asynccontextmanager
    async def transaction(self, owner):
        async with journal_database_errors(), self.sessions.begin() as session:
            if self.read_only:
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
            yield JournalTransaction(session, owner, InvitationRepository(self.sessions))

    async def install_template(self, template):
        definition = template.model_dump(mode="json")
        async with journal_database_errors(), self.sessions.begin() as session:
            await session.execute(
                pg_insert(JournalTemplateRecord)
                .values(
                    id=template.id,
                    version=template.version,
                    definition=definition,
                )
                .on_conflict_do_nothing()
            )
            existing = await session.scalar(
                select(JournalTemplateRecord.definition).where(
                    JournalTemplateRecord.id == template.id,
                    JournalTemplateRecord.version == template.version,
                )
            )
            if parse_stored(JournalTemplate, existing) != template:
                raise JournalError("journal_template_version_conflict")

    async def templates(self, limit=50):
        if not 1 <= limit <= 100:
            raise ValueError("journal_invalid_page_limit")
        async with journal_database_errors(), self.sessions.begin() as session:
            if self.read_only:
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
            rows = await session.scalars(
                select(JournalTemplateRecord.definition)
                .order_by(
                    JournalTemplateRecord.id,
                    JournalTemplateRecord.version.desc(),
                )
                .limit(limit)
            )
            return tuple(parse_stored(JournalTemplate, row) for row in rows)

    async def due_owners(self, *, at, limit):
        async with journal_database_errors(), self.sessions() as session:
            rows = await session.scalars(
                select(JournalRunRecord.owner_id)
                .where(
                    JournalRunRecord.status == "active",
                    JournalRunRecord.ends_at <= (at if at is not None else func.clock_timestamp()),
                )
                .order_by(JournalRunRecord.ends_at, JournalRunRecord.owner_id)
                .limit(limit)
            )
            return tuple(rows)


class JournalTransaction:
    def __init__(self, session, owner, invitations):
        self.session, self.owner, self.invitations = session, owner, invitations

    async def access(self):
        row = (
            await self.session.execute(
                select(User.is_active, UserWorkspace.status)
                .outerjoin(
                    UserWorkspace,
                    UserWorkspace.user_id == User.id,
                )
                .where(User.id == self.owner)
            )
        ).first()
        return OwnerAccess(
            exists=row is not None,
            enabled=bool(row and row.is_active),
            workspace_active=bool(row and row.status == "active"),
        )

    async def lock_owner(self):
        # Same preference-row lock as invitations; defaults stay disabled for a new row.
        await self.invitations.preference(self.session, self.owner)

    async def response_context(self, invitation_id):
        invitation = await self.session.scalar(
            select(Invitation.id).where(
                Invitation.id == invitation_id,
                Invitation.user_id == self.owner,
            )
        )
        if invitation is None:
            raise JournalError("journal_reference_not_found")
        row = await self.session.scalar(
            select(JournalInvitationRecord).where(
                JournalInvitationRecord.invitation_id == invitation_id,
                JournalInvitationRecord.owner_id == self.owner,
            )
        )
        return ResponseJournalContext(
            reference=EntryReference(
                run_id=row.run_id,
                stage_id=row.stage_id,
                run_revision=row.revision,
            )
            if row
            else None
        )

    async def now(self):
        return await self.session.scalar(select(func.clock_timestamp()))

    async def receipt(self, key):
        row = await self.session.get(JournalReceiptRecord, (self.owner, key))
        if row is None:
            return None
        return MutationReceipt(
            **{name: getattr(row, name) for name in MutationReceipt.model_fields}
        )

    async def template(self, identifier, version):
        payload = await self.session.scalar(
            select(JournalTemplateRecord.definition).where(
                JournalTemplateRecord.id == identifier,
                JournalTemplateRecord.version == version,
            )
        )
        return parse_stored(JournalTemplate, payload) if payload is not None else None

    async def current(self):
        identifier = await self.session.scalar(
            select(JournalRunRecord.id).where(
                JournalRunRecord.owner_id == self.owner,
                JournalRunRecord.status == "active",
            )
        )
        return await self.run(identifier) if identifier is not None else None

    async def run(self, identifier, revision=None):
        if revision is None:
            revision = await self.session.scalar(
                select(JournalRunRecord.revision).where(
                    JournalRunRecord.id == identifier,
                    JournalRunRecord.owner_id == self.owner,
                )
            )
            if revision is None:
                return None
        payload = await self.session.scalar(
            select(JournalRevisionRecord.snapshot).where(
                JournalRevisionRecord.run_id == identifier,
                JournalRevisionRecord.owner_id == self.owner,
                JournalRevisionRecord.revision == revision,
            )
        )
        if payload is None:
            return None
        run = parse_stored(JournalRun, payload)
        if run.owner_id != self.owner or run.id != identifier or run.revision != revision:
            raise JournalStorageUnavailable()
        return run

    async def runs(self, *, limit, offset):
        total = await self.session.scalar(
            select(func.count())
            .select_from(JournalRunRecord)
            .where(JournalRunRecord.owner_id == self.owner)
        )
        rows = (
            await self.session.execute(
                select(JournalRunRecord.id, JournalRunRecord.revision)
                .where(JournalRunRecord.owner_id == self.owner)
                .order_by(
                    case(
                        (JournalRunRecord.status == "active", 0),
                        (JournalRunRecord.status == "paused", 1),
                        else_=2,
                    ),
                    JournalRunRecord.updated_at.desc(),
                    JournalRunRecord.id,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return tuple([await self.run(row.id, row.revision) for row in rows]), total

    async def revisions(self, identifier, *, limit, offset):
        query = select(JournalRevisionRecord.revision).where(
            JournalRevisionRecord.owner_id == self.owner,
            JournalRevisionRecord.run_id == identifier,
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.scalars(
            query.order_by(JournalRevisionRecord.revision.desc()).limit(limit).offset(offset)
        )
        return tuple([await self.run(identifier, revision) for revision in rows]), total

    async def save(self, run, *, expected_revision):
        if run.owner_id != self.owner:
            raise JournalError("journal_not_found")
        values = dict(
            revision=run.revision,
            status=run.status,
            ends_at=run.stages[-1].ends_at,
            updated_at=run.updated_at,
        )
        if expected_revision is None:
            await self.session.execute(
                insert(JournalRunRecord).values(
                    id=run.id,
                    owner_id=self.owner,
                    template_id=run.template_id,
                    template_version=run.template_version,
                    **values,
                )
            )
        else:
            if run.revision != expected_revision + 1:
                raise JournalError("journal_revision_conflict")
            result = await self.session.execute(
                update(JournalRunRecord)
                .where(
                    JournalRunRecord.id == run.id,
                    JournalRunRecord.owner_id == self.owner,
                    JournalRunRecord.revision == expected_revision,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise JournalError("journal_revision_conflict")
        await self.session.execute(
            insert(JournalRevisionRecord).values(
                run_id=run.id,
                owner_id=self.owner,
                revision=run.revision,
                recorded_at=run.updated_at,
                snapshot=run.model_dump(mode="json"),
            )
        )
        await self.session.execute(
            insert(JournalStageRecord),
            [
                dict(
                    run_id=run.id,
                    owner_id=self.owner,
                    revision=run.revision,
                    stage_id=stage.id,
                    position=position,
                    starts_at=stage.starts_at,
                    ends_at=stage.ends_at,
                )
                for position, stage in enumerate(run.stages)
            ],
        )

    async def record_receipt(self, receipt):
        if receipt.owner_id != self.owner:
            raise JournalError("journal_not_found")
        await self.session.execute(insert(JournalReceiptRecord).values(**receipt.model_dump()))
