"""Project exception types."""


class PowersToolError(Exception):
    """Base exception for Powers Tool failures."""


class VisaConnectionError(PowersToolError):
    """Raised when VISA discovery, connection, or I/O fails."""
