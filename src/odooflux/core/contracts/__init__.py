"""Contract version and error types shared by every registry and plugin (REQ-ARC-002/006)."""

CONTRACT_VERSION = 1


class ContractError(Exception):
    """Base class for contract violations."""


class DuplicateRegistrationError(ContractError):
    """Two entries in one registry share a key."""


class PluginContractError(ContractError):
    """An entry declares a contract version this core does not implement."""

    def __init__(self, plugin: str, expected: int, actual):
        self.plugin = plugin
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"plugin {plugin!r} declares contract_version {actual!r}; "
            f"this core implements contract_version {expected}")


class UnsupportedVersionError(ContractError):
    """A requested version is unknown or not ordered as required."""
