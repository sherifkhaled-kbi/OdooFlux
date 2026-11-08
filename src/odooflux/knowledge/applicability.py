"""Version applicability helpers (ADR-007): Online releases map to the next on-premise major."""


def on_premise_major(version: str):
    """Return (on-premise version, changed). An Online release x.n (n > 0) maps to (x+1).0."""
    major, minor = version.split(".")
    if minor == "0":
        return version, False
    return f"{int(major) + 1}.0", True
