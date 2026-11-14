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
"""

from __future__ import annotations

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
    try:
        sys.exit(main())
    except Exception as err:  # noqa: BLE001  never break the word sync because of the sentences
        print(f"The important sentences couldn't be read: {err}")
        sys.exit(0)
