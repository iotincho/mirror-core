"""Use the diagnostic callback installed by the process composition."""


def report_issue(request, operation, error=None, **tags):
    callback = getattr(getattr(getattr(request, "app", None), "state", None), "report_issue", None)
    if callback is not None:
        callback(operation, error, **tags)
