#!/usr/bin/env python3
"""Pronunciations for the important sentences (the "Frases importantes" tab).

data/frases.json holds the sentences, written by hand, and data/guidebook.json
the key phrases the sync saves from each Duolingo unit's Guidebook. This script
writes data/frases-pron.json: each sentence read with Spanish letters, put
together from the pronunciations of your own words in data/words.json. Your
fixes to a word carry over to every sentence that uses it ("croissant" reads
"quasan" everywhere). Words that aren't in your notebook yet, like names, go
through eSpeak NG one at a time.

To fix a whole sentence, add it to data/overrides.json under "fr", like a word
(or use Editar on the page).

The sync workflow runs this on every run. To run it by hand:

    python3 scripts/frases.py

Without eSpeak NG installed, a sentence with a word that isn't in your notebook
keeps the pronunciation it had before.

Two more commands help keep the list growing (see scripts/frases-guide.md,
which the daily review follows):

    python3 scripts/frases.py --todo   # what's new since the last review
    python3 scripts/frases.py --check  # is data/frases.json in order?

--todo lists the key phrases from your Duolingo units that aren't in a group
yet and the words you've learned since the last review ("words_reviewed" in
data/frases.json), with your whole notebook for writing new sentences.
--check makes sure every sentence has its meaning and note, nothing is there
twice, and the sentences that aren't Duolingo's only use words from your
notebook. It exits with 1 if something needs fixing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pronounce  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "frases.json"
GUIDEBOOK = DATA / "guidebook.json"
WORDS = DATA / "words.json"
OVERRIDES = DATA / "overrides.json"
OUT = DATA / "frases-pron.json"

MAX_SPAN = 6  # the longest phrase from your notebook to look for, in words

# Liaison: these words run into the next one when it starts with a vowel, so
# "un éclair" reads "an necler" and "vous avez" reads "vu zavé".
LIAISON = {
    "fr": {
        **dict.fromkeys(["un", "mon", "ton", "son", "aucun", "on", "en"], "n"),
        **dict.fromkeys(["les", "des", "mes", "tes", "ses", "ces", "nous", "vous", "ils", "elles",
                         "aux", "deux", "trois", "dans", "chez", "quels", "quelles", "leurs"], "z"),
    },
}
VOWEL_START = re.compile(r"^[aeiouyàâäéèêëîïôöùûüœæ]", re.I)
PAUSE = re.compile(r"[,;:.!?…]+")
EDGES = " .,;:!?¿¡…«»\"“”()"


def clean(text: str) -> str:
    """The form a sentence is stored under: NFC, plain spaces, straight apostrophes."""
    text = unicodedata.normalize("NFC", str(text))
    for odd in (" ", " ", " "):
        text = text.replace(odd, " ")
    return " ".join(text.replace("’", "'").split())


def look_key(text: str) -> str:
    """How a word or phrase is looked up in your notebook."""
    return clean(text).lower().strip(EDGES)


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def notebook_for(words: dict, lang: str) -> tuple[dict, list[str]]:
    """Your words in that language, word -> pronunciation, and the courses' source languages."""
    index, sources = {}, []
    for course in (words.get("courses") or {}).values():
        if not isinstance(course, dict) or course.get("learning") != lang:
            continue
        sources.append(course.get("from") or "")
        for w in course.get("words") or []:
            if isinstance(w, dict) and isinstance(w.get("text"), str) and w.get("pron"):
                index.setdefault(look_key(w["text"]), w["pron"])
    return index, sources


def sentences_for(source: dict, guidebook: dict, lang: str) -> list[str]:
    out = []
    for group in (source.get(lang) or {}).get("groups") or []:
        for item in group.get("sentences") or []:
            if isinstance(item, dict) and isinstance(item.get("fr"), str) and item["fr"].strip():
                out.append(clean(item["fr"]))
    for key, entry in guidebook.items():
        if not key.startswith(lang + "-") or not isinstance(entry, dict):
            continue
        for unit in entry.get("units") or []:
            for ph in unit.get("phrases") or []:
                if isinstance(ph, dict) and isinstance(ph.get("fr"), str) and ph["fr"].strip():
                    out.append(clean(ph["fr"]))
    return list(dict.fromkeys(out))


def fixes_for(overrides: dict, lang: str, sources: list[str]) -> dict:
    """Your fixes for whole sentences, from the same table the sync reads for words."""
    table = next((overrides.get(f"{lang}-{s}") for s in sources if overrides.get(f"{lang}-{s}")), None)
    table = table or overrides.get(lang) or {}
    fixes = {}
    if isinstance(table, dict):
        for text, fix in table.items():
            if text.startswith("_"):
                continue
            if isinstance(fix, dict):
                fix = fix.get("pron")
            if isinstance(fix, str) and fix.strip():
                fixes[clean(text)] = " ".join(unicodedata.normalize("NFC", fix).split())
    return fixes


class Speller:
    def __init__(self, lang: str, notebook: dict):
        self.lang = lang
        self.notebook = notebook
        self.spoken: dict[str, str | None] = {}  # eSpeak's answers, word by word
        self.links = LIAISON.get(lang, {})

    def word(self, token: str) -> str | None:
        key = look_key(token)
        if key not in self.spoken:
            spelled, _ = pronounce.pronounce(token.strip(EDGES), self.lang)
            self.spoken[key] = spelled
        return self.spoken[key]

    def chunk(self, chunk: str) -> str | None:
        tokens = chunk.split()
        keys = [look_key(t) for t in tokens]
        units: list[tuple[str, str, str]] = []  # (first word, last word, how it reads)
        i = 0
        while i < len(tokens):
            for j in range(min(len(tokens), i + MAX_SPAN), i, -1):
                phrase = " ".join(keys[i:j])
                if phrase in self.notebook:
                    units.append((keys[i], keys[j - 1], self.notebook[phrase]))
                    i = j
                    break
            else:
                spelled = self.word(tokens[i])
                if not spelled:
                    return None
                units.append((keys[i], keys[i], spelled))
                i += 1
        out = []
        for n, (first, _, spelled) in enumerate(units):
            before = units[n - 1][1] if n else ""
            if before in self.links and VOWEL_START.match(first):
                spelled = self.links[before] + spelled
            out.append(spelled)
        return " ".join(out)

    def sentence(self, text: str) -> str | None:
        """A comma wherever the sentence pauses; no final punctuation."""
        parts = [p.strip() for p in PAUSE.split(clean(text)) if p.strip(EDGES)]
        spelled = [self.chunk(p) for p in parts]
        if not spelled or any(s is None for s in spelled):
            return None
        return ", ".join(spelled)


# --- Keeping the list growing: --todo and --check ----------------------------

def notebook_words(words: dict, lang: str) -> list[dict]:
    """Every word in your notebooks for that language, oldest first."""
    seen, out = set(), []
    for course in (words.get("courses") or {}).values():
        if not isinstance(course, dict) or course.get("learning") != lang:
            continue
        for w in course.get("words") or []:
            if not isinstance(w, dict) or not isinstance(w.get("text"), str):
                continue
            key = look_key(w["text"])
            if key and key not in seen:
                seen.add(key)
                out.append(w)
    return sorted(out, key=lambda w: (w.get("added") or "", w.get("seq") or 0))


def key_phrases(guidebook: dict, lang: str) -> list[dict]:
    """Duolingo's key phrases for that language, unit by unit, without repeats."""
    out, seen = [], set()
    for key, entry in guidebook.items():
        if not key.startswith(lang + "-") or not isinstance(entry, dict):
            continue
        for unit in entry.get("units") or []:
            for ph in unit.get("phrases") or []:
                if not (isinstance(ph, dict) and isinstance(ph.get("fr"), str) and ph["fr"].strip()):
                    continue
                k = look_key(ph["fr"])
                if k in seen:
                    continue
                seen.add(k)
                out.append({**ph, "section": unit.get("section") or 0, "unit": unit.get("unit") or 0,
                            "title": unit.get("title") or ""})
    return out


def placed(part: dict) -> dict:
    """Every sentence already in a group, by how it's looked up, with its group."""
    out = {}
    for group in part.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("sentences") or []:
            if isinstance(item, dict) and isinstance(item.get("fr"), str):
                out.setdefault(look_key(item["fr"]), group.get("id"))
    return out


def outside_notebook(text: str, vocab: set[str]) -> tuple[list[str], list[str]]:
    """Words of a sentence that aren't in your notebook, and the ones taken as names.

    A phrase from your notebook counts as a whole ("s'il vous plaît"). A
    capitalized word that isn't in the notebook is taken as a name (Marie,
    Lyon), except as the very first word of the sentence.
    """
    unknown, names, first = [], [], True
    for part in PAUSE.split(clean(text)):
        tokens = [t for t in part.split() if look_key(t)]
        keys = [look_key(t) for t in tokens]
        i = 0
        while i < len(tokens):
            for j in range(min(len(tokens), i + MAX_SPAN), i, -1):
                if " ".join(keys[i:j]) in vocab:
                    i = j
                    break
            else:
                word = tokens[i].strip(EDGES)
                if word[:1].isupper() and not first:
                    names.append(word)
                else:
                    unknown.append(word)
                i += 1
            first = False
    return unknown, names


def todo(lang: str = "fr") -> int:
    source = load(SOURCE, None)
    if not isinstance(source, dict) or not isinstance(source.get(lang), dict):
        print(f"data/frases.json has no part for {lang!r}.")
        return 1
    part = source[lang]
    guidebook = load(GUIDEBOOK, {})
    words = load(WORDS, {})
    guidebook = guidebook if isinstance(guidebook, dict) else {}
    words = words if isinstance(words, dict) else {}

    have = placed(part)
    fresh = [ph for ph in key_phrases(guidebook, lang) if look_key(ph["fr"]) not in have]
    notebook = notebook_words(words, lang)
    reviewed = part.get("words_reviewed")
    reviewed = reviewed if isinstance(reviewed, int) else 0
    newest = max((w.get("seq") or 0 for w in notebook), default=0)
    new_words = [w for w in notebook if (w.get("seq") or 0) > reviewed]

    if not fresh and not new_words:
        print(f"Nothing new: every key phrase is in a group and no word came after #{reviewed}.")
        return 0

    def means(w: dict) -> str:
        return ", ".join(w.get("translations") or []) or "?"

    print(f"== Key phrases from Duolingo that aren't in a group yet ({len(fresh)}) ==")
    unit = None
    for ph in fresh:
        here = (ph["section"], ph["unit"])
        if here != unit:
            unit = here
            print(f"Section {ph['section'] + 1}, unit {ph['unit'] + 1}: {ph['title'] or '(no title)'}")
        print(f"  {ph['fr']}  =  {ph.get('es') or '?'}")
    if not fresh:
        print("  (none)")

    print(f"\n== Words learned since the last review ({len(new_words)}; words_reviewed is {reviewed}, newest is {newest}) ==")
    for w in new_words:
        print(f"  #{w.get('seq')}  {w['text']}  =  {means(w)}")
    if not new_words:
        print("  (none)")

    print(f"\n== Your whole notebook ({len(notebook)} words; your own sentences can only use these, plus names) ==")
    print("  " + " | ".join(f"{w['text']} ({means(w)})" for w in notebook))

    print("\n== Groups now ==")
    for group in part.get("groups") or []:
        items = [x for x in group.get("sentences") or [] if isinstance(x, dict)]
        stars = sum(1 for x in items if x.get("star"))
        print(f"  {group.get('id')}: {group.get('title')} ({len(items)} sentences, {stars} with a star)")
        for x in items:
            print(f"      {'★ ' if x.get('star') else ''}{x.get('fr')}")

    print(f"\nWhen you're done, set \"words_reviewed\" to {newest} and run: python3 scripts/frases.py --check")
    return 0


def check(lang_only: str | None = None) -> int:
    source = load(SOURCE, None)
    if not isinstance(source, dict):
        print("data/frases.json isn't valid JSON.")
        return 1
    guidebook = load(GUIDEBOOK, {})
    words = load(WORDS, {})
    guidebook = guidebook if isinstance(guidebook, dict) else {}
    words = words if isinstance(words, dict) else {}
    problems: list[str] = []
    notes: list[str] = []
    for lang, part in source.items():
        if lang.startswith("_") or (lang_only and lang != lang_only):
            continue
        if not isinstance(part, dict) or not isinstance(part.get("groups"), list):
            problems.append(f"{lang}: needs a \"groups\" list.")
            continue
        notebook = notebook_words(words, lang)
        vocab = {look_key(w["text"]) for w in notebook}
        newest = max((w.get("seq") or 0 for w in notebook), default=0)
        duo = {look_key(ph["fr"]) for ph in key_phrases(guidebook, lang)}
        reviewed = part.get("words_reviewed")
        if not isinstance(reviewed, int) or reviewed < 0:
            problems.append(f"{lang}: \"words_reviewed\" should be a whole number (the newest word now is #{newest}).")
        elif reviewed > newest and notebook:
            problems.append(f"{lang}: \"words_reviewed\" is {reviewed}, but the newest word is #{newest}.")
        ids, seen, total, stars, all_names = set(), {}, 0, 0, set()
        for gi, group in enumerate(part["groups"]):
            if not isinstance(group, dict):
                problems.append(f"{lang}: group {gi + 1} isn't an object.")
                continue
            gid = group.get("id")
            where = f"{lang}/{gid or gi + 1}"
            if not isinstance(gid, str) or not re.fullmatch(r"[a-z0-9-]+", gid):
                problems.append(f"{where}: the id should be lowercase letters, digits and dashes.")
            elif gid in ids:
                problems.append(f"{where}: two groups have this id.")
            ids.add(gid)
            if not isinstance(group.get("title"), str) or not group["title"].strip():
                problems.append(f"{where}: needs a title.")
            items = group.get("sentences")
            if not isinstance(items, list) or not items:
                problems.append(f"{where}: needs at least one sentence.")
                continue
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("fr"), str) or not item["fr"].strip():
                    problems.append(f"{where}: a sentence has no \"fr\".")
                    continue
                fr = item["fr"]
                total += 1
                stars += bool(item.get("star"))
                key = look_key(fr)
                if key in seen:
                    problems.append(f"{where}: «{fr}» is also in {seen[key]}.")
                seen[key] = where
                for field in ("es", "use"):
                    if not isinstance(item.get(field), str) or not item[field].strip():
                        problems.append(f"{where}: «{fr}» needs \"{field}\".")
                if "star" in item and not isinstance(item["star"], bool):
                    problems.append(f"{where}: «{fr}»: \"star\" should be true or false.")
                if "added" in item and not (isinstance(item["added"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["added"])):
                    problems.append(f"{where}: «{fr}»: \"added\" should be a date like 2026-11-15.")
                for field in ("fr", "es", "use"):
                    if isinstance(item.get(field), str) and re.search("[–—]", item[field]):
                        problems.append(f"{where}: «{fr}»: \"{field}\" has a long dash; use a comma or a period.")
                if key in duo or not vocab:
                    continue
                unknown, names = outside_notebook(fr, vocab)
                all_names.update(names)
                if unknown:
                    problems.append(f"{where}: «{fr}» uses words that aren't in the notebook: {', '.join(unknown)}.")
        left = sum(1 for k in duo if k not in seen)
        notes.append(f"{lang}: {total} sentences in {len(ids)} groups, {stars} with a star" +
                     (f"; {left} key phrase{'s' if left != 1 else ''} from Duolingo not in a group yet" if left else "") +
                     (f"; taken as names: {', '.join(sorted(all_names))}" if all_names else "") + ".")
    for line in notes:
        print(line)
    if problems:
        print(f"\n{len(problems)} thing{'s' if len(problems) != 1 else ''} to fix:")
        for line in problems:
            print(f"  - {line}")
        return 1
    print("All good.")
    return 0


def main() -> int:
    source = load(SOURCE, None)
    if not isinstance(source, dict):
        print("Couldn't read data/frases.json. The important sentences keep their last version.")
        return 0
    guidebook = load(GUIDEBOOK, {})
    words = load(WORDS, {})
    overrides = load(OVERRIDES, {})
    old = load(OUT, {})
    guidebook = guidebook if isinstance(guidebook, dict) else {}
    overrides = overrides if isinstance(overrides, dict) else {}
    old = old if isinstance(old, dict) else {}

    result = {"version": 1}
    for lang, part in source.items():
        if lang.startswith("_") or not isinstance(part, dict):
            continue
        notebook, sources = notebook_for(words, lang)
        fixes = fixes_for(overrides, lang, sources)
        speller = Speller(lang, notebook)
        before = old.get(lang) if isinstance(old.get(lang), dict) else {}
        table, missing = {}, 0
        for text in sentences_for(source, guidebook, lang):
            if text in fixes:
                table[text] = [fixes[text], "you"]
                continue
            spelled = speller.sentence(text)
            if spelled:
                table[text] = [spelled]
            elif isinstance(before.get(text), list) and before[text] and before[text][1:] != ["you"]:
                table[text] = before[text][:1]  # keep what it had until eSpeak is around
            else:
                missing += 1
        result[lang] = table
        from_espeak = sorted(k for k, v in speller.spoken.items() if v)
        print(f"{lang}: {len(table)} sentences read" + (f", {missing} still without a reading" if missing else "") +
              (f"; eSpeak read {', '.join(from_espeak)}" if from_espeak else "") + ".")
        if missing and not pronounce.espeak_path():
            print("eSpeak NG isn't installed here, so words outside your notebook couldn't be read.")

    text = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    if OUT.exists() and OUT.read_text(encoding="utf-8") == text:
        print("No changes to data/frases-pron.json.")
    else:
        OUT.write_text(text, encoding="utf-8")
        print("Saved data/frases-pron.json.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Readings for the important sentences, and help to keep them growing.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--todo", action="store_true", help="list new key phrases and words since the last review")
    mode.add_argument("--check", action="store_true", help="check data/frases.json")
    args = parser.parse_args()
    if args.todo:
        sys.exit(todo())
    if args.check:
        sys.exit(check())
    try:
        sys.exit(main())
    except Exception as err:  # noqa: BLE001  never break the word sync because of the sentences
        print(f"The important sentences couldn't be read: {err}")
        sys.exit(0)
