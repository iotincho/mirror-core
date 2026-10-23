"""Compatibility imports; canonical implementation lives in the new layers."""

from src.adapters.storage.postgres.submissions import SubmissionRepository as SubmissionRepository
from src.core.processing.submissions import SubmissionConflict as SubmissionConflict
from src.core.processing.submissions import fingerprint as fingerprint
