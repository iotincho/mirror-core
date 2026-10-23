"""Compatibility constructor for the transactional application service."""

def RequestProcessing(repository, runtime):
    from src.bootstrap.processing import LegacyRequestFacade

    return LegacyRequestFacade(repository, runtime)
