"""Data-category authorization, minimisation and the sensitive-content filter (FR-019, ADR-017).

Policy (to be signed off by the project owner, see docs/reviews/fragments/ws-c-human-review.md):
- Sending source to an external provider needs a grant that names that provider and each data category sent.
- Allowed categories are source_python, source_xml and evidence_excerpt. Credentials, secrets, database dumps and
  unrelated customer data are never allowed and cannot be granted.
- A region whose text matches the filter is excluded whole (it is not redacted and sent: the replacement has to be
  byte-exact for the region, and a redacted prompt would invite the model to rewrite the secret).
"""

import re

from odooflux.ai.providers.types import DATA_CATEGORIES

FORBIDDEN_CATEGORIES = ("credentials", "secrets", "database_dump", "customer_data")


class AuthorizationError(Exception):
    """``code``: forbidden_category, unknown_category, bad_grant."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def parse_grants(values) -> dict:
    """``"p=a,b"`` or a list of them -> ``{provider: sorted categories}``. Forbidden or unknown categories fail."""
    if isinstance(values, str):
        values = [values]
    grants: dict = {}
    for value in values or []:
        provider, sep, cats = str(value).partition("=")
        provider = provider.strip()
        categories = {c.strip() for c in cats.split(",") if c.strip()}
        if not sep or not provider or not categories:
            raise AuthorizationError("bad_grant", f"expected PROVIDER=CATEGORY[,CATEGORY], got {value!r}")
        for category in categories:
            if category in FORBIDDEN_CATEGORIES:
                raise AuthorizationError("forbidden_category", f"{category} can never be sent")
            if category not in DATA_CATEGORIES:
                raise AuthorizationError("unknown_category", f"{category}; allowed: {', '.join(DATA_CATEGORIES)}")
        grants.setdefault(provider, set()).update(categories)
    return {p: sorted(c) for p, c in grants.items()}


class Authorizer:
    def __init__(self, grants: dict):
        self.grants = {p: frozenset(c) for p, c in (grants or {}).items()}

    def check(self, provider: str, provider_type: str, categories) -> object:
        """None when the transmission is authorized, else the contract ``error_kind``."""
        if provider_type != "external":
            return None  # local and fake providers keep the data on the machine
        if not self.grants:
            return "authorization_missing"
        if provider not in self.grants:
            return "authorization_provider_mismatch"
        categories = tuple(categories)
        if not categories or any(c not in DATA_CATEGORIES or c not in self.grants[provider] for c in categories):
            return "authorization_category_denied"
        return None

    def missing(self, provider: str, categories) -> tuple:
        """Categories of a request that the grant for ``provider`` does not cover (for the denial message)."""
        granted = self.grants.get(provider, frozenset())
        return tuple(c for c in categories if c not in granted)


_QUOTE = "['\"]"
_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("bearer_credential", re.compile(r"(?i)\bauthorization\s*[:=]\s*['\"]?(?:bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}")),
    ("provider_api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")),
    ("credential_literal", re.compile(
        r"(?i)\b[\w.]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)\w*"
        + _QUOTE + r"?\s*[:=]\s*" + _QUOTE + r"?(?!(?:fields\.|self\.|os\.|env\b|ir\.config))[^\s'\"#,)}\]]{6,}")),
    ("connection_string_with_password", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@[^\s/]+")),
    ("database_dump", re.compile(
        r"(?im)^\s*--\s*PostgreSQL database dump|^\s*COPY\s+\S+\s*(?:\([^)]*\))?\s+FROM\s+stdin\s*;"
        r"|^\s*INSERT\s+INTO\s+\S+[^;]*\bVALUES\b|^\s*pg_dump\b")),
)


def sensitive_kinds(text: str) -> list:
    """Names of the sensitive-content kinds found in ``text`` (never the matched values)."""
    return sorted({name for name, pattern in _PATTERNS if pattern.search(text or "")})


def minimise_violations(req) -> list:
    """Reasons the request carries more than the minimised region: absolute or escaping paths, customer code in the
    system text, roles other than the single user message."""
    problems = []
    path = str((req.region or {}).get("path", ""))
    if (not path or path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", path) or ".." in re.split(r"[\\/]", path)):
        problems.append("path_not_relative")
    if re.search(r"<code>\n[\s\S]*?</code>", req.system or ""):  # a filled block; the template may name the tags
        problems.append("system_has_code_block")
    if any(m.get("role") != "user" for m in req.messages):
        problems.append("unexpected_role")
    return problems
