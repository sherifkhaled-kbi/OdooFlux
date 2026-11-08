"""Behaviour contracts for plugins (structural typing; plugins need not inherit from core classes)."""

from typing import Optional, Protocol

from odooflux.core.contracts.records import Document, Finding, ValidationResult


class Rule(Protocol):
    key: str
    contract_version: int
    step: str
    depends: tuple

    def detect(self, document: Document) -> list:  # list[Finding]
        ...


class Validator(Protocol):
    key: str
    contract_version: int
    layer: int

    def applies_to(self, path: str) -> bool: ...

    def validate(self, path: str, text: str) -> ValidationResult: ...


class ParserAdapter(Protocol):
    key: str
    contract_version: int

    def parse(self, text: str) -> Optional[str]:
        """Return a parser error message, or None when the text parses."""
        ...


class RuntimeEnvironment(Protocol):
    key: str
    contract_version: int

    def available(self) -> bool: ...


class AIProvider(Protocol):
    key: str
    contract_version: int

    def complete(self, prompt: str, *, api_key: str, to_version: int) -> str: ...


class Renderer(Protocol):
    key: str
    contract_version: int

    def render(self, report: dict) -> str: ...


__all__ = ["Rule", "Validator", "ParserAdapter", "RuntimeEnvironment", "AIProvider", "Renderer", "Finding"]
