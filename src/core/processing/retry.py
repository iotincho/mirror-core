"""Reset a failed job and schedule its next delivery in the caller transaction."""


def reset_job(transaction, current, now):
    current.status = "queued"
    current.generation += 1
    current.version += 1
    current.fencing_token += 1
    current.stage_attempts = 0
    current.error_code = None
    current.retryable = False
    current.available_at = current.updated_at = now
    current.completed_at = None
    transaction.event(current)
    transaction.schedule(current)
