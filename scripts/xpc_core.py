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
  python3 xpc_core.py page-steps                     # list the Page build steps (first page, then background)
  python3 xpc_core.py page-steps --show 1 --part K   # step 1 (first page) text, part K
  python3 xpc_core.py page-steps --show N            # step N's EditCanvas edits (JSON), nothing else
  python3 xpc_core.py page-verify <file> [--after N] # check a ReadCanvas result against the expected source
  python3 xpc_core.py page-where <file>              # which step a ReadCanvas result is at (resume)
  python3 xpc_core.py page-status --tone info --lead "..." --text "..."
                                                 # exact PAGE_STATUS edit (SSNs masked); --apply <file> writes it
"""
from __future__ import annotations
import csv, glob, hashlib, io, json, math, os, re, struct, unicodedata, zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__version__ = "1.1.3"


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


# ---------------------------------------------------------------- Page build in stages
# The canvas holds page.min.tsx (page.canvas.tsx with comments and spare whitespace removed;
# see tools/shrink_page.js). It is built in three stages so the owner sees a working page fast:
#   step 1      WriteCanvas: the FIRST page (page/01-first.tsx). Sign in, Get your archive, and the
#               shared header, stepper and styles. Pick, Review and Run show as locked steps.
#               Each left-out part is a stub plus a marker line, chosen by tools/stage_plan.js
#               (page/regions.json), never by hand.
#   phase A     EditCanvas steps that fill the Pick screen's parts, then one finish step.
#   phase B     EditCanvas steps that fill Review, Run and the post-only helpers, then one finish.
# Filled text goes in as line comments ("//~" lines for A, "//^" for B), so every step compiles;
# each finish removes that phase's stubs, markers and comment prefixes in one EditCanvas call.
# After phase B the canvas is page.min.tsx byte for byte.
PAGE_CHUNK_MAX = 9500  # bytes per step as printed: one Shell or Read view shows it whole
PAGE_PHASES = {
    "A": {"P": "//~", "N": "//=", "open": "/*@A*/", "close": "/*@@A*/"},
    "B": {"P": "//^", "N": "//!", "open": "/*@B*/", "close": "/*@@B*/"},
}
PAGE_RESERVED = ("\n//", "@@", "/*@", "\u2028", "\u2029", "\r")
BUNDLE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _page_paths(bundle_dir=BUNDLE_DIR):
    return os.path.join(bundle_dir, "page.min.tsx"), os.path.join(bundle_dir, "page")


def _close(ph, r):
    # regions whose stub ends in a brace get their own closing token, so removing one kind of
    # closing marker can never eat a brace that belongs to the page
    return ph["close"] if not r["tail"] else ph["close"][:-2] + "c*/"


def _apply_edits(cur, edits):
    for e in edits:
        n = cur.count(e["old_string"])
        if e.get("replace_all"):
            assert n >= 1, ("no match", e["old_string"][:40])
            cur = cur.replace(e["old_string"], e["new_string"])
        else:
            assert n == 1, ("must match once", n, e["old_string"][:40])
            cur = cur.replace(e["old_string"], e["new_string"], 1)
    return cur


def page_plan(src, regions, limit=PAGE_CHUNK_MAX):
    """(first_page_text, steps). steps: list of {"phase","kind":"fill"|"finish","edits":[...]}."""
    for bad in PAGE_RESERVED:
        assert bad not in src, f"page.min.tsx contains reserved {bad!r}"
    first, pos = [], 0
    for k, r in enumerate(regions):
        ph = PAGE_PHASES[r["phase"]]
        first.append(src[pos:r["start"]])
        first.append(r["stub"] + ph["open"] + "\n" + ph["P"] + f"@@{k}@@" + "\n" + _close(ph, r) + r["tail"])
        pos = r["end"]
    first.append(src[pos:])
    first = "".join(first)
    steps = []
    for phase in ("A", "B"):
        ph = PAGE_PHASES[phase]
        cur_edits, cur_size = [], 0
        def flush():
            nonlocal cur_edits, cur_size
            if cur_edits:
                steps.append({"phase": phase, "kind": "fill", "edits": cur_edits})
            cur_edits, cur_size = [], 0
        for k, r in enumerate(regions):
            if r["phase"] != phase:
                continue
            body = src[r["start"]:r["end"]]
            marker = ph["P"] + f"@@{k}@@"
            enc = lambda t: t.replace("\n", "\n" + ph["N"])
            jl = lambda t: len(json.dumps(t, ensure_ascii=False).encode())
            i = 0
            while i < len(body):
                room = limit - cur_size - 2 * len(marker) - 80
                if room < 600:
                    flush(); continue
                lo, hi = i + 1, len(body)
                if jl(enc(body[i:lo])) > room:
                    flush(); continue
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if jl(enc(body[i:mid])) <= room:
                        lo = mid
                    else:
                        hi = mid - 1
                piece, i = body[i:lo], lo
                new = ph["P"] + enc(piece) + ("" if i >= len(body) else "\n" + marker)
                e = {"old_string": marker, "new_string": new}
                cur_edits.append(e)
                cur_size += jl(e["new_string"]) + jl(marker) + 40
        flush()
        heads, tails = set(), set()
        for r in regions:
            if r["phase"] == phase:
                heads.add(r["stub"] + ph["open"] + "\n" + ph["P"])
                tails.add("\n" + _close(ph, r) + r["tail"])
        fin = [{"old_string": h, "new_string": "", "replace_all": True} for h in sorted(heads, key=lambda x: (-len(x), x))]
        fin += [{"old_string": t, "new_string": "", "replace_all": True} for t in sorted(tails, key=lambda x: (-len(x), x))]
        fin.append({"old_string": "\n" + ph["P"], "new_string": "", "replace_all": True})
        steps.append({"phase": phase, "kind": "finish", "edits": fin})
    return first, steps


def page_states(first, steps):
    """Exact source after each step: index 1 = first page, index n = after step n."""
    states = [None, first]
    cur = first
    for st in steps:
        edits = st["edits"]
        if st["kind"] == "finish":
            ph = PAGE_PHASES[st["phase"]]
            if ("\n" + ph["N"]) in cur:
                edits = edits + [{"old_string": "\n" + ph["N"], "new_string": "\n", "replace_all": True}]
                st["edits"] = edits
        cur = _apply_edits(cur, edits)
        states.append(cur)
    return states


def page_build_files(bundle_dir=BUNDLE_DIR, limit=PAGE_CHUNK_MAX):
    """Release-time: from page.min.tsx and page/regions.json write page/01-first.tsx, page/NN.json
    (EditCanvas edits for step NN) and page/plan.json; prove the steps end at page.min.tsx."""
    src_path, d = _page_paths(bundle_dir)
    src = open(src_path, encoding="utf-8").read()
    regions = json.load(open(os.path.join(d, "regions.json"), encoding="utf-8"))["regions"]
    first, steps = page_plan(src, regions, limit)
    states = page_states(first, steps)
    assert states[-1] == src, "staged build does not end at page.min.tsx"
    for f in glob.glob(os.path.join(d, "[0-9][0-9]*")):
        os.remove(f)
    open(os.path.join(d, "01-first.tsx"), "w", encoding="utf-8", newline="").write(first)
    plan = {"result": "page.min.tsx", "result_sha256": hashlib.sha256(src.encode()).hexdigest(),
            "first_page_bytes": len(first.encode()), "steps": [{"step": 1, "tool": "WriteCanvas", "stage": "first page",
            "file": "page/01-first.tsx", "bytes": len(first.encode()), "sha256_after": hashlib.sha256(first.encode()).hexdigest()}]}
    for n, st in enumerate(steps, 2):
        name = f"{n:02d}.json"
        body = json.dumps(st["edits"], ensure_ascii=False, indent=0)
        open(os.path.join(d, name), "w", encoding="utf-8", newline="").write(body)
        stage = ("Pick screen" if st["phase"] == "A" else "Review and Run") + (" finish" if st["kind"] == "finish" else "")
        plan["steps"].append({"step": n, "tool": "EditCanvas", "stage": stage, "phase": st["phase"], "kind": st["kind"],
                              "file": "page/" + name, "bytes": len(body.encode()), "edits": len(st["edits"]),
                              "sha256_after": hashlib.sha256(states[n].encode()).hexdigest()})
    plan["pick_ready_after"] = max(s["step"] for s in plan["steps"] if s.get("phase") == "A")
    plan["full_page_after"] = plan["steps"][-1]["step"]
    json.dump(plan, open(os.path.join(d, "plan.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return plan


def page_steps(bundle_dir=BUNDLE_DIR):
    return json.load(open(os.path.join(_page_paths(bundle_dir)[1], "plan.json"), encoding="utf-8"))


def page_show(n, part=None, bundle_dir=BUNDLE_DIR, limit=PAGE_CHUNK_MAX):
    """Exact text for step n. Step 1 is long, so it prints in parts (--part 1, 2, ...): the
    WriteCanvas contents are the parts joined with nothing between them."""
    plan = page_steps(bundle_dir)
    st = plan["steps"][n - 1]
    text = open(os.path.join(bundle_dir, st["file"]), encoding="utf-8").read()
    if n != 1:
        return text
    parts, cur, size = [], [], 0
    for ch in text:
        b = len(ch.encode())
        if size + b > limit:
            parts.append("".join(cur)); cur, size = [], 0
        cur.append(ch); size += b
    parts.append("".join(cur))
    if part is None:
        return f"step 1 has {len(parts)} parts: print each with --part N and join them with nothing between\n"
    return parts[part - 1]


# Boot lines the bot may rewrite with a one-line edit. page-verify and page-where put them
# back before comparing, so a status or starting-step edit does not fail the build check.
PAGE_BOOT_DEFAULTS = (
    ("START_STEP", '"signin"'),
    ("START_PHASE", '"choose"'),
    ("START_RUN", '"idle"'),
    ("SIGNED_IN_HANDLE", '""'),
    ("PAGE_STATUS", "null"),
)
PAGE_STATUS_TONES = ("info", "warn", "error", "ok")


def _stmt_end(src, k):
    quote = None
    esc = False
    depth = 0
    while k < len(src):
        c = src[k]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        else:
            if c in "\"'`":
                quote = c
            elif c in "({[":
                depth += 1
            elif c in ")}]":
                depth = max(0, depth - 1)
            elif c == ";" and depth == 0:
                return k
        k += 1
    return None


def _const_decl(src, name):
    """(start, equals, semicolon) of `const name...;` or None."""
    key = f"const {name}"
    i = 0
    while True:
        i = src.find(key, i)
        if i < 0:
            return None
        before_ok = i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")
        nxt = i + len(key)
        after_ok = nxt >= len(src) or not (src[nxt].isalnum() or src[nxt] == "_")
        if before_ok and after_ok:
            eq = src.find("=", nxt)
            if eq < 0:
                return None
            end = _stmt_end(src, eq + 1)
            if end is None:
                return None
            return i, eq, end
        i += len(key)


def _set_const_initializer(src, name, expr):
    span = _const_decl(src, name)
    if span is None:
        return src
    _i, eq, end = span
    return src[:eq + 1] + expr + src[end:]


def normalize_page_boot(src):
    """Reset START_STEP, START_PHASE, START_RUN, SIGNED_IN_HANDLE, and PAGE_STATUS."""
    if src is None:
        return None
    for name, expr in PAGE_BOOT_DEFAULTS:
        src = _set_const_initializer(src, name, expr)
    return src


def _ts_string(text):
    out = ['"']
    for ch in text or "":
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def page_status_expr(tone=None, lead="", text=""):
    """Initializer for PAGE_STATUS. Empty lead and text (after SSN masking) is null, which hides the banner."""
    lead_m = mask_ssn(lead or "")
    text_m = mask_ssn(text or "")
    if tone is None or (lead_m == "" and text_m == ""):
        return "null"
    if tone not in PAGE_STATUS_TONES:
        raise ValueError("tone must be info, warn, error, or ok")
    return '{tone:"' + tone + '",lead:' + _ts_string(lead_m) + ",text:" + _ts_string(text_m) + "}"


def _page_status_decl(bundle_dir=BUNDLE_DIR):
    src = open(_page_paths(bundle_dir)[0], encoding="utf-8").read()
    span = _const_decl(src, "PAGE_STATUS")
    if span is None:
        raise ValueError("PAGE_STATUS is not in page.min.tsx")
    return src, span


def page_status_edit(tone=None, lead="", text="", bundle_dir=BUNDLE_DIR):
    """EditCanvas edit from the shipped PAGE_STATUS line to the masked value.
    old_string is the whole shipped declaration; new_string keeps that declaration and replaces the initializer."""
    src, (i, eq, end) = _page_status_decl(bundle_dir)
    expr = page_status_expr(tone, lead, text)
    return {"old_string": src[i:end + 1], "new_string": src[i:eq + 1] + expr + ";"}


def apply_page_status(src, tone=None, lead="", text=""):
    if _const_decl(src, "PAGE_STATUS") is None:
        raise ValueError("PAGE_STATUS declaration not found")
    return _set_const_initializer(src, "PAGE_STATUS", page_status_expr(tone, lead, text))


def _canvas_source(raw):
    """Source text from a saved ReadCanvas result (tool wrapper and header stripped) or a plain file."""
    i = raw.find("import")
    if i < 0:
        return None
    src = raw[i:]
    j = src.rfind("</cursor_untrusted")
    if j >= 0:
        src = src[:j]
    return src.rstrip()


def page_expected(after=None, bundle_dir=BUNDLE_DIR):
    """Exact source the canvas should hold after step `after` (None = finished page)."""
    src_path, d = _page_paths(bundle_dir)
    if after is None:
        return open(src_path, encoding="utf-8").read()
    plan = page_steps(bundle_dir)
    cur = open(os.path.join(d, "01-first.tsx"), encoding="utf-8").read()
    for st in plan["steps"][1:after]:
        cur = _apply_edits(cur, json.load(open(os.path.join(bundle_dir, st["file"]), encoding="utf-8")))
    return cur


def page_verify(path, after=None, bundle_dir=BUNDLE_DIR):
    """(ok, detail). ok when the saved ReadCanvas result at `path` holds exactly the source
    expected after step `after` (default: the finished page.min.tsx)."""
    want_full = page_expected(after, bundle_dir)
    want = normalize_page_boot(want_full).rstrip()
    got = normalize_page_boot(_canvas_source(open(path, encoding="utf-8").read()))
    if got is None:
        return False, "no canvas source found in file"
    if got == want:
        return True, hashlib.sha256(want_full.encode()).hexdigest()
    n, m = 0, min(len(got), len(want))
    while n < m and got[n] == want[n]:
        n += 1
    return False, f"first difference at character {n}: expected {want[n:n+60]!r}, canvas has {got[n:n+60]!r}"


def page_where(path, bundle_dir=BUNDLE_DIR):
    """Which step the canvas at `path` is at (to resume), or None."""
    got = normalize_page_boot(_canvas_source(open(path, encoding="utf-8").read()))
    plan = page_steps(bundle_dir)
    for st in reversed(plan["steps"]):
        if got is not None and page_expected(st["step"], bundle_dir).rstrip() == got:
            return st["step"]
    return None

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
    ps = sub.add_parser("page-steps", help="the Page build steps")
    ps.add_argument("--show", type=int, help="print only this step's exact text")
    ps.add_argument("--part", type=int, help="step 1 only: which part to print")
    pv = sub.add_parser("page-verify", help="check a ReadCanvas result")
    pv.add_argument("file")
    pv.add_argument("--after", type=int, help="check the state after this build step instead of the finished page")
    pw = sub.add_parser("page-where", help="which build step a saved ReadCanvas result is at")
    pw.add_argument("file")
    sub.add_parser("page-build", help="release-time: regenerate page/ from page.min.tsx and page/regions.json")
    pst = sub.add_parser("page-status", help="exact PAGE_STATUS edit; SSN-shaped numbers are masked")
    pst.add_argument("--tone", choices=list(PAGE_STATUS_TONES))
    pst.add_argument("--lead", default="")
    pst.add_argument("--text", default="")
    pst.add_argument("--clear", action="store_true", help="hide the banner (PAGE_STATUS = null)")
    pst.add_argument("--apply", metavar="FILE", help="write the edit into this canvas file")
    a = ap.parse_args(argv)
    if a.cmd == "page-build":
        plan = page_build_files()
        print(f"page-build ok: first page {plan['first_page_bytes']} bytes, {len(plan['steps'])} steps, pick ready after step {plan['pick_ready_after']}, full page after step {plan['full_page_after']}"); return 0
    if a.cmd == "page-steps":
        if a.show is None:
            plan = page_steps()
            print(json.dumps([{k: v for k, v in st.items() if k != "sha256_after"} for st in plan["steps"]], indent=1)); return 0
        sys.stdout.write(page_show(a.show, a.part)); return 0
    if a.cmd == "page-verify":
        ok, detail = page_verify(a.file, a.after)
        print(f"page-verify ok {detail}" if ok else f"page-verify MISMATCH {detail}"); return 0 if ok else 1
    if a.cmd == "page-where":
        w = page_where(a.file)
        print(f"page-where step {w}" if w else "page-where unknown (not at any build step)"); return 0 if w else 1
    if a.cmd == "page-status":
        if not a.clear and not a.tone and not a.lead and not a.text and not a.apply:
            _src, (i, _eq, end) = _page_status_decl()
            sys.stdout.write(_src[i:end + 1] + "\n"); return 0
        if not a.clear and not a.tone:
            print("page-status needs --tone or --clear"); return 1
        tone = None if a.clear else a.tone
        edit = page_status_edit(tone, a.lead, a.text)
        if a.apply:
            raw = open(a.apply, encoding="utf-8").read()
            open(a.apply, "w", encoding="utf-8", newline="").write(apply_page_status(raw, tone, a.lead, a.text))
        print(json.dumps(edit, ensure_ascii=False)); return 0
    if a.cmd == "mask":
        sys.stdout.write(mask_ssn(sys.stdin.read())); return 0
    if a.cmd == "selftest":
        assert mask_ssn("id 123-45-6789 / 123 45 6789 / 123456789") == "id ***-**-6789 / ***-**-6789 / ***-**-6789"
        assert find_words("sh1t happens", STRONG) and not find_words("classic assassin cocktail", STRONG)
        assert typed_ok("delete 1,234 posts", 1234) and not typed_ok("yes", 1234)
        shipped = page_status_edit(None)["old_string"]
        assert shipped.startswith("const PAGE_STATUS:") and shipped.endswith("=null;")
        edit = page_status_edit("warn", 'he said "no"\n123-45-6789', "id 123456789")
        assert edit["old_string"] == shipped
        assert "123-45-6789" not in edit["new_string"] and "123456789" not in edit["new_string"]
        assert "***-**-6789" in edit["new_string"] and '\\"no\\"' in edit["new_string"] and "\\n" in edit["new_string"]
        assert edit["new_string"].startswith(shipped[:shipped.rindex("=") + 1])
        assert page_status_expr("info", "", "") == "null"
        base = open(_page_paths()[0], encoding="utf-8").read()
        changed = apply_page_status(base, "error", "123 45 6789", "still here")
        changed = _set_const_initializer(changed, "START_STEP", '"pick"')
        changed = _set_const_initializer(changed, "SIGNED_IN_HANDLE", '"owner"')
        assert "123 45 6789" not in changed and "***-**-6789" in changed
        assert normalize_page_boot(changed) == base
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
