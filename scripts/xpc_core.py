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
  python3 xpc_core.py page-steps --show 1 --part K --start archive --handle HANDLE
                                                 # same, already on the archive step with the handle filled
  python3 xpc_core.py page-steps --show N            # step N's EditCanvas edits (JSON), nothing else
  python3 xpc_core.py page-state --start archive --handle HANDLE --run running
                                                 # exact boot-line edits, including START_RUN
  python3 xpc_core.py page-state --qa era --kept id1,id2 --lane free --pace steady --cooling on
                                                 # load rules, kept ids, lane, pace, cooling-off
  python3 xpc_core.py page-state --deleted 10 --verified 8 --left 2 --unchecked 1 --likes 40
  python3 xpc_core.py verdict posts.jsonl [--rules rules.json | --qa everything] [--handle HANDLE]
  python3 xpc_core.py page-pool posts.jsonl [--qa everything] [--handle HANDLE]
                                                 # EditCanvas payloads, each <= 20000 bytes
  python3 xpc_core.py export posts.jsonl --out list.csv [--qa everything]
  python3 xpc_core.py export-check list.csv      # row count, exact ids, unwrap ="id"
  python3 xpc_core.py page-verify <file> [--after N] # check a ReadCanvas result against the expected source
  python3 xpc_core.py page-where <file>              # which step a ReadCanvas result is at (resume)
  python3 xpc_core.py page-status --tone info --lead "..." --text "..."
                                                 # exact PAGE_STATUS edit (SSNs masked); --apply <file> writes it
  python3 xpc_core.py page-typecheck             # tsc --strict on every build step
"""
from __future__ import annotations
import csv, glob, hashlib, io, json, math, os, re, struct, unicodedata, zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__version__ = "1.1.6"

NODE_TOOLS_DEFAULT = "/workspace/xpc-node-tools"
NODE_TOOL_PACKAGES = ("typescript@5.6.3", "esbuild@0.28.2", "@types/react@18.3.18")


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
    skipped_tweets = sum(1 for s in report["skipped"] if not str(s.get("where") or "").startswith("community"))
    report["skipped_counted"] = skipped_tweets
    report["unreadable"] = len(report["date_issues"]) + skipped_tweets
    accounted = n_tweets + report["duplicates"] + skipped_tweets
    report["accounted"] = accounted
    report["count_mismatch"] = manifest_count is not None and manifest_count != accounted
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
        out = {k: d.get(k, v) for k, v in _BUILTIN.items()}
        out["suffixes"] = list(d.get("suffixes") or ["", "s", "es", "ed", "er", "ers", "ing", "in", "y", "ty", "ies", "head", "heads", "face"])
        return out, path
    except Exception:
        builtin = dict(_BUILTIN)
        builtin["suffixes"] = ["", "s", "es", "ed", "er", "ers", "ing", "in", "y", "ty", "ies", "head", "heads", "face"]
        return builtin, "builtin"


_WL, WORDLIST_SOURCE = load_wordlists()
STRONG = list(_WL["strong"])
MILD = list(_WL["mild"])
SLURS = list(_WL["slurs"])
NAME_LIKE = set(_WL["name_like"])  # also common surnames/names: skip "Dick Van Dyke"-style Title Case names
FIGHTY = list(_WL["fighty"])
GIVEAWAY = list(_WL["giveaway"])
SUFFIXES = list(_WL["suffixes"])
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


def needs_typed_confirm(to_delete, scanned, delete_everything=False):
    """Delete everything always needs the typed phrase, and so does a large or majority cleanup."""
    if to_delete <= 0:
        return False
    if delete_everything:
        return True
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
                else:
                    v = csv_safe(mask_ssn("" if v is None else str(v)))
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


def page_step_sources(bundle_dir=BUNDLE_DIR):
    """(step_number, source) for the first page, each later step, and the finished page."""
    src_path, d = _page_paths(bundle_dir)
    src = open(src_path, encoding="utf-8").read()
    regions = json.load(open(os.path.join(d, "regions.json"), encoding="utf-8"))["regions"]
    first, steps = page_plan(src, regions)
    states = page_states(first, steps)
    if states[-1] != src:
        raise AssertionError("staged build does not end at page.min.tsx")
    return [(n, text) for n, text in enumerate(states) if text is not None]


def node_tools_dir():
    return os.environ.get("XPC_NODE_TOOLS") or NODE_TOOLS_DEFAULT


def ensure_node_tools():
    """(dir, ready). Use XPC_NODE_TOOLS or /workspace/xpc-node-tools. Install the pinned
    packages there if they are missing. If node or npm cannot do that, return ready False
    so the type-check is skipped instead of stalling the first run."""
    import subprocess
    d = node_tools_dir()
    tsc = os.path.join(d, "node_modules", "typescript", "bin", "tsc")
    react = os.path.join(d, "node_modules", "@types", "react", "package.json")
    if os.path.isfile(tsc) and os.path.isfile(react):
        os.environ["XPC_NODE_TOOLS"] = d
        return d, True
    try:
        os.makedirs(d, exist_ok=True)
        proc = subprocess.run(["npm", "i", "--prefix", d, "--silent", *NODE_TOOL_PACKAGES], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return d, False
    ready = proc.returncode == 0 and os.path.isfile(tsc) and os.path.isfile(react)
    if ready:
        os.environ["XPC_NODE_TOOLS"] = d
    return d, ready


def apply_page_boot(src, start=None, handle=None, phase=None):
    """First-write variant: START_STEP, SIGNED_IN_HANDLE, and START_PHASE already set.
    Empty handle leaves the default. phase is grabbing, waiting, or ready while the bot fetches."""
    if start:
        src = _set_const_initializer(src, "START_STEP", '"' + start + '"')
    if handle:
        src = _set_const_initializer(src, "SIGNED_IN_HANDLE", _ts_string(mask_ssn(handle)))
    if phase:
        src = _set_const_initializer(src, "START_PHASE", '"' + phase + '"')
    return src


def page_typecheck(bundle_dir=BUNDLE_DIR):
    """tsc --strict (React types) on every build step, plus a step-1 page that already
    starts at archive with a handle. Returns (exit_code, output). Skips if the tools
    cannot be installed."""
    import subprocess, tempfile
    tools, ready = ensure_node_tools()
    if not ready:
        return 0, f"page-typecheck skipped: typescript and @types/react are not available in {tools}\n"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "typecheck_page.js")
    tmp = tempfile.mkdtemp(prefix="xpc-steps-")
    paths = []
    first = None
    for n, text in page_step_sources(bundle_dir):
        path = os.path.join(tmp, f"step-{n:02d}.tsx")
        open(path, "w", encoding="utf-8", newline="").write(text)
        paths.append(path)
        if n == 1:
            first = text
    if first is not None:
        path = os.path.join(tmp, "step-01-archive.tsx")
        open(path, "w", encoding="utf-8", newline="").write(apply_page_boot(first, "archive", "example", "grabbing"))
        paths.append(path)
        path = os.path.join(tmp, "step-01-ready.tsx")
        open(path, "w", encoding="utf-8", newline="").write(apply_page_boot(first, "archive", "example", "ready"))
        paths.append(path)
    env = os.environ.copy()
    env["XPC_NODE_TOOLS"] = tools
    proc = subprocess.run(["node", script, *paths], capture_output=True, text=True, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def page_steps(bundle_dir=BUNDLE_DIR):
    return json.load(open(os.path.join(_page_paths(bundle_dir)[1], "plan.json"), encoding="utf-8"))


def page_show(n, part=None, bundle_dir=BUNDLE_DIR, limit=PAGE_CHUNK_MAX, start=None, handle=None, phase=None):
    """Exact text for step n. Step 1 is long, so it prints in parts (--part 1, 2, ...): the
    WriteCanvas contents are the parts joined with nothing between them.
    --start, --handle, and --phase rewrite the boot lines before the first page is split,
    so the first write can open on the archive step already fetching."""
    plan = page_steps(bundle_dir)
    st = plan["steps"][n - 1]
    text = open(os.path.join(bundle_dir, st["file"]), encoding="utf-8").read()
    if n == 1 and (start or handle or phase):
        text = apply_page_boot(text, start, handle, phase)
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


PAGE_DATA_CONSTS = (
    "POOL", "ARCHIVE_CAPS", "ARCHIVE_POST_COUNT", "PROFILE_POST_COUNT_LABEL",
    "LOADED_RULES", "LOADED_QA", "LOADED_KEPT", "LOADED_LANE", "LOADED_PACE",
    "LOADED_COOLING", "LOADED_FAILED", "LOADED_DELETED", "LOADED_VERIFIED",
    "LOADED_LEFT", "LOADED_UNCHECKED", "LOADED_LIKES", "LOADED_TOTALS",
)


def normalize_page_boot(src, canonical=None):
    """Reset boot lines and loaded archive data so verify still matches the shipped page.
    POOL, archive caps, profile counts, and the LOADED_* constants are put back to the
    shipped initializers. Rules the owner edits with Clear all rules stay in BASE."""
    if src is None:
        return None
    for name, expr in PAGE_BOOT_DEFAULTS:
        src = _set_const_initializer(src, name, expr)
    if canonical is None:
        canonical = open(_page_paths()[0], encoding="utf-8").read()
    for name in PAGE_DATA_CONSTS:
        have = _const_decl(canonical, name)
        if have is None or _const_decl(src, name) is None:
            continue
        _i, eq, end = have
        src = _set_const_initializer(src, name, canonical[eq + 1:end])
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


def _ts_value(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return _ts_string(mask_ssn(v))
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_ts_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{_ts_value(val)}" for k, val in v.items()) + "}"
    raise TypeError(type(v).__name__)


def _const_edit(src, name, expr):
    i, eq, end = _const_decl(src, name)
    return {"name": name, "old_string": src[i:end + 1], "new_string": src[i:eq + 1] + expr + ";"}


def page_state_edits(start=None, handle=None, phase=None, run=None, rules=None, qa=None, kept=None,
                     lane=None, pace=None, cooling=None, failed=None, deleted=None, verified=None,
                     left=None, unchecked=None, likes=None, totals=None, bundle_dir=BUNDLE_DIR):
    """Exact one-line edits for boot lines and the loadable data constants."""
    src = open(_page_paths(bundle_dir)[0], encoding="utf-8").read()
    edits = []
    if start:
        edits.append(_const_edit(src, "START_STEP", '"' + start + '"'))
    if run:
        edits.append(_const_edit(src, "START_RUN", '"' + run + '"'))
    if handle:
        edits.append(_const_edit(src, "SIGNED_IN_HANDLE", _ts_string(mask_ssn(handle))))
    if phase:
        edits.append(_const_edit(src, "START_PHASE", '"' + phase + '"'))
    if rules is not None:
        edits.append(_const_edit(src, "LOADED_RULES", _ts_value(rules)))
    if qa is not None:
        edits.append(_const_edit(src, "LOADED_QA", _ts_string(qa)))
    if kept is not None:
        edits.append(_const_edit(src, "LOADED_KEPT", _ts_value(list(kept))))
    if lane is not None:
        edits.append(_const_edit(src, "LOADED_LANE", _ts_string(lane)))
    if pace is not None:
        edits.append(_const_edit(src, "LOADED_PACE", _ts_string(pace)))
    if cooling is not None:
        edits.append(_const_edit(src, "LOADED_COOLING", "true" if cooling else "false"))
    if failed is not None:
        edits.append(_const_edit(src, "LOADED_FAILED", _ts_value(failed)))
    if deleted is not None:
        edits.append(_const_edit(src, "LOADED_DELETED", str(int(deleted))))
    if verified is not None:
        edits.append(_const_edit(src, "LOADED_VERIFIED", str(int(verified))))
    if left is not None:
        edits.append(_const_edit(src, "LOADED_LEFT", str(int(left))))
    if unchecked is not None:
        edits.append(_const_edit(src, "LOADED_UNCHECKED", str(int(unchecked))))
    if likes is not None:
        edits.append(_const_edit(src, "LOADED_LIKES", str(int(likes))))
    if totals is not None:
        edits.append(_const_edit(src, "LOADED_TOTALS", _ts_value(totals)))
    return edits


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

# ---------------------------------------------------------------- verdicts shared with the Page
PAGE_POOL_MAX = 20000  # one EditCanvas payload, old_string + new_string, in bytes
PAGE_SAMPLE_CAP = 50
QUICK_IDS = ("everything", "oldest", "era", "replies", "reposts", "best")


def base_rules():
    """The Page's BASE. Clear all rules returns here. Loaded rules are a separate constant."""
    return {
        "timeMode": "none", "olderDays": 365, "olderDate": "", "yearFrom": 2023, "yearTo": 2026,
        "protectDays": 0, "protectDate": "", "posts": False, "replies": False, "selfReplies": False,
        "reposts": False, "quotes": False, "community": False, "mediaPhotos": False, "mediaVideos": False,
        "mediaGifs": False, "mediaText": False, "postsLikesMax": -1, "repliesLikesMax": -1, "repliesMax": -1,
        "deleteWords": [], "keepWords": [], "replyHandles": [], "repostOf": "", "topic": "",
        "skipMentions": False, "keepThreads": False, "keepProfilePin": True, "keepMedia": False,
        "deleteSlurs": False,
    }


def _handle(s):
    return re.sub(r"^@", "", (s or "").strip()).lower()


def _post_days(p, today):
    if p.get("daysAgo") is not None and p.get("daysAgo") != "":
        return int(p["daysAgo"])
    if p.get("date_note"):
        return -1
    dt = p.get("created_at_dt") or p.get("created_at")
    if isinstance(dt, str):
        dt = parse_date(dt)
    if not isinstance(dt, datetime):
        return -1
    return (today.date() - dt.astimezone(TZ).date()).days


def _year_of(days, today):
    return (today.date() - timedelta(days=max(0, int(days)))).year


def normalize_post(p, today):
    typ = p.get("type") or "post"
    self_reply = typ == "self_reply" or bool(p.get("selfReply"))
    if typ == "self_reply":
        typ = "reply"
    if typ not in ("post", "reply", "repost", "quote"):
        typ = "post"
    kinds = p.get("media_kinds") or []
    return {
        "id": str(p.get("id") or ""),
        "daysAgo": _post_days(p, today),
        "type": typ,
        "likes": int(p.get("likes") if p.get("likes") is not None else (p.get("favorite_count") or 0)),
        "replies": int(p.get("replies") or p.get("reply_count") or 0),
        "text": p.get("text") or "",
        "summary": p.get("summary") or "",
        "community": bool(p.get("community")),
        "selfReply": self_reply,
        "replyTo": p.get("replyTo") or p.get("in_reply_to_screen_name") or "",
        "inReplyToId": str(p.get("inReplyToId") or p.get("in_reply_to") or ""),
        "media": bool(p.get("media") or any(k in ("photo", "video", "animated_gif") for k in kinds)),
        "gif": bool(p.get("gif") or "animated_gif" in kinds),
        "mediaKind": p.get("mediaKind") or (kinds[0] if kinds else ""),
        "profilePin": bool(p.get("profilePin") or p.get("profile_pin")),
        "extraMentions": bool(p.get("extraMentions")) or len(p.get("typed_mentions") or []) > 0,
        "repostOf": p.get("repostOf") or p.get("repost_of") or "",
        "thread": p.get("thread") or "",
    }


def card_rules(qa, posts, today):
    """Quick-card rules. Replies are to other people only. Past era is oldest through oldest+1."""
    r = base_rules()
    posts = posts or []
    if qa == "everything":
        r.update(timeMode="all", posts=True, replies=True, selfReplies=True, reposts=True, quotes=True, community=True, protectDays=0, protectDate="")
    elif qa == "oldest":
        r.update(timeMode="older", olderDays=730, olderDate="", posts=True, replies=True, selfReplies=True, reposts=True, quotes=True, community=True, protectDays=0, protectDate="")
    elif qa == "era":
        dated = [normalize_post(p, today)["daysAgo"] for p in posts]
        dated = [d for d in dated if d >= 0]
        oldest = _year_of(max(dated), today) if dated else today.year
        r.update(timeMode="years", yearFrom=oldest, yearTo=oldest + 1, posts=True, replies=True, selfReplies=True, reposts=True, quotes=True, community=True, protectDays=0, protectDate="")
    elif qa == "replies":
        r.update(timeMode="all", posts=False, replies=True, selfReplies=False, reposts=False, quotes=False, community=False, protectDays=0, protectDate="")
    elif qa == "reposts":
        r.update(timeMode="all", posts=False, replies=False, selfReplies=False, reposts=True, quotes=False, community=False, protectDays=0, protectDate="")
    elif qa == "best":
        r.update(timeMode="all", posts=False, replies=False, selfReplies=False, reposts=False, quotes=False, community=False, postsLikesMax=-1, repliesLikesMax=-1, keepThreads=False, protectDays=0, protectDate="")
    return r


def _is_self_reply(p, handle):
    if p.get("selfReply"):
        return True
    if p.get("type") != "reply":
        return False
    me = _handle(handle)
    return me != "" and _handle(p.get("replyTo") or "") == me


def _scope_parts(p, r, handle, today):
    if p["daysAgo"] < 0:
        return None
    topic = (r.get("topic") or "").strip()
    repost_of = _handle(r.get("repostOf") or "")
    has_scope = (
        r.get("timeMode") not in (None, "none") or r.get("deleteWords") or r.get("deleteSlurs") or topic
        or repost_of or (r.get("postsLikesMax") or -1) >= 0 or (r.get("repliesLikesMax") or -1) >= 0
        or r.get("replyHandles") or r.get("posts") or r.get("replies") or r.get("reposts") or r.get("quotes") or r.get("community")
        or r.get("mediaPhotos") or r.get("mediaVideos") or r.get("mediaGifs") or r.get("mediaText")
    )
    if not has_scope:
        return None
    parts = []
    mode = r.get("timeMode")
    if mode == "all":
        parts.append("everything")
    if mode == "older":
        older = r.get("olderDate") or ""
        if older:
            try:
                cut = datetime.strptime(older, "%Y-%m-%d").replace(tzinfo=TZ)
                min_days = (today.date() - cut.date()).days
            except Exception:
                min_days = -1
        else:
            min_days = int(r.get("olderDays") or 0)
        if min_days < 0 or p["daysAgo"] < min_days:
            return None
        parts.append("older")
    if mode == "years":
        y = _year_of(p["daysAgo"], today)
        if y < int(r.get("yearFrom") or 0) or y > int(r.get("yearTo") or 0):
            return None
        parts.append("years")
    typ = p["type"]
    if p["community"]:
        type_ok = bool(r.get("community"))
    elif _is_self_reply(p, handle):
        type_ok = bool(r.get("selfReplies"))
    elif typ == "post":
        type_ok = bool(r.get("posts"))
    elif typ == "reply":
        type_ok = bool(r.get("replies"))
    elif typ == "quote":
        type_ok = bool(r.get("quotes"))
    else:
        type_ok = bool(r.get("reposts"))
    if not type_ok:
        return None
    like_cap = -1
    if typ != "repost" and not p["community"]:
        like_cap = int(r.get("repliesLikesMax") if typ == "reply" else r.get("postsLikesMax") or -1)
    if like_cap >= 0 and p["likes"] > like_cap:
        return None
    words = list(r.get("deleteWords") or [])
    if words or r.get("deleteSlurs"):
        hit = next((w for w in words if find_words(p["text"], [w])), "")
        slur = (not hit) and r.get("deleteSlurs") and bool(find_words(p["text"], SLURS))
        if not hit and not slur:
            return None
        parts.append("slur" if slur else "word")
    if repost_of:
        if p["type"] != "repost" or _handle(p.get("repostOf") or "") != repost_of:
            return None
    handles = list(r.get("replyHandles") or [])
    if handles:
        ok = any(_handle(h) == _handle(p.get("replyTo") or "") or find_words(p["text"], ["@" + _handle(h)]) for h in handles)
        if not ok:
            return None
    return parts or ["match"]


def _keep_reason(p, r, pins):
    if p["id"] in pins:
        return "Kept by you"
    if (r.get("keepWords") or []) and any(find_words(p["text"], [w]) for w in r["keepWords"]):
        return "keep word"
    return ""


def compute_verdicts(posts, rules=None, pins=None, qa="", today=None, handle=""):
    """Same decisions as the Page's computeVerdicts. Posts with no readable date are not deleted."""
    today = today or datetime.now(TZ)
    pins = set(str(x) for x in (pins or []))
    rules = card_rules(qa, posts, today) if qa else {**base_rules(), **(rules or {})}
    if qa == "" and rules.get("timeMode") == "years" and int(rules.get("yearFrom") or 0) == 0:
        dated = [normalize_post(p, today)["daysAgo"] for p in posts]
        dated = [d for d in dated if d >= 0]
        if dated:
            oldest = _year_of(max(dated), today)
            rules["yearFrom"], rules["yearTo"] = oldest, oldest + 1
    norm = [normalize_post(p, today) for p in posts]
    by_id = {p["id"]: p for p in norm}
    kept_threads = set()
    if rules.get("keepThreads"):
        for p in norm:
            if p["id"] in pins or _keep_reason(p, rules, pins):
                key = p.get("thread") or p.get("inReplyToId") or p["id"]
                kept_threads.add(key)
    out = {}
    for p in norm:
        if p["daysAgo"] < 0:
            out[p["id"]] = {"kind": "none", "reason": "no readable date"}
            continue
        if p["id"] in pins:
            out[p["id"]] = {"kind": "keep", "reason": "Kept by you"}
            continue
        parts = _scope_parts(p, rules, handle, today)
        if not parts:
            out[p["id"]] = {"kind": "none", "reason": ""}
            continue
        why = _keep_reason(p, rules, pins)
        if why:
            out[p["id"]] = {"kind": "keep", "reason": why}
            continue
        key = p.get("thread") or p.get("inReplyToId") or p["id"]
        if rules.get("keepThreads") and key in kept_threads and p["id"] not in pins:
            out[p["id"]] = {"kind": "keep", "reason": "part of a kept thread"}
            continue
        out[p["id"]] = {"kind": "delete", "reason": "Matches"}
    no_date = sum(1 for p in norm if p["daysAgo"] < 0)
    matched = [p for p in norm if out[p["id"]]["kind"] == "delete"]
    kept = len(norm) - len(matched)
    fast = sum(1 for p in matched if p["type"] != "repost")
    delete_everything = qa == "everything" or (
        rules.get("timeMode") == "all" and rules.get("posts") and rules.get("replies") and rules.get("selfReplies")
        and rules.get("reposts") and rules.get("quotes") and rules.get("community") and not rules.get("deleteWords")
        and not rules.get("deleteSlurs") and (rules.get("postsLikesMax") or -1) < 0 and (rules.get("repliesLikesMax") or -1) < 0
    )
    return {
        "posts": norm, "verdicts": out, "rules": rules, "scanned": len(norm), "matched": len(matched),
        "kept": kept, "no_date": no_date, "fast_count": fast,
        "needs_typed_confirm": needs_typed_confirm(len(matched), len(norm), delete_everything),
        "confirm_phrase": confirm_phrase(len(matched)) if needs_typed_confirm(len(matched), len(norm), delete_everything) else "",
    }


def verdict_totals(result, caps):
    groups = [
        ("Posts", lambda p: not p["community"] and p["type"] == "post"),
        ("Replies", lambda p: not p["community"] and p["type"] == "reply"),
        ("Reposts", lambda p: p["type"] == "repost"),
        ("Quotes", lambda p: not p["community"] and p["type"] == "quote"),
        ("Community", lambda p: p["community"]),
    ]
    rows = []
    for label, pred in groups:
        if label == "Quotes" and not caps.get("hasQuoteFields"):
            rows.append(["Quotes", "n/a", "not available from this archive"])
            continue
        allp = [p for p in result["posts"] if pred(p)]
        dele = [p for p in allp if result["verdicts"][p["id"]]["kind"] == "delete"]
        rows.append([label, str(len(dele)), str(len(allp) - len(dele))])
    return {
        "scanned": result["scanned"], "matched": result["matched"], "kept": result["kept"],
        "noDate": result["no_date"], "fastCount": result["fast_count"], "byType": rows,
    }


def _worst_key(p):
    text = p.get("text") or ""
    leak = bool(SSN_RE.search(text) or PHONE_RE.search(text) or EMAIL_RE.search(text))
    slur = bool(find_words(text, SLURS))
    strong = bool(find_words(text, STRONG))
    tier = 0 if leak else 1 if slur else 2 if strong else 4
    days = p.get("daysAgo") if p.get("daysAgo", -1) >= 0 else -1
    return (tier, p.get("likes") or 0, -days)


def _compact_post(p, text_cap):
    text = mask_ssn(p.get("text") or "")
    if len(text) > text_cap:
        text = text[:text_cap].rstrip() + "…"
    row = {"id": p["id"], "daysAgo": p["daysAgo"], "type": p["type"], "likes": p["likes"], "text": text, "summary": mask_ssn((p.get("summary") or text)[:60])}
    if p.get("selfReply"):
        row["selfReply"] = True
    if p.get("replyTo"):
        row["replyTo"] = p["replyTo"]
    if p.get("community"):
        row["community"] = True
    if p.get("media"):
        row["media"] = True
    if p.get("repostOf"):
        row["repostOf"] = p["repostOf"]
    return row


def _read_posts(path):
    posts = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                posts.append(json.loads(line))
    return posts


def load_rules_file(path, qa, posts, today):
    if qa:
        return card_rules(qa, posts, today), qa
    if not path:
        return base_rules(), ""
    raw = json.load(open(path, encoding="utf-8"))
    qa_in = raw.get("qa") or ""
    if qa_in:
        return card_rules(qa_in, posts, today), qa_in
    return {**base_rules(), **raw.get("rules", raw)}, ""


def page_pool_payloads(posts, rules, qa="", handle="", today=None, bundle_dir=BUNDLE_DIR):
    """Edits that load a capped sample plus full-archive totals. Each edit is <= PAGE_POOL_MAX bytes."""
    today = today or datetime.now(TZ)
    result = compute_verdicts(posts, rules if not qa else None, qa=qa, today=today, handle=handle)
    caps = {
        "hasPinFlag": any(p.get("profilePin") for p in result["posts"]),
        "hasReplyCount": any(p.get("replies") for p in result["posts"]),
        "hasQuoteFields": any(p["type"] == "quote" for p in result["posts"]),
    }
    totals = verdict_totals(result, caps)
    doomed = [p for p in result["posts"] if result["verdicts"][p["id"]]["kind"] == "delete"]
    doomed.sort(key=_worst_key)
    src = open(_page_paths(bundle_dir)[0], encoding="utf-8").read()
    count = sum(1 for p in result["posts"] if not p["community"])
    sample_n, text_cap = PAGE_SAMPLE_CAP, 80
    edits = []
    while True:
        sample = [_compact_post(p, text_cap) for p in doomed[:sample_n]]
        edits = [
            _const_edit(src, "ARCHIVE_CAPS", _ts_value(caps)),
            _const_edit(src, "ARCHIVE_POST_COUNT", str(count)),
            _const_edit(src, "LOADED_TOTALS", _ts_value(totals)),
            _const_edit(src, "POOL", _ts_value(sample)),
        ]
        sizes = [len(json.dumps(e, ensure_ascii=False).encode()) for e in edits]
        if max(sizes) <= PAGE_POOL_MAX or (text_cap <= 20 and sample_n <= 5):
            break
        if text_cap > 20:
            text_cap = 20 if text_cap > 40 else text_cap - 20
        else:
            sample_n = max(5, sample_n // 2)
    return {"edits": edits, "bytes": [len(json.dumps(e, ensure_ascii=False).encode()) for e in edits],
            "max_bytes": PAGE_POOL_MAX, "sample": min(sample_n, len(doomed)), "totals": totals,
            "needs_typed_confirm": result["needs_typed_confirm"], "confirm_phrase": result["confirm_phrase"]}


def doomed_rows(posts, rules, qa="", handle="", today=None):
    today = today or datetime.now(TZ)
    result = compute_verdicts(posts, None if qa else rules, qa=qa, today=today, handle=handle)
    h = _handle(handle)
    rows = []
    for p in result["posts"]:
        if result["verdicts"][p["id"]]["kind"] != "delete":
            continue
        url = f"https://x.com/{h}/status/{p['id']}" if h else f"https://x.com/i/web/status/{p['id']}"
        rows.append({
            "id": p["id"], "status_url": url, "type": p["type"], "likes": p["likes"],
            "about": p.get("summary") or "", "text": p.get("text") or "",
            "matched_rule": result["verdicts"][p["id"]]["reason"],
        })
    return rows, result


def unwrap_export_id(cell):
    s = (cell or "").strip()
    if s.startswith("'"):
        s = s[1:]
    m = re.fullmatch(r'="(.*)"', s)
    if m:
        return m.group(1)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def export_check(path):
    """Doomed export: row count, ids exact, ids unwrapped from =\"...\"."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = []
    for row in rows:
        raw = row.get("id") or ""
        uid = unwrap_export_id(raw)
        if not re.fullmatch(r"\d{1,20}", uid):
            return {"ok": False, "rows": len(rows), "ids": ids, "error": f"bad id {raw!r}"}
        ids.append(uid)
        for key, val in row.items():
            if key == "id" or not val:
                continue
            if SSN_RE.search(val):
                return {"ok": False, "rows": len(rows), "ids": ids, "error": f"unmasked number in {key}"}
    return {"ok": True, "rows": len(rows), "ids": ids}


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
    stest = sub.add_parser("selftest")
    stest.add_argument("--no-typecheck", action="store_true", help="skip the Node type-check; first-turn fast path")
    ps = sub.add_parser("page-steps", help="the Page build steps")
    ps.add_argument("--show", type=int, help="print only this step's exact text")
    ps.add_argument("--part", type=int, help="step 1 only: which part to print")
    ps.add_argument("--start", choices=["signin", "archive", "pick", "review", "run"], help="step 1 only: START_STEP already set")
    ps.add_argument("--handle", default="", help="step 1 only: SIGNED_IN_HANDLE already filled")
    ps.add_argument("--phase", choices=["choose", "grabbing", "waiting", "ready", "manual"], help="step 1 only: START_PHASE already set")
    pstate = sub.add_parser("page-state", help="exact boot-line and loaded-data edits")
    pstate.add_argument("--start", choices=["signin", "archive", "pick", "review", "run"])
    pstate.add_argument("--run", choices=["idle", "running", "done"])
    pstate.add_argument("--handle", default="")
    pstate.add_argument("--phase", choices=["choose", "grabbing", "waiting", "ready", "manual"])
    pstate.add_argument("--rules", help="JSON object merged over BASE for LOADED_RULES")
    pstate.add_argument("--qa", choices=["", *QUICK_IDS])
    pstate.add_argument("--kept", default="", help="comma-separated kept post ids")
    pstate.add_argument("--lane", choices=["free", "fast"])
    pstate.add_argument("--pace", choices=["steady", "faster", "fastest"])
    pstate.add_argument("--cooling", choices=["on", "off"])
    pstate.add_argument("--failed", help='JSON array of {"id","reason"}')
    pstate.add_argument("--deleted", type=int)
    pstate.add_argument("--verified", type=int)
    pstate.add_argument("--left", type=int)
    pstate.add_argument("--unchecked", type=int)
    pstate.add_argument("--likes", type=int)
    pstate.add_argument("--totals", help="JSON LoadedTotals object")
    for name, help_ in (
        ("verdict", "full-archive counts using the Page's rules"),
        ("page-pool", "compact Page edits, each payload <= 20000 bytes"),
        ("export", "doomed-post CSV with masked free text"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("posts")
        sp.add_argument("--rules")
        sp.add_argument("--qa", choices=list(QUICK_IDS))
        sp.add_argument("--handle", default="")
        sp.add_argument("--pins", default="")
        if name == "export":
            sp.add_argument("--out", required=True)
    chk = sub.add_parser("export-check", help="count doomed-export rows and unwrap ids")
    chk.add_argument("file")
    pv = sub.add_parser("page-verify", help="check a ReadCanvas result")
    pv.add_argument("file")
    pv.add_argument("--after", type=int, help="check the state after this build step instead of the finished page")
    pw = sub.add_parser("page-where", help="which build step a saved ReadCanvas result is at")
    pw.add_argument("file")
    sub.add_parser("page-build", help="release-time: regenerate page/ from page.min.tsx and page/regions.json")
    sub.add_parser("page-typecheck", help="tsc --strict on every build step, including the first and final page")
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
    if a.cmd == "page-typecheck":
        code, out = page_typecheck()
        sys.stdout.write(out)
        return code
    if a.cmd == "page-steps":
        plan = page_steps()
        if a.show is None:
            print(json.dumps([{k: v for k, v in st.items() if k != "sha256_after"} for st in plan["steps"]], indent=1)); return 0
        nsteps = len(plan["steps"])
        if a.show < 1 or a.show > nsteps:
            print(f"the plan has {nsteps} steps"); return 1
        sys.stdout.write(page_show(a.show, a.part, start=a.start, handle=a.handle or None, phase=a.phase)); return 0
    if a.cmd == "page-state":
        rules = json.loads(a.rules) if a.rules else None
        failed = json.loads(a.failed) if a.failed else None
        totals = json.loads(a.totals) if a.totals else None
        kept = [x for x in a.kept.split(",") if x] if a.kept else None
        if not any([a.start, a.handle, a.phase, a.run, rules, a.qa is not None, kept, a.lane, a.pace, a.cooling, failed, a.deleted is not None, a.verified is not None, a.left is not None, a.unchecked is not None, a.likes is not None, totals]):
            print("page-state needs a flag"); return 1
        edits = page_state_edits(
            a.start, a.handle or None, a.phase, run=a.run, rules=rules, qa=a.qa, kept=kept,
            lane=a.lane, pace=a.pace, cooling=(a.cooling == "on") if a.cooling else None,
            failed=failed, deleted=a.deleted, verified=a.verified, left=a.left,
            unchecked=a.unchecked, likes=a.likes, totals=totals,
        )
        print(json.dumps(edits, ensure_ascii=False)); return 0
    if a.cmd in ("verdict", "page-pool", "export"):
        posts = _read_posts(a.posts)
        today = datetime.now(TZ)
        rules, qa = load_rules_file(a.rules, a.qa, posts, today)
        pins = [x for x in (a.pins or "").split(",") if x]
        if a.cmd == "verdict":
            result = compute_verdicts(posts, rules, pins=pins, qa=qa, today=today, handle=a.handle)
            caps = {"hasQuoteFields": any(p["type"] == "quote" for p in result["posts"]), "hasPinFlag": False, "hasReplyCount": False}
            print(json.dumps({**verdict_totals(result, caps), "needs_typed_confirm": result["needs_typed_confirm"], "confirm_phrase": result["confirm_phrase"]}, ensure_ascii=False))
            return 0
        if a.cmd == "page-pool":
            payload = page_pool_payloads(posts, rules, qa=qa, handle=a.handle, today=today)
            if any(n > PAGE_POOL_MAX for n in payload["bytes"]):
                print(json.dumps({"ok": False, "error": "payload over 20000 bytes", "bytes": payload["bytes"]}))
                return 1
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        rows, result = doomed_rows(posts, rules, qa=qa, handle=a.handle, today=today)
        fields = ["id", "status_url", "type", "likes", "about", "text", "matched_rule"]
        write_export_csv(a.out, rows, fields)
        print(json.dumps({"rows": len(rows), "out": a.out, "needs_typed_confirm": result["needs_typed_confirm"]}))
        return 0
    if a.cmd == "export-check":
        report = export_check(a.file)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
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
        i, _eq, end = _const_decl(base, "SIGNED_IN_HANDLE")
        assert base[i:end + 1] == 'const SIGNED_IN_HANDLE:string="";'
        for name, literal in (
            ("PHONE_FORTRESS_URL", "https://x.ai/bot/a_4tVB4gwbwFBLkUhkTCW"),
            ("EMAIL_FORTRESS_URL", "https://x.ai/bot/MyKDbPYVwJeJpCNtVTFym"),
        ):
            j, _eq, jend = _const_decl(base, name)
            assert base[j:jend + 1] == f'const {name}:string="{literal}";'
        first = open(os.path.join(_page_paths()[1], "01-first.tsx"), encoding="utf-8").read()
        booted = apply_page_boot(first, "archive", "example", "grabbing")
        assert 'const START_STEP:Step="archive";' in booted
        assert 'const SIGNED_IN_HANDLE:string="example";' in booted
        assert 'const START_PHASE:HomePhase="grabbing";' in booted
        assert normalize_page_boot(booted) == first
        edits = page_state_edits("archive", "example", "grabbing")
        assert edits[0]["old_string"] == 'const START_STEP:Step="signin";'
        assert edits[0]["new_string"] == 'const START_STEP:Step="archive";'
        assert edits[1]["old_string"] == 'const SIGNED_IN_HANDLE:string="";'
        assert edits[1]["new_string"] == 'const SIGNED_IN_HANDLE:string="example";'
        assert edits[2]["old_string"] == 'const START_PHASE:HomePhase="choose";'
        assert edits[2]["new_string"] == 'const START_PHASE:HomePhase="grabbing";'
        man = json.load(open(os.path.join(BUNDLE_DIR, "manifest.json"), encoding="utf-8"))
        listed = {item["path"] for item in man["files"]}
        for rel in man["page_build"]["steps"]:
            assert rel in listed, rel
            assert os.path.isfile(os.path.join(BUNDLE_DIR, rel)), rel
        for item in man["files"]:
            data = open(os.path.join(BUNDLE_DIR, item["path"]), "rb").read()
            assert hashlib.sha256(data).hexdigest() == item["sha256"] and len(data) == item["bytes"], item["path"]
        assert "daysAgo<0" in base and "oldestYear+1" in base
        assert "https://x.com/i/web/status/" in base and "Button didn't respond" not in base
        assert "2023-01-01" not in base and "2026-10-15" not in base and "One click" not in base
        assert "$8" not in base and "$99" not in base and "selfReplies:false" in base
        endings = re.search(r"const WORD_ENDINGS(?::string\[\])?=\[(.*?)\];", base)
        slurs = re.search(r"const SLUR_WORDS(?::string\[\])?=\[(.*?)\];", base)
        assert endings and json.loads("[" + endings.group(1) + "]") == SUFFIXES
        assert slurs and json.loads("[" + slurs.group(1) + "]") == SLURS
        assert "head" in SUFFIXES and "heads" in SUFFIXES and "face" in SUFFIXES
        qc = json.load(open(os.path.join(DATA_DIR, "quick-cleanups.json"), encoding="utf-8"))
        replies = next(c for c in qc["quick_cleanups"] if c["id"] == "all_replies")
        era = next(c for c in qc["quick_cleanups"] if c["id"] == "past_era")
        assert replies["rule"]["types"] == ["reply"] and "self_reply" not in replies["rule"]["types"]
        assert era["rule"]["year_to"] == "oldest+1" and qc["typed_confirm"]["delete_everything"] is True
        fixed = datetime(2026, 11, 24, tzinfo=TZ)
        sample = [
            {"id": "10", "type": "post", "text": "hello", "favorite_count": 1, "created_at": "2020-01-01T00:00:00+00:00"},
            {"id": "11", "type": "reply", "text": "to them", "favorite_count": 0, "created_at": "2020-06-01T00:00:00+00:00", "in_reply_to_screen_name": "other"},
            {"id": "12", "type": "self_reply", "text": "own thread", "favorite_count": 0, "created_at": "2020-06-02T00:00:00+00:00"},
            {"id": "13", "type": "post", "text": "ssn 123-45-6789", "favorite_count": 0, "date_note": "date unreadable"},
        ]
        replied = compute_verdicts(sample, qa="replies", today=fixed, handle="me")
        assert replied["verdicts"]["11"]["kind"] == "delete" and replied["verdicts"]["12"]["kind"] != "delete"
        assert replied["verdicts"]["10"]["kind"] != "delete"
        wiped = compute_verdicts(sample, qa="everything", today=fixed)
        assert wiped["verdicts"]["13"]["kind"] == "none" and wiped["no_date"] == 1 and wiped["needs_typed_confirm"] is True
        assert wiped["verdicts"]["10"]["kind"] == "delete" and wiped["verdicts"]["12"]["kind"] == "delete"
        era_v = compute_verdicts(sample, qa="era", today=fixed)
        assert era_v["rules"]["yearFrom"] == 2020 and era_v["rules"]["yearTo"] == 2021
        assert era_v["verdicts"]["13"]["kind"] == "none"
        assert needs_typed_confirm(3, 100, True) and not needs_typed_confirm(3, 100, False)
        loaded = _set_const_initializer(base, "LOADED_DELETED", "4")
        loaded = _set_const_initializer(loaded, "POOL", "[{id:\"1\",daysAgo:-1,type:\"post\",likes:0,replies:0,text:\"x\",summary:\"x\"}]")
        assert normalize_page_boot(loaded) == base
        run_edit = page_state_edits(run="running")
        assert run_edit[0]["name"] == "START_RUN" and run_edit[0]["new_string"].endswith('"running";')
        import tempfile
        tmp = tempfile.mkdtemp()
        open(os.path.join(tmp, "tweets.js"), "w", encoding="utf-8").write(
            'window.YTD.tweets.part0 = ['
            '{"tweet":{"id_str":"100","created_at":"Wed Jan 01 00:00:00 +0000 2020","full_text":"ok","favorite_count":0}},'
            '{"tweet":{"id_str":"bad id","created_at":"Wed Jan 01 00:00:00 +0000 2020","full_text":"nope","favorite_count":0}}'
            ']'
        )
        _posts, rep = parse_archive([tmp], "1", today=fixed, manifest_count=2)
        assert rep["count_mismatch"] is False and rep["skipped_counted"] == 1 and rep["ready_for_review"] is True
        _posts, rep = parse_archive([tmp], "1", today=fixed, manifest_count=3)
        assert rep["count_mismatch"] is True and rep["ready_for_review"] is False
        csv_path = os.path.join(tmp, "doomed.csv")
        write_export_csv(csv_path, [{"id": "1234567890123456789", "status_url": "https://x.com/i/web/status/1234567890123456789", "type": "post", "likes": 0, "about": "ssn 123-45-6789", "text": "fine", "matched_rule": "Matches"}], ["id", "status_url", "type", "likes", "about", "text", "matched_rule"])
        checked = export_check(csv_path)
        assert checked["ok"] and checked["rows"] == 1 and checked["ids"] == ["1234567890123456789"]
        raw_csv = open(csv_path, encoding="utf-8").read()
        assert "123-45-6789" not in raw_csv and "***-**-6789" in raw_csv
        pool = page_pool_payloads(sample, None, qa="everything", today=fixed)
        assert pool["bytes"] and max(pool["bytes"]) <= PAGE_POOL_MAX and pool["totals"]["noDate"] == 1
        if not a.no_typecheck:
            tcode, tout = page_typecheck()
            assert tcode == 0, tout
        else:
            tcode, tout = 0, ""
        if not a.no_typecheck and "skipped" not in tout:
            final = page_steps()["full_page_after"]
            for label in ("ok step-01.tsx", "ok step-07.tsx", f"ok step-{final:02d}.tsx", "ok step-01-archive.tsx", "ok step-01-ready.tsx"):
                assert label in tout, tout
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
                      "partial": report["partial"], "count_mismatch": report["count_mismatch"],
                      "skipped": report.get("skipped_counted", 0), "unreadable": report.get("unreadable", 0),
                      "accounted": report.get("accounted")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
