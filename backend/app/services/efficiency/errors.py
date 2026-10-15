"""Domain errors for the efficiency domain.

Endpoints map these to HTTP statuses; services never raise HTTPException.
"""


class EfficiencyError(Exception):
    """Base class for efficiency-domain errors."""


class EfficiencyNotFoundError(EfficiencyError):
    pass


class EfficiencyForbiddenError(EfficiencyError):
    pass


class EfficiencyValidationError(EfficiencyError):
    pass
