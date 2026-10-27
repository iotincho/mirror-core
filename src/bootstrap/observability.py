"""Configure process telemetry and expose callbacks for dependency injection."""

from src.adapters.providers.telemetry.sentry import initialize_sentry as initialize
from src.adapters.providers.telemetry.sentry import report_issue as report_issue
from src.adapters.providers.telemetry.sentry import trace_operation as trace_operation
from src.bootstrap.settings import get_settings


def initialize_sentry(service):
    initialize(service, get_settings())
