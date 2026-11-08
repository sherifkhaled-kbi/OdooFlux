"""Fix attribution by re-scan (FR-008, FR-016, R-04)."""


def resolved_by_rescan(before: list, after: list, key=lambda item: item.category) -> list:
    """
    Items of *before* that the re-scan no longer reports. Pairs are formed by key and line
    distance, closest pairs first; each post-fix item accounts for at most one pre-fix item, so a
    persisting item never counts as fixed. A moved finding is still found (by key and proximity).
    """
    pairs = sorted(
        ((abs(a.line - b.line), i, j)
         for i, b in enumerate(before) for j, a in enumerate(after) if key(a) == key(b)),
        key=lambda t: (t[0], t[1], t[2]))
    matched_before, matched_after = set(), set()
    for _distance, i, j in pairs:
        if i in matched_before or j in matched_after:
            continue
        matched_before.add(i)
        matched_after.add(j)
    return [item for i, item in enumerate(before) if i not in matched_before]


def status_by_rescan(before: list, after: list) -> dict:
    """Map finding id -> FIXED or OPEN, keyed by rule id (for the core Finding model)."""
    gone = {f.id for f in resolved_by_rescan(before, after, key=lambda f: f.rule_id)}
    return {f.id: ("FIXED" if f.id in gone else "OPEN") for f in before}
