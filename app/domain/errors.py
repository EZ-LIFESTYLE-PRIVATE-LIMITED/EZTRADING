"""Domain-level exceptions. Adapters translate vendor errors into these."""


class EZTradingError(Exception):
    """Base class for all application errors."""


class AuthRequiredError(EZTradingError):
    """No signed-in user."""


class BrokerAuthError(EZTradingError):
    """Broker session missing or expired; user must log in to the broker again."""


class BrokerError(EZTradingError):
    """Broker call failed for a reason other than authentication."""


class AdvisorError(EZTradingError):
    """The AI advisor failed or returned an unusable answer."""


class ValidationError(EZTradingError):
    """User input was invalid."""


class NotFoundError(EZTradingError):
    """Requested resource does not exist (or belongs to someone else)."""


class ConflictError(EZTradingError):
    """Action conflicts with current state (e.g. suggestion already executed)."""


class ForbiddenError(EZTradingError):
    """The action is switched off or not allowed for this account."""


class PremiumRequiredError(ForbiddenError):
    """The feature needs an active premium subscription."""


class RateLimitedError(EZTradingError):
    """Too many requests; try again later."""
