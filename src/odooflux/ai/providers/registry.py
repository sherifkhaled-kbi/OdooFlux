"""Provider registry keyed by ``name`` with a contract-version check (REQ-AI-001)."""

from odooflux.core.contracts import CONTRACT_VERSION


class ProviderContractError(Exception):
    """``code`` is one of contract_version_mismatch, duplicate_provider, unknown_provider."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class ProviderRegistry:
    def __init__(self):
        self._providers: dict = {}

    def register(self, provider) -> None:
        actual = getattr(provider, "contract_version", None)
        if actual != CONTRACT_VERSION:
            raise ProviderContractError("contract_version_mismatch",
                                        f"{getattr(provider, 'name', '?')}: expected {CONTRACT_VERSION}, got {actual}")
        if provider.name in self._providers:
            raise ProviderContractError("duplicate_provider", provider.name)
        self._providers[provider.name] = provider

    def try_register(self, provider):
        """Register or return the error code; the run continues without that provider (US4 scenario 1)."""
        try:
            self.register(provider)
        except ProviderContractError as exc:
            return exc.code
        return None

    def get(self, name: str):
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderContractError("unknown_provider", name) from None

    def names(self) -> list:
        return sorted(self._providers)
