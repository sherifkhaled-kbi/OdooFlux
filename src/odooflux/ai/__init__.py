"""Optional, provider-neutral AI assistance (feature 007, ADR-017).

AI is never on the critical path: nothing in this package runs unless the user enabled it, consented to
sending code and authorized a provider. The core imports nothing from here; the composition root
(``odooflux.builtins``) registers the escalation pass.
"""
