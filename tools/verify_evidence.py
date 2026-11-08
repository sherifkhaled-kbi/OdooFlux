#!/usr/bin/env python3
"""Fetch-and-verify evidence records (stdlib only). Cache under /tmp/ev_cache.

Usage: verify_evidence.py EV-390 EV-391 ...   (or numeric ranges A-B via 390..396)
Checks per location: revision == pinned SHA for branch (official_sources/revisions.json);
present: file fetched at SHA, line range contains match (whitespace-normalised);
absent: 404 at SHA, or the match (regex, also with \\s restored if backslash was lost) has no hit.
Prints one JSON line per location with status OK / BAD_REVISION / EXCERPT_MISMATCH / ABSENT_FAIL.
"""
import hashlib, json, os, re, sys, urllib.request, urllib.error
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "odooflux", "knowledge")
CACHE = os.environ.get("EV_CACHE", "/tmp/ev_cache")  # set EV_CACHE to a fresh empty dir for no-cache verification
os.makedirs(CACHE, exist_ok=True)
norm = lambda s: re.sub(r"\s+", " ", s).strip()

def fetch(repo, sha, path):
    key = os.path.join(CACHE, hashlib.sha1(f"{repo}@{sha}:{path}".encode()).hexdigest())
    if os.path.exists(key):
        t = open(key, encoding="utf-8", errors="replace").read()
        return None if t == "\x00404" else t
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    try:
        t = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            open(key, "w").write("\x00404"); return None
        raise
    open(key, "w", encoding="utf-8").write(t)
    return t

def _valid(p):
    try: re.compile(p); return True
    except re.error: return False

def main(ids):
    revs = {(r["repository"], r["branch"]): r["revision"] for r in json.load(open(f"{ROOT}/official_sources/revisions.json"))}
    bad = 0
    for ev in ids:
        d = json.load(open(f"{ROOT}/evidence/{ev}.json"))
        for i, l in enumerate(d["locations"]):
            st, why = "OK", ""
            if revs.get((d["repository"], l["branch"])) != l["revision"]:
                st, why = "BAD_REVISION", f"pinned={revs.get((d['repository'], l['branch']))}"
            else:
                txt = fetch(d["repository"], l["revision"], l["path"])
                if l["kind"] == "absent":
                    if txt is None: pass
                    else:
                        pats = [l["match"], re.sub(r"(?<![\\\w])s\+", r"\\s+", l["match"])]
                        hit = None
                        for p in pats:
                            try: hit = re.search(p, txt, re.M) or hit
                            except re.error: pass
                        core = re.sub(r"^\^?(\\?s\+)?", "", l["match"])  # literal remainder of a (possibly backslash-mangled) regex
                        lit = core if len(core) > 3 else l["match"]
                        if hit or l["match"] in txt: st, why = "ABSENT_FAIL", "pattern found"
                        elif l["match"].startswith("^") and not re.match(r"\^s\+", l["match"]) and not _valid(l["match"]):
                            if any(x.startswith(l["match"][1:]) for x in txt.splitlines()): st, why = "ABSENT_FAIL", "line-anchored literal found"
                        elif (re.match(r"\^s\+", l["match"]) or not _valid(l["match"])) and norm(lit) in norm(txt): st, why = "ABSENT_FAIL", f"literal {lit!r} found (regex vacuous/over-narrow)"
                elif txt is None:
                    st, why = "EXCERPT_MISMATCH", "404"
                else:
                    lines = txt.splitlines(); ln = l["line"]
                    if not isinstance(ln, int): st, why = "EXCERPT_MISMATCH", "no line"
                    else:
                        # allow +/-0 only: exact line, plus joined neighbouring line for wrapped excerpts
                        w = norm(" ".join(lines[ln-1:ln+2]))
                        if norm(lines[ln-1]) and norm(l["match"]) in norm(lines[ln-1]): pass
                        elif norm(l["match"]) in w: st, why = "OK", "spans lines"
                        else:
                            near = [k+1 for k, x in enumerate(lines) if norm(l["match"]) in norm(x)]
                            st, why = "EXCERPT_MISMATCH", f"line {ln}: {norm(lines[ln-1])[:80]!r}; found at {near[:5]}"
            if st != "OK": bad += 1
            print(json.dumps({"ev": ev, "loc": i, "branch": l["branch"], "kind": l["kind"], "path": l["path"], "line": l["line"], "status": st, "why": why}))
    print("FAILURES", bad, file=sys.stderr)

if __name__ == "__main__":
    ids = []
    for a in sys.argv[1:]:
        m = re.fullmatch(r"(\d+)\.\.(\d+)", a)
        ids += [f"EV-{n}" for n in range(int(m[1]), int(m[2])+1)] if m else [a]
    main(ids)
