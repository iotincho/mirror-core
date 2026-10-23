"""Compatibility composition of provider failure normalization and retry policy."""

from src.bootstrap.failures import failure_for as failure_for
from src.core.processing.failures import retry_delay as retry_delay
