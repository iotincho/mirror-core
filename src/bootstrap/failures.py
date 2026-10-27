"""Compose technical failure normalization with the workflow retry policy."""

from src.adapters.providers.http.failures import failure_facts
from src.core.processing.failures import classify_failure
from src.core.processing.failures import retry_delay as retry_delay


def failure_for(error, attempts, service):
    return classify_failure(failure_facts(error), attempts, service)
