"""The single AI gateway (FR-016, FR-017, FR-020, FR-021, ADR-017).

Every AI operation goes through ``Gateway.complete``. In order it checks: the request names the selected provider and
model; the customer kill switch (external providers); the data-category authorization (external providers); the
sensitive-content filter and minimisation (every provider); the credential. Only then does the adapter run, with a
timeout and bounded retries of transient errors.

No fallback: a gateway holds exactly one provider. An error, a block or an exhausted budget returns an explicit error
response; no other provider is consulted. Nothing here logs a key, a prompt or a response, only provider, model,
token counts, attempts and outcome.
"""

import logging
import time
from dataclasses import dataclass, field

from odooflux.ai.authorization import Authorizer, minimise_violations, sensitive_kinds
from odooflux.ai.providers.catalog import CatalogError
from odooflux.ai.providers.credentials import load_credential
from odooflux.ai.providers.factory import build_provider
from odooflux.ai.providers.transport import call_with_retries
from odooflux.ai.providers.types import AIResponse, Usage, error_response
from odooflux.ai.usage.usage import compute_cost

log = logging.getLogger("odooflux.ai")


@dataclass
class GatewayConfig:
    provider: str
    model: str
    endpoint: str = ""
    grants: dict = field(default_factory=dict)  # provider -> categories
    kill_switch: bool = False
    max_retries: int = 2
    timeout_s: float = 60.0
    secrets_file: str = ""
    scanned_paths: tuple = ()
    fake_script: str = ""


class Gateway:
    def __init__(self, config: GatewayConfig, catalog, entry, descriptor, provider, credential, authorizer, sleep):
        self.config, self.catalog = config, catalog
        self.entry, self.descriptor = entry, descriptor
        self.provider, self.provider_name = provider, entry.name
        self._credential, self._authorizer, self._sleep = credential, authorizer, sleep

    # -- checks that run before any adapter is reached ------------------------------------------------------
    def _block(self, req):
        if req.provider != self.provider_name or req.model != self.config.model:
            return error_response("invalid_request", "request_does_not_match_selected_provider")
        external = self.entry.type == "external"
        if external and self.config.kill_switch:
            return error_response("transmission_disabled", "kill_switch")
        denied = self._authorizer.check(self.provider_name, self.entry.type, req.data_categories)
        if denied:
            missing = self._authorizer.missing(self.provider_name, req.data_categories)
            detail = "authorization:missing=" + ",".join(missing) if denied == "authorization_category_denied" and missing \
                else "authorization"
            return error_response(denied, detail)
        text = req.system + "\n" + "\n".join(m.get("content", "") for m in req.messages)
        if sensitive_kinds(text):
            return error_response("sensitive_content_excluded", "sensitive_content")
        problems = minimise_violations(req)
        if problems:
            return error_response("invalid_request", "minimisation:" + ",".join(problems))
        if external and self._credential is None:
            return error_response("auth", "credential_missing")
        return None

    def complete(self, req, *, on_attempt=None, before_retry=None) -> AIResponse:
        started = time.monotonic()
        blocked = self._block(req)
        attempts: list = []
        if blocked is not None:
            final = blocked
            final.attempts = 0  # nothing reached an adapter
        else:
            def attempt() -> AIResponse:
                try:
                    return self.provider.complete(req)
                except Exception as exc:  # noqa: BLE001  adapters should not raise; the text of an exception is dropped
                    return error_response("unknown", type(exc).__name__)

            def seen(resp: AIResponse) -> None:
                attempts.append(resp)
                if on_attempt is not None:
                    on_attempt(resp)

            final = call_with_retries(attempt, max_retries=self.config.max_retries, sleep=self._sleep,
                                      on_attempt=seen, before_retry=before_retry)
            final.usage = Usage(input=sum(a.usage.input for a in attempts), output=sum(a.usage.output for a in attempts),
                                cached=sum(a.usage.cached for a in attempts),
                                estimated=any(a.usage.estimated for a in attempts))
            final.attempts = len(attempts)
            final.cost = compute_cost(final.usage, self.descriptor.pricing)
        outcome = final.error_kind if final.stop_reason == "error" else final.stop_reason
        log.info("ai call provider=%s model=%s outcome=%s input_tokens=%d output_tokens=%d cached_tokens=%d "
                 "attempts=%d duration_ms=%d", self.provider_name, self.config.model, outcome, final.usage.input,
                 final.usage.output, final.usage.cached, final.attempts, int((time.monotonic() - started) * 1000))
        return final


def build_gateway(config: GatewayConfig, catalog, *, environ, transport_for=None, sleep=time.sleep) -> Gateway:
    """Resolve provider and model against the catalog (``CatalogError`` on failure) and build the one adapter.

    ``transport_for(provider_name)`` supplies a transport (tests); the default is the stdlib transport. Nothing is
    opened here.
    """
    entry, descriptor = catalog.resolve(config.provider, config.model, config.endpoint)
    credential = None
    if entry.credential_env:
        credential = load_credential(entry.credential_env, environ, secrets_file=config.secrets_file or None,
                                     scanned_paths=config.scanned_paths)
    script = None
    if entry.adapter == "fake" and config.fake_script:
        import json
        with open(config.fake_script, encoding="utf-8") as handle:
            script = json.load(handle)
    transport = transport_for(entry.name) if transport_for is not None else None
    provider = build_provider(entry, credential=credential, transport=transport,
                              timeout_s=config.timeout_s or entry.timeout_s or 60.0, fake_script=script)
    return Gateway(config, catalog, entry, descriptor, provider, credential, Authorizer(config.grants), sleep)


__all__ = ["Gateway", "GatewayConfig", "build_gateway", "CatalogError"]
