#!/usr/bin/env python3
"""Pull the words you've learned on Duolingo into data/words.json.

The GitHub Actions workflow runs this every 15 minutes. Each run:
  1. reads your Duolingo login token from the DUOLINGO_JWT environment variable,
  2. asks Duolingo for the list you see at duolingo.com/practice-hub/words,
  3. merges it into data/words.json (a word's "added" date is the first sync
     that saw it),
  4. writes a pronunciation with Spanish letters for each new word,
  5. applies your fixes from data/overrides.json,
  6. for a course with important sentences (data/frases.json), saves the key
     phrases from the Guidebook of each unit you've done into
     data/guidebook.json.

It also merges export files dropped into data/import/ (made with the button on
tools.html), which works even without a token.

Duolingo has no official API. This makes the same requests the Duolingo
website makes, so it breaks if Duolingo changes them. See README.md.

    python3 scripts/sync.py            # normal run
    python3 scripts/sync.py --offline  # skip Duolingo: imports and pronunciations only
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pronounce  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WORDS_FILE = DATA / "words.json"
OVERRIDES_FILE = DATA / "overrides.json"
IMPORT_DIR = DATA / "import"
FRASES_FILE = DATA / "frases.json"
GUIDEBOOK_FILE = DATA / "guidebook.json"

DUOLINGO = "https://www.duolingo.com"
BASE_URL = os.environ.get("DUOLINGO_BASE_URL", DUOLINGO).rstrip("/")
PAGE_SIZE = 100
MAX_PAGES = 200
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

LANGUAGE_NAMES = {
    "ar": "Arabic", "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "eo": "Esperanto", "es": "Spanish",
    "fi": "Finnish", "fr": "French", "ga": "Irish", "gd": "Scottish Gaelic",
    "he": "Hebrew", "hi": "Hindi", "ht": "Haitian Creole", "hu": "Hungarian",
    "hv": "High Valyrian", "hw": "Hawaiian", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "kl": "Klingon", "ko": "Korean", "la": "Latin", "nb": "Norwegian",
    "nl": "Dutch", "no": "Norwegian", "nv": "Navajo", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sv": "Swedish", "sw": "Swahili", "tr": "Turkish",
    "uk": "Ukrainian", "vi": "Vietnamese", "yi": "Yiddish", "zh": "Chinese", "zs": "Chinese",
    "zu": "Zulu",
}


class SyncError(Exception):
    """A problem to explain in plain words in the Actions log and on the page."""


class HttpProblem(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.text = text


def warn(text: str) -> None:
    print(f"::warning::{text}" if os.environ.get("GITHUB_ACTIONS") else f"warning: {text}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


# --- Talking to Duolingo ---------------------------------------------------

def call(method: str, path: str, jwt: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Cookie": f"jwt_token={jwt}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Origin": DUOLINGO,
        "Referer": DUOLINGO + "/practice-hub/words",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    last = ""
    for attempt in range(4):
        req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "replace")[:400]
            if err.code == 429 or err.code >= 500:
                last = f"HTTP {err.code}"
                time.sleep(5 * (attempt + 1))
                continue
            raise HttpProblem(err.code, text) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            last = str(getattr(err, "reason", err))
            time.sleep(5 * (attempt + 1))
            continue
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise HttpProblem(200, raw[:400]) from None
    raise SyncError(f"Couldn't reach Duolingo after several tries ({last}). It may be down; the next run will try again.")


def explain(problem: HttpProblem, doing: str) -> SyncError:
    text = problem.text.lower()
    looks_like_page = "<html" in text or "<!doctype" in text or "captcha" in text or "cloudflare" in text
    if problem.code == 200 or (problem.code == 403 and looks_like_page):
        return SyncError(
            f"Duolingo answered with a web page instead of data while {doing}, which usually means it's "
            "blocking requests from GitHub's servers. Use the export button on tools.html instead (README, plan B)."
        )
    if problem.code in (401, 403):
        return SyncError(
            f"Duolingo rejected the token (HTTP {problem.code}) while {doing}. Copy a fresh jwt_token "
            "from your browser and update the DUOLINGO_JWT secret (README, step 2). This happens after "
            "you change your Duolingo password."
        )
    detail = " ".join(problem.text.split())[:200]
    return SyncError(f"Duolingo answered HTTP {problem.code} while {doing}: {detail}")


def clean_token(raw: str) -> str:
    token = raw.strip().strip("'\"").strip()
    if token.startswith("jwt_token="):
        token = token[len("jwt_token="):]
    return token


def user_id_from(jwt: str) -> str:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload))["sub"]
    except Exception:
        raise SyncError(
            "DUOLINGO_JWT doesn't look like a Duolingo token. It's a long string with two dots in it, "
            "copied from the jwt_token cookie on duolingo.com (README, step 2)."
        ) from None
    return str(sub)


def _flatten(items):
    for item in items:
        if isinstance(item, list):
            yield from _flatten(item)
        else:
            yield item


def progressed_skills(course: dict) -> list[dict]:
    """How far along the course you are, worked out the way the Words page does:
    the first level of each skill on your path, unless that skill is still locked."""
    skills: list[dict] = []
    seen: set[str] = set()
    for section in course.get("pathSectioned") or []:
        for unit in (section or {}).get("units") or []:
            for level in (unit or {}).get("levels") or []:
                if not isinstance(level, dict):
                    continue
                ids = []
                for key in ("pathLevelMetadata", "pathLevelClientData"):
                    meta = level.get(key)
                    if isinstance(meta, dict):
                        ids.append(meta.get("skillId"))
                        ids.extend(meta.get("skillIds") or [])
                for sid in ids:
                    if not isinstance(sid, str) or not sid or sid in seen:
                        continue
                    seen.add(sid)
                    state = level.get("state")
                    if state == "locked":
                        continue
                    skills.append({
                        "finishedLevels": 1 if state in ("passed", "legendary") else 0,
                        "finishedSessions": int(level.get("finishedSessions") or 0),
                        "skillId": {"id": sid},
                    })
    if skills:
        return skills
    # Older course format: a list (sometimes a list of lists) of skills.
    for item in _flatten(course.get("skills") or []):
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        levels = int(item.get("finishedLevels") or 0)
        lessons = int(item.get("finishedLessons") or 0)
        if not isinstance(sid, str) or not sid or sid in seen or (levels <= 0 and lessons <= 0):
            continue
        seen.add(sid)
        skills.append({"finishedLevels": levels, "finishedSessions": lessons, "skillId": {"id": sid}})
    return skills


def current_course(user_id: str, jwt: str) -> tuple[str, str, list[dict], dict]:
    """The open course: (learning, from, progress for the word list, the course data)."""
    found = None
    problems = []
    for version in ("2017-06-30", "2023-05-23"):
        try:
            data = call("GET", f"/{version}/users/{user_id}?fields=currentCourse", jwt)
        except HttpProblem as problem:
            if problem.code in (401, 403) or problem.code == 200:
                raise explain(problem, "reading your course") from None
            problems.append(f"{version}: HTTP {problem.code}")
            continue
        course = (data or {}).get("currentCourse") or {}
        learning = course.get("learningLanguage") or (data or {}).get("learningLanguage")
        source = course.get("fromLanguage") or (data or {}).get("fromLanguage")
        if not learning or not source:
            problems.append(f"{version}: no course in the answer")
            continue
        skills = progressed_skills(course)
        if skills:
            return learning, source, skills, course
        found = found or (learning, source, skills, course)
    if found:
        warn("Couldn't work out your progress from the course data, so asking Duolingo for words without it.")
        return found
    raise SyncError("Couldn't read your current Duolingo course (" + "; ".join(problems) + ").")


def language_courses(user_id: str, jwt: str) -> list[dict] | None:
    """The language courses on your Duolingo account that have any XP.

    Duolingo only hands out the word list of the course that's open in your
    app, so this list is how the page knows about a course (say Portuguese)
    before the sync has caught it open.
    """
    try:
        data = call("GET", f"/2017-06-30/users/{user_id}?fields=courses", jwt)
    except (HttpProblem, SyncError) as problem:
        warn(f"Couldn't read your list of courses ({problem}).")
        return None
    found = []
    for course in (data or {}).get("courses") or []:
        if not isinstance(course, dict):
            continue
        learning, source = course.get("learningLanguage"), course.get("fromLanguage")
        if not isinstance(learning, str) or not isinstance(source, str):
            continue
        if course.get("subject") not in (None, "language"):
            continue
        if isinstance(course.get("xp"), (int, float)) and course["xp"] <= 0:
            continue
        found.append({"learning": learning, "from": source,
                      "name": LANGUAGE_NAMES.get(learning, course.get("title") or learning)})
    found.sort(key=lambda c: (c["learning"], c["from"]))
    return found


def learned_words(user_id: str, learning: str, source: str, skills: list[dict], jwt: str):
    path = f"/2017-06-30/users/{user_id}/courses/{learning}/{source}/learned-lexemes"
    bodies = [
        {"lastTotalLexemeCount": 0, "progressedSkills": skills},
        {"lastTimeLearnedAt": None, "progressedSkills": skills},  # an older version of the same request
    ]
    which = 0
    words: list[dict] = []
    start = 0
    total = None
    pages = 0
    while pages < MAX_PAGES:
        query = f"?limit={PAGE_SIZE}&sortBy=LEARNED_DATE&startIndex={start}"
        try:
            page = call("POST", path + query, jwt, bodies[which])
        except HttpProblem as problem:
            if start == 0 and which == 0 and problem.code in (400, 422):
                which = 1
                continue
            raise explain(problem, "downloading your words") from None
        if page is None and start == 0 and which == 0:
            which = 1
            continue
        if not isinstance(page, dict) or not isinstance(page.get("learnedLexemes"), list):
            raise SyncError(
                "Duolingo's answer didn't contain a word list, so it may have changed how the Words page works. "
                "Try the export button on tools.html (README, plan B)."
            )
        pages += 1
        items = page["learnedLexemes"]
        words.extend(x for x in items if isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip())
        pagination = page.get("pagination") or {}
        if total is None and isinstance(pagination.get("totalLexemes"), int):
            total = pagination["totalLexemes"]
        nxt = pagination.get("nextStartIndex")
        if not items or not isinstance(nxt, int) or nxt <= start:
            break
        start = nxt
        time.sleep(0.5)
    return words, total


# --- Key phrases from each unit's Guidebook ---------------------------------
#
# Every unit on the path has a Guidebook whose first part, "Frases clave", lists
# a few sentences with a translation and Duolingo's recording. The course data
# gives its address, a public file that needs no token.

def wants_key_phrases(learning: str) -> bool:
    """Only a course with an important-sentences tab (data/frases.json) needs them."""
    try:
        frases = json.loads(FRASES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(frases, dict) and isinstance(frases.get(learning), dict)


def done_units(course: dict) -> list[dict]:
    """Units where at least one lesson is finished, with their Guidebook address."""
    out = []
    for si, section in enumerate(course.get("pathSectioned") or []):
        for ui, unit in enumerate((section or {}).get("units") or []):
            if not isinstance(unit, dict):
                continue
            # "unit_test" is the offer to jump ahead, not something you did.
            states = [lv.get("state") for lv in unit.get("levels") or [] if isinstance(lv, dict)]
            if not any(s not in (None, "locked", "active", "unit_test") for s in states):
                continue
            url = (unit.get("guidebook") or {}).get("url")
            if isinstance(url, str) and url.startswith("https://"):
                out.append({"section": si, "unit": ui, "title": nfc(unit.get("teachingObjective") or ""), "url": url})
    return out


def _styled(node) -> str:
    if isinstance(node, dict) and isinstance(node.get("styledString"), dict):
        return node["styledString"].get("text") or ""
    return ""


def _plain(text: str) -> str:
    return " ".join(nfc(text.replace(" ", " ").replace(" ", " ")).split())


def guidebook_phrases(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        book = json.loads(resp.read().decode("utf-8"))
    found: list[tuple[int | None, dict]] = []
    for el in (book or {}).get("elements") or []:
        if not isinstance(el, dict) or el.get("type") != "dialogue":
            continue
        part = (el.get("meta") or {}).get("sectionIndex")
        for ph in (el.get("element") or {}).get("phrases") or []:
            if not isinstance(ph, dict):
                continue
            text, meaning = _plain(_styled(ph.get("text"))), _plain(_styled(ph.get("subtext")))
            if not text:
                continue
            item = {"fr": text, "es": meaning}
            if isinstance(ph.get("ttsURL"), str) and ph["ttsURL"].startswith("https://"):
                item["audio"] = ph["ttsURL"]
            found.append((part, item))
    # The key phrases are the first part; later parts (tips) can have examples too.
    key = [item for part, item in found if part in (0, None)]
    return key or [item for _, item in found]


def update_key_phrases(course: dict, learning: str, source: str) -> str | None:
    """Save the key phrases of the units you've done. Returns a line for the log, if anything changed."""
    if not wants_key_phrases(learning):
        return None
    store = load_json(GUIDEBOOK_FILE, {})
    if not isinstance(store, dict):
        store = {}
    entry = store.setdefault(f"{learning}-{source}", {"units": []})
    units = {(u.get("section"), u.get("unit")): u for u in entry.get("units") or [] if isinstance(u, dict)}
    fetched = 0
    for unit in done_units(course):
        old = units.get((unit["section"], unit["unit"]))
        if old and old.get("url") == unit["url"] and old.get("title") == unit["title"]:
            continue  # the address changes when Duolingo edits the Guidebook
        try:
            phrases = guidebook_phrases(unit["url"])
        except Exception as err:  # noqa: BLE001  one unit failing shouldn't stop the rest
            warn(f"Couldn't read the Guidebook of unit {unit['unit'] + 1} ({err}).")
            continue
        units[(unit["section"], unit["unit"])] = {**unit, "phrases": phrases}
        fetched += 1
        time.sleep(0.3)
    if not fetched:
        return None
    entry["units"] = sorted(units.values(), key=lambda u: (u["section"], u["unit"]))
    total = sum(len(u.get("phrases") or []) for u in entry["units"])
    GUIDEBOOK_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return f"Key phrases: {total} from {len(entry['units'])} units (read {fetched} Guidebook{'s' if fetched != 1 else ''})."


# --- Merging into data/words.json ------------------------------------------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as err:
        raise SyncError(f"{path.relative_to(ROOT)} isn't valid JSON ({err}). Undo your last edit to it.") from None


def course_entry(store: dict, learning: str, source: str) -> tuple[str, dict]:
    key = f"{learning}-{source}"
    entry = store["courses"].setdefault(key, {
        "learning": learning,
        "from": source,
        "name": LANGUAGE_NAMES.get(learning, learning),
        "words": [],
        "dropped": {},
    })
    entry.setdefault("dropped", {})
    return key, entry


def merge(entry: dict, lexemes: list[dict], stamp: str, full: bool) -> list[str]:
    """Merge a list from Duolingo into a course. Returns the words that are new.

    full=True means this is Duolingo's whole current list, so words missing
    from it are dropped (their dates are remembered in case they come back).
    """
    words = {w["text"]: w for w in entry["words"]}
    dropped = entry["dropped"]
    seq = max((w.get("seq", 0) for w in entry["words"]), default=0)

    incoming: list[tuple[str, dict]] = []
    listed: set[str] = set()
    for lexeme in lexemes:
        text = nfc(lexeme.get("text") or "")
        if text and text not in listed:
            listed.add(text)
            incoming.append((text, lexeme))

    new: list[str] = []
    # Duolingo lists the newest words first, so number them from the end.
    for text, lexeme in reversed(incoming):
        translations = [nfc(t) for t in lexeme.get("translations") or [] if isinstance(t, str) and t.strip()]
        audio = lexeme.get("audioURL") if isinstance(lexeme.get("audioURL"), str) else None
        word = words.get(text)
        if word is None:
            seq += 1
            word = {"text": text, "translations": translations, "audio": audio,
                    "added": dropped.pop(text, stamp), "seq": seq}
            words[text] = word
            entry["words"].append(word)
            new.append(text)
        else:
            if translations and word.get("translations") != translations:
                word["translations"] = translations
            if audio and word.get("audio") != audio:
                word["audio"] = audio
    new.reverse()  # newest first, for the summary

    if full:
        gone = [text for text in words if text not in listed]
        if gone and len(listed) >= 0.5 * len(words):
            for text in gone:
                dropped[text] = words[text].get("added", stamp)
            entry["words"] = [w for w in entry["words"] if w["text"] in listed]
        elif gone:
            warn(
                f"Duolingo listed {len(listed)} words but {len(words)} were saved before. Keeping all of "
                "them in case something went wrong on Duolingo's side."
            )
    return new


def read_imports(store: dict, stamp: str) -> list[str]:
    notes = []
    done = store.setdefault("imports", [])
    for path in sorted(IMPORT_DIR.glob("*.json")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        if digest in done:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            warn(f"Skipped data/import/{path.name}: it isn't a valid export file.")
            continue
        course = data.get("course") if isinstance(data, dict) else None
        lexemes = data.get("learnedLexemes") if isinstance(data, dict) else None
        if not isinstance(course, dict) or not course.get("learning") or not course.get("from") or not isinstance(lexemes, list):
            warn(f"Skipped data/import/{path.name}: it isn't an export from tools.html.")
            continue
        key, entry = course_entry(store, course["learning"], course["from"])
        valid = [x for x in lexemes if isinstance(x, dict) and isinstance(x.get("text"), str)]
        new = merge(entry, valid, stamp, full=False)
        done.append(digest)
        store["current"] = key
        notes.append(f"Imported {path.name}: {len(valid)} words, {len(new)} new.")
    return notes


def overrides_for(overrides: dict, entry: dict) -> dict:
    table = overrides.get(f"{entry['learning']}-{entry['from']}") or overrides.get(entry["learning"]) or {}
    fixes = {}
    if isinstance(table, dict):
        for text, fix in table.items():
            if text.startswith("_"):
                continue
            if isinstance(fix, str):
                fix = {"pron": fix}
            if isinstance(fix, dict):
                fixes[nfc(text)] = fix
    return fixes


def finish_words(entry: dict, overrides: dict | None) -> int:
    """Add pronunciations and apply your fixes. Returns how many pronunciations were written.

    overrides=None means data/overrides.json couldn't be read, so words you
    fixed by hand are left exactly as they are until the file is repaired.
    """
    lang = entry["learning"]
    can_speak = bool(pronounce.espeak_path()) and lang in pronounce.VOICES
    fixes = overrides_for(overrides or {}, entry)
    written = 0
    for word in entry["words"]:
        if overrides is None:
            if word.get("pron_src") != "you" and can_speak and not (
                word.get("pron") and word.get("pron_v") == pronounce.VERSION
            ):
                spelled, ipa = pronounce.pronounce(word["text"], lang)
                if spelled:
                    word.update(pron=spelled, ipa=ipa, pron_v=pronounce.VERSION, pron_src="auto")
                    written += 1
            continue
        fix = fixes.get(word["text"], {})
        if isinstance(fix.get("translations"), list):
            word["translations"] = [str(t) for t in fix["translations"]]
        elif isinstance(fix.get("translations"), str):
            word["translations"] = [fix["translations"]]
        if isinstance(fix.get("note"), str) and fix["note"].strip():
            word["note"] = fix["note"].strip()
        else:
            word.pop("note", None)
        if isinstance(fix.get("pron"), str) and fix["pron"].strip():
            word["pron"] = nfc(fix["pron"])
            word["pron_src"] = "you"
            continue
        if word.get("pron_src") == "you":  # the fix was removed, so make a fresh one
            for key in ("pron", "pron_src", "pron_v"):
                word.pop(key, None)
        if not can_speak or (word.get("pron") and word.get("pron_v") == pronounce.VERSION):
            continue
        spelled, ipa = pronounce.pronounce(word["text"], lang)
        if spelled:
            word.update(pron=spelled, ipa=ipa, pron_v=pronounce.VERSION, pron_src="auto")
            written += 1
    return written


# --- Reporting -------------------------------------------------------------

def report(notes: list[str], error: str | None, setup: str | None = None, read: str | None = None) -> None:
    """Print what happened and hand a one-line status to the workflow.

    setup is a step you still have to do (like adding the token): the run
    doesn't fail, but the page shows the message.
    """
    for line in notes:
        print(line)
    if error:
        print(f"::error::{error}" if os.environ.get("GITHUB_ACTIONS") else f"error: {error}")
    problem = error or setup
    message = problem or (notes[0] if notes else "No changes.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("message=" + " ".join(message.split())[:500] + "\n")
            fh.write("ok=" + ("false" if problem else "true") + "\n")
            fh.write("read=" + (read or "") + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### Duolingo sync\n\n")
            if error:
                fh.write(f"**Didn't work:** {error}\n\n")
            for line in notes:
                fh.write(f"- {line}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--offline", action="store_true", help="skip Duolingo; only imports and pronunciations")
    args = parser.parse_args()

    stamp = now_iso()
    notes: list[str] = []
    error = None
    try:
        store = load_json(WORDS_FILE, {})
        store.setdefault("version", 1)
        store.setdefault("current", None)
        store.setdefault("updated", None)
        store.setdefault("courses", {})
    except SyncError as err:
        report([], str(err))
        return 1
    overrides_error = None
    try:
        overrides = load_json(OVERRIDES_FILE, {})
        if not isinstance(overrides, dict):
            raise SyncError("data/overrides.json should be a { ... } object. Undo your last edit to it.")
    except SyncError as err:
        overrides, overrides_error = None, str(err)
        warn(overrides_error)
    before = json.dumps(store, sort_keys=True, ensure_ascii=False)

    def fingerprint(entry: dict) -> str:
        return json.dumps({k: v for k, v in entry.items() if k != "updated"}, sort_keys=True, ensure_ascii=False)

    before_courses = {key: fingerprint(entry) for key, entry in store["courses"].items()}
    read_key = None

    notes += read_imports(store, stamp)

    jwt = clean_token(os.environ.get("DUOLINGO_JWT", ""))
    setup = None
    if args.offline:
        pass
    elif not jwt:
        setup = "The DUOLINGO_JWT secret isn't set yet, so Duolingo was skipped (README, step 2)."
        warn(setup)
    else:
        try:
            user_id = user_id_from(jwt)
            learning, source, skills, course = current_course(user_id, jwt)
            lexemes, total = learned_words(user_id, learning, source, skills, jwt)
            if not lexemes:
                raise SyncError(
                    "Duolingo sent an empty word list. Check that duolingo.com/practice-hub/words shows your words."
                )
            key, entry = course_entry(store, learning, source)
            new = merge(entry, lexemes, stamp, full=True)
            store["current"] = key
            read_key = key
            known = language_courses(user_id, jwt)
            if known is not None:
                if not any(c["learning"] == learning and c["from"] == source for c in known):
                    known.append({"learning": learning, "from": source, "name": entry["name"]})
                    known.sort(key=lambda c: (c["learning"], c["from"]))
                if store.get("known") != known:
                    store["known"] = known
            if total is not None:
                entry["duolingo_total"] = total
            line = f"{entry['name']}: {len(entry['words'])} words, {len(new)} new"
            if new:
                line += ": " + ", ".join(new[:12]) + (", …" if len(new) > 12 else "")
            notes.insert(0, line)
            try:
                phrases_line = update_key_phrases(course, learning, source)
                if phrases_line:
                    notes.append(phrases_line)
            except Exception as err:  # noqa: BLE001  the words matter more than the key phrases
                warn(f"Couldn't update the key phrases ({err}).")
        except SyncError as err:
            error = str(err)

    if not pronounce.espeak_path():
        notes.append("eSpeak NG isn't installed here, so no new pronunciations were written.")
    for entry in store["courses"].values():
        written = finish_words(entry, overrides)
        if written:
            notes.append(f"Wrote {written} pronunciation{'s' if written != 1 else ''} for {entry['name']}.")
        entry["words"].sort(key=lambda w: -w.get("seq", 0))
        entry["count"] = len(entry["words"])
    for key, entry in store["courses"].items():
        if before_courses.get(key) != fingerprint(entry):
            entry["updated"] = stamp

    if json.dumps(store, sort_keys=True, ensure_ascii=False) != before:
        store["updated"] = stamp
        DATA.mkdir(parents=True, exist_ok=True)
        WORDS_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        notes.append("Saved data/words.json.")
    else:
        notes.append("No changes to save.")

    error = error or overrides_error
    report(notes, error, setup, read_key)
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
