"""X Post Cleaner core logic, shipped in the xpc-bundle release and installed at
/workspace/xpc/scripts/xpc_core.py by the xpc-getting-started skill.

Implements the rules written in the xpc-* skills. No network access, no X calls,
no deletes, no owner data inside. Word lists live in ../data/wordlists.json
(uncensored on purpose: matching needs the real words; the Page shows slurs only
as a counted group). Dates use the owner's time zone: $XPC_TZ if set, otherwise
the computer's local zone.

CLI (all local, read-only on the archive):
  python3 xpc_core.py parse <archive.zip|folder|tweets.js ...> --own-id <numeric id> --out /workspace/xpc/state
  python3 xpc_core.py mask < text        # mask SSN-shaped numbers
  python3 xpc_core.py selftest
"""
from __future__ import annotations
import csv, glob, io, json, math, os, re, struct, unicodedata, zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__version__ = "1.1.0"


def owner_tz():
    """Owner's zone: $XPC_TZ (IANA name) if set and valid, else the computer's local zone."""
    cands = [os.environ.get("XPC_TZ", ""), os.environ.get("TZ", "").lstrip(":")]
    try:
        link = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in link:
            cands.append(link.split("zoneinfo/", 1)[1])
    except Exception:
        pass
    try:
        cands.append(open("/etc/timezone").read())
    except Exception:
        pass
    for name in cands:
        name = (name or "").strip()
        if name:
            try:
                return ZoneInfo(name)  # IANA zone: handles daylight saving
            except Exception:
                pass
    return datetime.now().astimezone().tzinfo  # last resort: fixed offset


TZ = owner_tz()
DATA_DIR = os.environ.get("XPC_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# ---------------------------------------------------------------- archive reading
WRAP_RE = re.compile(r"^\ufeff?\s*window(?:\.YTD\.[A-Za-z_]+\.part\d+|\[[^\]]*\](?:\.[A-Za-z_]+)*(?:\.part\d+)?)\s*=\s*", re.S)
WANT = ("data/tweets", "data/community-tweet", "data/note-tweet", "data/manifest", "data/like", "data/deleted-tweets")


def load_js_text(raw: str):
    """Return (items, warning). Tolerates BOM, CRLF, old/odd wrappers, no wrapper,
    a trailing ';', and truncation (salvages every complete record)."""
    raw = raw.lstrip("\ufeff")
    m = WRAP_RE.match(raw)
    body = raw[m.end():] if m else raw
    if not m:
        i = body.find("[")
        body = body[i:] if i >= 0 else ""
    body = body.strip().rstrip(";").strip()
    if not body:
        return [], "no data found (empty file or not an archive file)"
    try:
        data = json.loads(body)
        return (data if isinstance(data, list) else [data]), None
    except json.JSONDecodeError as e:
        dec = json.JSONDecoder(); out = []; i = body.find("[") + 1
        while 0 < i < len(body):
            while i < len(body) and body[i] in " \r\n\t,":
                i += 1
            try:
                obj, i = dec.raw_decode(body, i); out.append(obj)
            except Exception:
                break
        return out, f"file is cut off or damaged at character {e.pos}; saved {len(out)} complete records"


def scan_zip_bytes(b: bytes, want=WANT):
    """Local-header scan (works on partial downloads and data-descriptor entries).
    Returns {name: (text, complete)}."""
    got = {}; i = 0
    while True:
        i = b.find(b"PK\x03\x04", i)
        if i < 0 or i + 30 > len(b):
            break
        comp = struct.unpack("<H", b[i + 8:i + 10])[0]
        nlen, xlen = struct.unpack("<HH", b[i + 26:i + 30])
        name = b[i + 30:i + 30 + nlen].decode("utf-8", "replace")
        start = i + 30 + nlen + xlen
        if name.startswith(want) and name.endswith(".js"):
            if comp == 8:
                d = zlib.decompressobj(-15)
                try:
                    data = d.decompress(b[start:]); complete = d.eof
                except zlib.error:
                    data, complete = b"", False
            else:
                csize = struct.unpack("<I", b[i + 18:i + 22])[0]
                data = b[start:start + csize]; complete = csize > 0 and len(data) == csize
            got[name] = (data.decode("utf-8", "replace"), complete)
        i = start
    return got


def collect_sources(paths):
    """paths: a folder, .js files, and/or one or more ZIP parts (whole or partial).
    Returns {basename: (text, complete)} for every archive data file found in ANY part."""
    if isinstance(paths, str):
        paths = [paths]
    out = {}
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(glob.glob(os.path.join(p, "*.js")) + glob.glob(os.path.join(p, "data", "*.js"))):
                out[os.path.basename(f)] = (open(f, encoding="utf-8-sig", errors="replace").read(), True)
            zips = sorted(glob.glob(os.path.join(p, "*.zip")) + glob.glob(os.path.join(p, "*.zip.part")) + glob.glob(os.path.join(p, "*.zip.crdownload")))
            for z in zips:
                for k, v in scan_zip_bytes(open(z, "rb").read()).items():
                    nm = os.path.basename(k)
                    if nm not in out or (v[1] and not out[nm][1]):
                        out[nm] = v
        elif p.endswith(".js"):
            out[os.path.basename(p)] = (open(p, encoding="utf-8-sig", errors="replace").read(), True)
        else:
            for k, v in scan_zip_bytes(open(p, "rb").read()).items():
                nm = os.path.basename(k)
                if nm not in out or (v[1] and not out[nm][1]):
                    out[nm] = v
    return out


TWEET_FILE_RE = re.compile(r"^tweets(?:-part\d+)?\.js$")


def tweet_files(sources):
    def order(n):
        m = re.search(r"part(\d+)", n)
        return int(m.group(1)) if m else 0
    return sorted([n for n in sources if TWEET_FILE_RE.match(n)], key=order)


# ---------------------------------------------------------------- record fields
ID_RE = re.compile(r"^\d{1,20}$")


def parse_date(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%a %b %d %H:%M:%S %z %Y").astimezone(TZ)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).astimezone(TZ)
    except Exception:
        return None


def to_likes(v):
    """-> (int >= 0, note|None). '1.2K' -> 1200, negative -> 0, junk -> 0."""
    if isinstance(v, bool):
        return 0, "not a number"
    if isinstance(v, int):
        return (v, None) if v >= 0 else (0, "negative")
    if isinstance(v, float):
        return (int(v), None) if v >= 0 else (0, "negative")
    s = str(v if v is not None else "").strip().replace(",", "")
    if s == "":
        return 0, "missing"
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KkMm]?)", s)
    if not m:
        return 0, "not a number"
    n = int(float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()])
    return (n, None) if n >= 0 else (0, "negative")


def text_of(t):
    return t.get("full_text") or t.get("text") or ""


def classify(t, own_id):
    """post | reply | self_reply | quote | repost.
    A typed 'RT @' that earned likes is the owner's own post, not a repost (reposts show 0 likes)."""
    text = text_of(t)
    likes, _ = to_likes(t.get("favorite_count"))
    is_reply = bool(t.get("in_reply_to_status_id_str") or t.get("in_reply_to_status_id"))
    if text.startswith("RT @") and likes == 0 and not is_reply:
        return "repost"
    if is_reply:
        uid = str(t.get("in_reply_to_user_id_str") or t.get("in_reply_to_user_id") or "")
        return "self_reply" if own_id and uid == str(own_id) else "reply"
    if t.get("quoted_status_id_str") or t.get("quoted_status_id") or str(t.get("is_quote_status")).lower() == "true":
        return "quote"
    return "post"


def media_kinds(t):
    ms = (t.get("extended_entities") or {}).get("media") or (t.get("entities") or {}).get("media") or []
    return sorted({(m or {}).get("type") or "unknown" for m in ms})


LEADING_NAMES_RE = re.compile(r"^(?:\s*@\w{1,15})+\s*")


def typed_mentions(t):
    """@names the owner typed. In a reply, X adds EVERY name in the thread at the start,
    so the whole leading run of @names is automatic. Reposts have none."""
    text = text_of(t)
    if text.startswith("RT @"):
        return []
    if t.get("in_reply_to_status_id_str") or t.get("in_reply_to_status_id"):
        text = LEADING_NAMES_RE.sub("", text, count=1)
    return re.findall(r"(?<![\w@])@(\w{1,15})", text)


def normalize_records(items, src, own_id, seen, report, today):
    posts = []
    for n, it in enumerate(items):
        try:
            t = it.get("tweet") if isinstance(it, dict) else None
            if not isinstance(t, dict):
                report["skipped"].append({"where": f"{src} #{n}", "why": "not a post record"}); continue
            raw_id = t.get("id_str") if t.get("id_str") is not None else t.get("id")
            if isinstance(raw_id, float):
                report["skipped"].append({"where": f"{src} #{n}", "why": "id lost precision (number, not text)"}); continue
            tid = str(raw_id).strip() if raw_id is not None else ""
            if not ID_RE.match(tid):
                report["skipped"].append({"where": f"{src} #{n}", "why": f"bad id {tid[:24]!r}"}); continue
            if tid in seen:
                report["duplicates"] += 1; continue
            dt = parse_date(t.get("created_at"))
            date_note = None
            if dt is None:
                date_note = "date unreadable"
            elif dt > today + timedelta(days=1):
                date_note = "date in the future"
            likes, lnote = to_likes(t.get("favorite_count"))
            if lnote:
                report["fixed_fields"].append({"id": tid, "field": "likes", "note": lnote})
            typ = classify(t, own_id)
            seen.add(tid)
            posts.append({
                "id": tid, "created_at_dt": dt, "date_note": date_note, "text": text_of(t),
                "type": typ, "community": src.startswith("community"), "media_kinds": media_kinds(t),
                "favorite_count": likes, "in_reply_to": str(t.get("in_reply_to_status_id_str") or t.get("in_reply_to_status_id") or "") or None,
                "in_reply_to_screen_name": t.get("in_reply_to_screen_name"), "typed_mentions": typed_mentions(t),
                "repost_of": (re.match(r"^RT @(\w{1,15}):", text_of(t)) or [None, None])[1] if typ == "repost" else None,
                "src": src,
            })
            if date_note:
                report["date_issues"].append({"id": tid, "note": date_note})
        except Exception as e:  # never let one record stop the import
            report["skipped"].append({"where": f"{src} #{n}", "why": f"{type(e).__name__}"})
    return posts


def parse_archive(paths, own_id, today=None, manifest_count=None):
    """Read every tweets*.js (all parts, all ZIP parts) + community-tweet.js + note-tweet.js.
    Returns (posts, report). report['ready_for_review'] is False when files are partial
    or the parsed count doesn't match the manifest."""
    today = today or datetime.now(TZ)
    src = collect_sources(paths)
    report = {"files": {}, "skipped": [], "duplicates": 0, "fixed_fields": [], "date_issues": [],
              "partial": [], "manifest_count": manifest_count, "notes": {}}
    seen, posts = set(), []
    for name in tweet_files(src):
        text, complete = src[name]
        items, warn = load_js_text(text)
        report["files"][name] = {"records": len(items), "warning": warn, "complete": complete and not warn}
        if warn or not complete:
            report["partial"].append(name)
        posts += normalize_records(items, name, own_id, seen, report, today)
    if "community-tweet.js" in src:
        items, warn = load_js_text(src["community-tweet.js"][0])
        report["files"]["community-tweet.js"] = {"records": len(items), "warning": warn}
        posts += normalize_records(items, "community-tweet.js", own_id, seen, report, today)
    if "note-tweet.js" in src:
        notes, _ = load_js_text(src["note-tweet.js"][0])
        report["notes"] = match_notes(posts, notes)
    if manifest_count is None and "manifest.js" in src:
        try:
            man, _ = load_js_text(src["manifest.js"][0].replace("window.__THAR_CONFIG = ", "window.YTD.manifest.part0 = "))
            m = man[0] if man else {}
            manifest_count = int(((m.get("dataTypes") or {}).get("tweets") or {}).get("count") or 0) or None
        except Exception:
            manifest_count = None
    report["manifest_count"] = manifest_count
    n_tweets = sum(1 for p in posts if not p["community"])
    report["parsed_tweets"] = n_tweets
    report["count_mismatch"] = manifest_count is not None and manifest_count != n_tweets + report["duplicates"]
    report["ready_for_review"] = not report["partial"] and not report["count_mismatch"] and bool(tweet_files(src))
    return posts, report


def match_notes(posts, notes):
    """Long posts (note-tweets) share no id with their post. Match by created time (within 2 s)
    AND the post's visible text being the start of the note. Ambiguous or unmatched notes are
    reported, never guessed."""
    by_sec = {}
    for p in posts:
        if p["created_at_dt"]:
            by_sec.setdefault(int(p["created_at_dt"].timestamp()), []).append(p)
    merged, ambiguous, unmatched = [], [], []
    for n in notes:
        nt = (n or {}).get("noteTweet") or {}
        dt = parse_date(nt.get("createdAt") or "")
        ntext = ((nt.get("core") or {}).get("text") or "")
        if not dt:
            unmatched.append(nt.get("noteTweetId")); continue
        cands = []
        for d in range(-2, 3):
            for p in by_sec.get(int(dt.timestamp()) + d, []):
                core = re.sub(r"\s*https://t\.co/\w+\s*$", "", p["text"]).rstrip("….").strip()
                if core and ntext.startswith(core[:80]):
                    cands.append(p)
        if len(cands) == 1:
            cands[0]["text"] = ntext; cands[0]["note_tweet_id"] = str(nt.get("noteTweetId")); merged.append(cands[0]["id"])
        elif len(cands) > 1:
            ambiguous.append(str(nt.get("noteTweetId")))
        else:
            unmatched.append(str(nt.get("noteTweetId")))
    return {"merged": merged, "ambiguous": ambiguous, "unmatched": unmatched}


# ---------------------------------------------------------------- threads
def thread_roots(posts):
    """Full chain: every own post maps to the first post of its thread (following parents
    that are in the archive). When the chain leaves the archive, the missing parent id is the
    group key, so siblings under the same missing parent stay together."""
    by_id = {p["id"]: p for p in posts}
    root = {}
    for p in posts:
        chain, cur = [], p
        while True:
            if cur["id"] in root:
                r = root[cur["id"]]; break
            chain.append(cur["id"])
            par = cur.get("in_reply_to")
            if not par:
                r = cur["id"]; break
            if par not in by_id:
                r = f"parent:{par}"; break
            if par in chain:  # cycle guard
                r = par; break
            cur = by_id[par]
        for c in chain:
            root[c] = r
    return root


# ---------------------------------------------------------------- SSN masking
_SEP = r"[ \-\u2010\u2011\u2012\u2013\u2014\u2015.]"
SSN_RE = re.compile(rf"(?<![\d\w])(\d{{3}}){_SEP}?(\d{{2}}){_SEP}?(\d{{4}})(?![\d\w])")


def mask_ssn(text: str) -> str:
    """Every SSN-shaped number (dashed, spaced, en-dash, dotted, or 9 digits in a row)
    becomes ***-**-<its own last 4>. The full number is never printed."""
    if not text:
        return text
    return SSN_RE.sub(lambda m: f"***-**-{m.group(3)}", text)


# ---------------------------------------------------------------- profanity and slurs
_BUILTIN = {
    "strong": ["fuck", "shit", "bitch", "asshole", "bastard", "dick", "cunt", "motherfucker", "bullshit", "piss", "crap",
               "cock", "pussy", "whore", "slut"],
    "mild": ["wtf", "damn", "hell", "goddamn"],
    "slurs": ["nigger", "nigga", "faggot", "fag", "retard", "tranny", "kike", "spic", "chink", "wetback", "dyke", "coon"],
    "name_like": ["cock", "coon", "dick", "dyke"],
    "fighty": [], "giveaway": [],
}


def load_wordlists(path=None):
    """Lists from data/wordlists.json (the shipped, sha-checked file). Falls back to the
    built-in copy only if the file is missing or unreadable, and says so in WORDLIST_SOURCE."""
    path = path or os.path.join(DATA_DIR, "wordlists.json")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {k: d.get(k, v) for k, v in _BUILTIN.items()}, path
    except Exception:
        return dict(_BUILTIN), "builtin"


_WL, WORDLIST_SOURCE = load_wordlists()
STRONG = list(_WL["strong"])
MILD = list(_WL["mild"])
SLURS = list(_WL["slurs"])
NAME_LIKE = set(_WL["name_like"])  # also common surnames/names: skip "Dick Van Dyke"-style Title Case names
FIGHTY = list(_WL["fighty"])
GIVEAWAY = list(_WL["giveaway"])
SUFFIXES = ["", "s", "es", "ed", "er", "ers", "ing", "in", "y", "ty", "ies", "head", "heads", "face"]
LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "i"}
TOKEN_RE = re.compile(r"#?[\w@$!|*']+", re.U)


def _collapse(s):
    return re.sub(r"(.)\1+", r"\1", s)


def _norm_token(tok):
    tok = unicodedata.normalize("NFKC", tok)
    hashtag = tok.startswith("#")
    tok = tok.lstrip("#")
    tok = re.sub(r"^[^\w$@]+|[^\w*]+$", "", tok)  # trailing !!!, ..., quotes
    if not tok:
        return "", hashtag, []
    camel = re.findall(r"[A-Z][a-z]+|[a-z]+|[A-Z]+(?![a-z])", tok) if hashtag else []
    low = tok.lower()
    if re.search(r"[a-z]", low):
        low = "".join(LEET.get(c, c) for c in low)
    return low.strip("'"), hashtag, [c.lower() for c in camel]


def _forms(word):
    return {_collapse(word + s) for s in SUFFIXES}


_FORMS_CACHE = {}


def _word_forms(word):
    if word not in _FORMS_CACHE:
        _FORMS_CACHE[word] = _forms(word.lower())
    return _FORMS_CACHE[word]


_INDEX_CACHE = {}


def _index(words):
    key = tuple(words)
    if key not in _INDEX_CACHE:
        idx = {}
        for w in words:
            wl = w.lower().lstrip("#")
            if w.startswith("#"):
                continue
            for f in _word_forms(wl):
                idx.setdefault(f, []).append(w)
        _INDEX_CACHE[key] = idx
    return _INDEX_CACHE[key]


def find_words(text, words):
    """Whole-word matches (safe on 'class', 'assassin', 'Scunthorpe', 'cocktail') with
    case, common endings, number/symbol swaps (sh1t, a$$hole), repeated letters (fuuuck),
    * masks (f*ck, f**k), and words inside hashtags (#FuckMondays). Returns matched list words."""
    hits = []
    idx = _index(words)
    raw_tokens = TOKEN_RE.findall(text or "")
    for i, raw in enumerate(raw_tokens):
        tok, hashtag, camel = _norm_token(raw)
        if not tok:
            continue
        cands = []
        for p in [_collapse(tok)] + [_collapse(c) for c in camel]:
            cands += idx.get(p, [])
        if "*" in tok:
            pat = re.compile("^" + re.escape(tok).replace(r"\*", "[a-z]") + "$")
            cands += [w for w in words if not w.startswith("#") and any(pat.match(w.lower() + s) for s in SUFFIXES)]
        if hashtag:
            cands += [w for w in words if w.startswith("#") and tok == w.lower().lstrip("#")]
            cands += [w for w in words if not w.startswith("#") and len(w) >= 4 and (tok.startswith(w.lower()) or tok.endswith(w.lower()))]
        for w in cands:
            wl = w.lower().lstrip("#")
            if wl in NAME_LIKE and raw[:1].isupper() and raw[1:2].islower():
                prev = raw_tokens[i - 1] if i > 0 else ""; nxt = raw_tokens[i + 1] if i + 1 < len(raw_tokens) else ""
                if (i > 0 and prev[:1].isupper()) or nxt[:1].isupper():
                    continue  # looks like a name: "Dick Van Dyke"
            if w not in hits:
                hits.append(w)
    return hits


# ---------------------------------------------------------------- pace, budget, confirm, proof
DAILY_ACTIONS = {"steady": 100, "faster": 200, "fastest": 350}  # shared by deletes, unreposts, unlikes, retries, browser checks
PACE_DOWN = {"fastest": "faster", "faster": "steady", "steady": "steady"}
FAST_LANE_PER_DAY = 4000  # finish-date figure: ~42 per 15 minutes, under X's 50
TYPED_CONFIRM_SHARE = 0.5
TYPED_CONFIRM_COUNT = 10_000


def needs_typed_confirm(to_delete, scanned):
    return to_delete >= TYPED_CONFIRM_COUNT or (scanned > 0 and to_delete / scanned > TYPED_CONFIRM_SHARE)


def confirm_phrase(n):
    return f"DELETE {n:,} POSTS"


def typed_ok(typed, n):
    t = re.sub(r"\s+", " ", (typed or "").strip().upper())
    m = re.fullmatch(r"DELETE ([\d,\s]+) POSTS?", t)
    return bool(m) and int(re.sub(r"[,\s]", "", m.group(1)) or -1) == n


def finish_days(n, per_day):
    return 0 if n <= 0 else math.ceil(n / per_day)


def verified_gone(results):
    """results: {id: 'gone'|'already_gone'|'still_live'|'reappeared'|'unreachable'} for every id the run reached.
    Verified gone = gone + already gone, out of all attempted. Unreachable is listed, never counted as gone."""
    a = len(results)
    g = sum(1 for v in results.values() if v in ("gone", "already_gone"))
    u = sum(1 for v in results.values() if v == "unreachable")
    return {"attempted": a, "verified_gone": g, "still_live": a - g - u, "unreachable": u,
            "line": f"Verified gone: {g:,} of {a:,}. Still live: {a - g - u:,}." + (f" Couldn't check: {u:,}." if u else "")}


# ---------------------------------------------------------------- export
def csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def write_export_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in rows:
            out = []
            for k in fields:
                v = r.get(k)
                if k == "id":
                    v = f"=\"{v}\""  # keeps 19-digit ids as text in Excel/Sheets
                elif k == "text":
                    v = csv_safe(mask_ssn(v or ""))
                else:
                    v = csv_safe(v)
                out.append(v)
            w.writerow(out)


# ---------------------------------------------------------------- Worst 50 ordering (not a ban-risk score)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+1[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}(?!\d)")


def risk_rank(p):
    """Sort key for the Worst 50 sprint: personal-leak-like text, slurs, strong words,
    fighty replies, then low engagement, then oldest. Lower sorts first. Ordering only."""
    text = p.get("text") or ""
    low = text.lower()
    leak = bool(SSN_RE.search(text) or PHONE_RE.search(text) or EMAIL_RE.search(text))
    slur = bool(find_words(text, SLURS))
    strong = bool(find_words(text, STRONG))
    fighty = p.get("type") in ("reply", "self_reply") and any(f in low for f in FIGHTY)
    tier = 0 if leak else 1 if slur else 2 if strong else 3 if fighty else 4
    dt = p.get("created_at_dt")
    return (tier, p.get("favorite_count") or 0, dt.timestamp() if dt else 0)


# ---------------------------------------------------------------- CLI
def _post_row(p):
    r = dict(p)
    r["created_at"] = p["created_at_dt"].isoformat() if p.get("created_at_dt") else None
    r.pop("created_at_dt", None)
    return r


def _cli(argv=None):
    import argparse, sys
    ap = argparse.ArgumentParser(prog="xpc_core.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("parse", help="archive -> posts.jsonl + import_meta.json (local only)")
    pa.add_argument("paths", nargs="+")
    pa.add_argument("--own-id", required=True, help="the signed-in account's numeric X id")
    pa.add_argument("--out", default="/workspace/xpc/state")
    sub.add_parser("mask", help="mask SSN-shaped numbers in stdin")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "mask":
        sys.stdout.write(mask_ssn(sys.stdin.read())); return 0
    if a.cmd == "selftest":
        assert mask_ssn("id 123-45-6789 / 123 45 6789 / 123456789") == "id ***-**-6789 / ***-**-6789 / ***-**-6789"
        assert find_words("sh1t happens", STRONG) and not find_words("classic assassin cocktail", STRONG)
        assert typed_ok("delete 1,234 posts", 1234) and not typed_ok("yes", 1234)
        print(f"xpc_core {__version__} selftest ok · tz={TZ} · wordlists={WORDLIST_SOURCE}"); return 0
    os.makedirs(a.out, exist_ok=True)
    posts, report = parse_archive(a.paths, a.own_id)
    with open(os.path.join(a.out, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(_post_row(p), ensure_ascii=False) + "\n")
    counts = {}
    for p in posts:
        k = "community" if p["community"] else p["type"]
        counts[k] = counts.get(k, 0) + 1
    meta = {"xpc_core": __version__, "parsed_at": datetime.now(TZ).isoformat(), "tz": str(TZ),
            "counts_by_type": counts, "total": len(posts),
            "own_media": sum(1 for p in posts if p["media_kinds"] and p["type"] != "repost"), **report}
    with open(os.path.join(a.out, "import_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"total": len(posts), "counts_by_type": counts, "ready_for_review": report["ready_for_review"],
                      "partial": report["partial"], "count_mismatch": report["count_mismatch"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
