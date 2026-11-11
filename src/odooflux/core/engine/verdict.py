"""Per-file output verdict (AD-05): VALID, INVALID or UNKNOWN for one candidate text.

The verdict is built from the layer-1 syntax validators that apply to the file.
- INVALID: a check actually failed. The edit is rejected and the original text is kept.
- VALID: every applicable check passed. The edit is kept.
- UNKNOWN: nothing failed, but no check could confirm the text (no validator for the format, or some check was
  UNAVAILABLE). The edit is kept and the uncertainty is reported; it is never claimed as verified.
A passing syntax check says nothing about semantic equivalence.
"""

from dataclasses import dataclass

VALID, INVALID, UNKNOWN = "VALID", "INVALID", "UNKNOWN"
NO_SYNTAX_CHECK = "no syntax check exists for this file format"


@dataclass(frozen=True)
class FileVerdict:
    status: str
    reason: str = ""

    @property
    def keep(self) -> bool:
        return self.status != INVALID

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason}


def judge_output(validators, path: str, text: str) -> FileVerdict:
    results = [v.validate(path, text) for v in validators if v.layer == 1 and v.applies_to(path)]
    failed = [r for r in results if r.outcome == "FAIL"]
    if failed:
        return FileVerdict(INVALID, failed[0].reason)
    if not results:
        return FileVerdict(UNKNOWN, NO_SYNTAX_CHECK)
    if all(r.outcome == "PASS" for r in results):
        return FileVerdict(VALID)
    gaps = sorted({r.reason for r in results if r.outcome != "PASS" and r.reason})
    return FileVerdict(UNKNOWN, "; ".join(gaps) or "a check did not run")
