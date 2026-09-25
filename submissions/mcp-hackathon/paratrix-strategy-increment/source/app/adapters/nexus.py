"""Explicit source availability for the simulation-only Worker deployment."""

class SourceUnavailable(Exception):
    code = "source_unavailable"

    def __init__(self, message: str = "The Nexus source is currently unavailable."):
        self.message = message
        self.issues: list[dict] = []
        super().__init__(message)


class SourceInsufficient(Exception):
    code = "source_not_sufficient"

    def __init__(
        self,
        message: str = "The Nexus response lacks complete simulated equity with verifiable semantics.",
        issues: list[dict] | None = None,
    ):
        self.message = message
        self.issues = issues or []
        super().__init__(message)


class DisabledNexus:
    """No external account credentials or socket-based clients in this deployment."""

    def status(self):
        return {
            "configured": False,
            "verified": False,
            "public_refs": [],
            "note": "This deployment supports public examples and simulated equity JSON imports. The external Nexus connection is disabled.",
        }

    def import_curve(self, _strategy_ref):
        raise SourceUnavailable("The external Nexus connection is disabled in this deployment.")
