"""Pronunciations written with Spanish letters.

eSpeak NG, a free speech program, turns a word into IPA (the alphabet
linguists use to write sounds). This file turns that IPA into letters a
Spanish speaker can read out loud:

    French "bonjour"   -> IPA "bɔ̃ʒˈuʁ"   -> "bonyur"
    French "merci"     -> IPA "mɛʁsˈi"   -> "mersí"
    French "croissant" -> IPA "kʁwasˈɑ̃"  -> "cruasán"

Accents follow normal Spanish spelling rules, so "mersí" gets one and
"bonyur" doesn't (Spanish already stresses the end of a word ending in r).

Every choice about how a sound is written is in the tables below, so a choice
you don't like is a one-line change. After editing them, add 1 to VERSION and
the next sync redoes the pronunciations it made before (your manual fixes in
data/overrides.json are never touched).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata

VERSION = 2

# Duolingo course code -> the eSpeak NG voice that reads that language.
VOICES = {
    "ar": "ar", "ca": "ca", "cs": "cs", "cy": "cy", "da": "da", "de": "de",
    "el": "el", "en": "en-us", "eo": "eo", "es": "es", "fi": "fi", "fr": "fr",
    "ga": "ga", "he": "he", "hi": "hi", "hu": "hu", "id": "id", "it": "it",
    "ja": "ja", "ko": "ko", "la": "la", "nb": "nb", "nl": "nl", "no": "nb",
    "pl": "pl", "pt": "pt-br", "ro": "ro", "ru": "ru", "sv": "sv", "sw": "sw",
    "tr": "tr", "uk": "uk", "vi": "vi", "zh": "cmn", "zs": "cmn",
}

# Vowels. Spanish has five, so most IPA vowels fold into one of them.
# Two letters Spanish doesn't use are kept because the sounds really differ:
#   ü = say "i" with your lips rounded as for "u" (French "tu", German "über")
#   ö = say "e" with your lips rounded as for "o" (French "deux", German "schön")
VOWELS = {
    "a": "a", "ɑ": "a", "æ": "a", "ɐ": "a", "ʌ": "a", "ɒ": "o",
    "e": "e", "ɛ": "e", "ə": "e", "ɜ": "e", "ɘ": "e", "ɞ": "e",
    "i": "i", "ɪ": "i", "ɨ": "i", "ᵻ": "i",
    "o": "o", "ɔ": "o", "ɤ": "o",
    "u": "u", "ʊ": "u", "ɯ": "u", "ʉ": "u",
    "y": "ü", "ʏ": "ü",
    "ø": "ö", "œ": "ö", "ɶ": "ö",
}

# How eSpeak writes some sounds differs by language. For Brazilian Portuguese
# it writes the unstressed final e ("leite") as y and adds a tiny vowel after
# r ("jardim" -> ʒaɾədʒˈiŋ), so those two read differently there ("" = skip).
LANG_VOWELS = {"pt": {"y": "i", "ə": ""}}

# Nasal vowels (French "bon", "an", "vin") are written as the vowel plus n,
# or m before p and b, the way Spanish writes "campo". These vowels get a
# different letter when they're nasal.
NASAL_VOWELS = {"œ": "e"}  # French "un" sounds like "en" to Spanish ears

CONSONANTS = {
    "p": "p", "b": "b", "t": "t", "d": "d", "ɟ": "y",
    "f": "f", "v": "v", "s": "s", "z": "z",
    "ʃ": "sh", "ɕ": "sh", "ʂ": "sh",
    "x": "j", "χ": "j", "ç": "j", "h": "j", "ɦ": "j", "ħ": "j",
    "θ": "z", "ð": "d", "β": "b", "ɣ": "g", "ʋ": "v", "ɸ": "f",
    "m": "m", "n": "n", "ɲ": "ñ", "ŋ": "ng", "ɴ": "n", "ɱ": "m",
    "l": "l", "ɫ": "l", "ʎ": "ll", "ɭ": "l", "ʟ": "l",
    "r": "r", "ɾ": "r", "ʁ": "r", "ʀ": "r", "ɹ": "r", "ɻ": "r", "ɽ": "r",
    "ʔ": "",
    # Sounds whose spelling depends on what comes next (see _consonant):
    "k": "k", "q": "k", "c": "k", "g": "g", "ɡ": "g",
    "ʒ": "zh", "ʑ": "zh", "ʐ": "zh",
}

# Two-symbol sounds, matched before single symbols.
AFFRICATES = {
    "tʃ": "ch", "tɕ": "ch", "tʂ": "ch",
    "dʒ": "y", "dʑ": "y", "dʐ": "y",
    "ts": "ts", "dz": "ds", "pf": "pf",
}

# Sounds that glide into a vowel, like the i in "bien" or the u in "cuando".
GLIDES = {"j": "i", "w": "u", "ɥ": "ü", "ʍ": "u"}

STRONG = set("aeoö")
WEAK = set("iuü")
ACUTE = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "ü": "ǘ", "ö": "ö́"}

_LANG_TAG = re.compile(r"\([a-z]{2,3}(?:-[a-z0-9]+)?\)")
_SPLIT = re.compile(r"[\s|‖_]+")


class _Tok:
    __slots__ = ("kind", "ipa", "nasal", "stress")

    def __init__(self, kind: str, ipa: str, stress: bool = False):
        self.kind = kind  # "V" vowel, "C" consonant, "G" glide
        self.ipa = ipa
        self.nasal = False
        self.stress = stress


def _tokens(word: str) -> list[_Tok]:
    s = unicodedata.normalize("NFD", word)
    s = s.replace("c\u0327", "ç")  # NFD splits ç (German "ich") into c + cedilla
    s = s.replace("͡", "").replace("͜", "")  # tie bars, as in t͡ʃ
    s = s.replace("ɚ", "ər").replace("ɝ", "ɜr").replace("˞", "r")
    toks: list[_Tok] = []
    stress = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "ˈ":
            stress = True
            i += 1
            continue
        pair = s[i:i + 2]
        if pair in AFFRICATES:
            toks.append(_Tok("C", pair))
            i += 2
        elif ch in VOWELS:
            tok = _Tok("V", ch, stress)
            stress = False
            i += 1
            while i < len(s) and unicodedata.combining(s[i]):
                if s[i] == "̃":
                    tok.nasal = True
                elif s[i] == "̯":  # non-syllabic, as in German "Uhr"
                    tok.kind = "G"
                    stress, tok.stress = tok.stress, False
                i += 1
            toks.append(tok)
            continue
        elif ch in GLIDES:
            toks.append(_Tok("G", ch))
            i += 1
        elif ch in CONSONANTS:
            toks.append(_Tok("C", ch))
            i += 1
        elif ch == "ʲ":  # palatalized, as in Russian "нет"
            toks.append(_Tok("G", "j"))
            i += 1
        elif ch == "ʷ":
            toks.append(_Tok("G", "w"))
            i += 1
        else:  # length marks, secondary stress, unknown symbols
            i += 1
            continue
        while i < len(s) and unicodedata.combining(s[i]):
            i += 1
    return toks


def _letters_of(tok: _Tok | None, vowels: dict | None = None) -> str:
    """The first Spanish letter a token will be written with (for lookahead)."""
    if tok is None:
        return ""
    if tok.kind == "V":
        if tok.nasal and tok.ipa in NASAL_VOWELS:
            return NASAL_VOWELS[tok.ipa]
        return (vowels or {}).get(tok.ipa, VOWELS[tok.ipa])
    if tok.kind == "G":
        return GLIDES.get(tok.ipa, VOWELS.get(tok.ipa, ""))
    return AFFRICATES.get(tok.ipa) or CONSONANTS.get(tok.ipa, "")


def _consonant(tok: _Tok, nxt: _Tok | None, vowels: dict | None = None) -> list[tuple[str, bool]]:
    sym = tok.ipa
    front = _letters_of(nxt, vowels)[:1] in ("e", "i")
    if sym in ("k", "q", "c"):
        spelled = "qu" if front else "c"
    elif sym in ("g", "ɡ"):
        spelled = "gu" if front else "g"
    elif sym in ("ʒ", "ʑ", "ʐ"):
        # The French "j" sound: "y" before a vowel (bonjour -> bonyur),
        # "sh" at the end of a word or before a consonant (fromage -> fromash).
        spelled = "y" if nxt is not None and nxt.kind in ("V", "G") else "sh"
    else:
        spelled = AFFRICATES.get(sym) or CONSONANTS.get(sym, "")
    # The u in "que"/"gue" is silent, so it isn't a vowel for the accent rules.
    return [(ch, False) for ch in spelled]


def _spell_word(ipa_word: str, lang: str | None = None) -> str:
    vowels = LANG_VOWELS.get(lang or "", {})
    toks = []
    carry = False
    for tok in _tokens(ipa_word):
        if tok.kind == "V" and vowels.get(tok.ipa) == "":
            carry = carry or tok.stress  # skipped vowel: hand any stress to the next one
            continue
        if carry and tok.kind == "V":
            tok.stress, carry = True, False
        toks.append(tok)
    out: list[list] = []  # [letter, is_vowel, is_stressed]
    pending_nasal = False

    def flush_nasal(next_tok: _Tok | None) -> None:
        nonlocal pending_nasal
        if not pending_nasal:
            return
        if (next_tok is not None and next_tok.kind == "V" and not next_tok.stress
                and (next_tok.nasal or _letters_of(next_tok, vowels) in ("i", "u"))):
            return  # a nasal diphthong ("não" -> naun, "mãe" -> main): the n goes after both vowels
        pending_nasal = False
        if next_tok is not None and next_tok.kind == "C" and next_tok.ipa in ("n", "m", "ɲ", "ŋ"):
            return  # "ennui": the real n already follows
        letter = "m" if next_tok is not None and next_tok.kind == "C" and next_tok.ipa[0] in "pb" else "n"
        out.append([letter, False, False])

    for idx, tok in enumerate(toks):
        nxt = toks[idx + 1] if idx + 1 < len(toks) else None
        if tok.kind != "G":
            flush_nasal(tok)
        if tok.kind == "C":
            # A doubled sound is written once (Italian "bello", "cappuccino").
            if nxt is not None and nxt.kind == "C" and (
                nxt.ipa == tok.ipa or (len(nxt.ipa) == 2 and nxt.ipa[0] == tok.ipa)
            ):
                continue
            if tok.ipa == "ŋ" and (nxt is None or nxt.kind != "V"):
                # Closing a syllable, ŋ is how eSpeak marks a nasal vowel in Portuguese
                # ("bem" -> bein, "com" -> con); Spanish writes it n, or m before p/b.
                if not (out and out[-1][0] in ("n", "m")):
                    out.append(["m" if nxt is not None and nxt.ipa[:1] in "pb" else "n", False, False])
                continue
            for ch, is_vowel in _consonant(tok, nxt, vowels):
                out.append([ch, is_vowel, False])
        elif tok.kind == "G":
            letter = GLIDES.get(tok.ipa) or VOWELS.get(tok.ipa, "")
            if tok.ipa == "w" and out and out[-1][0] == "u":
                continue
            if tok.ipa == "j":
                # Spanish writes this sound as "y" after an i ("fille" -> "fiy"),
                # between vowels ("voyage" -> "vuayash"), at the start of a word
                # ("hier" -> "yer") and at the end ("travail" -> "travay", like
                # "hoy"), and as "i" elsewhere ("bien").
                next_is_vowel = nxt is not None and nxt.kind == "V"
                after_vowel = bool(out) and out[-1][1]
                if (out and out[-1][0] == "i") or (next_is_vowel and (not out or after_vowel)) or (nxt is None and after_vowel and not pending_nasal):
                    letter = "y"
            if letter:
                out.append([letter, letter in STRONG or letter in WEAK, False])
        else:
            plain = vowels.get(tok.ipa, VOWELS[tok.ipa])
            letter = NASAL_VOWELS.get(tok.ipa, plain) if tok.nasal else plain
            out.append([letter, True, tok.stress])
            if tok.nasal:
                pending_nasal = True
    flush_nasal(None)

    _add_accent(out)
    return "".join(letter for letter, _, _ in out)


def _add_accent(out: list[list]) -> None:
    """Write an accent where Spanish spelling rules need one."""
    nuclei: list[list[int]] = []
    i = 0
    while i < len(out):
        if not out[i][1]:
            i += 1
            continue
        group = []
        while i < len(out) and out[i][1]:
            group.append(i)
            i += 1
        cur = [group[0]]
        for a, b in zip(group, group[1:]):
            la, lb = out[a][0], out[b][0]
            hiatus = (
                (la in STRONG and lb in STRONG)
                or (lb in WEAK and out[b][2] and la in STRONG)
                or (la in WEAK and out[a][2] and lb in STRONG)
            )
            if hiatus:
                nuclei.append(cur)
                cur = [b]
            else:
                cur.append(b)
        nuclei.append(cur)

    if len(nuclei) < 2:
        return  # one-syllable words don't take an accent
    stressed = next((k for k, nuc in enumerate(nuclei) if any(out[x][2] for x in nuc)), None)
    if stressed is None:
        return
    nuc = nuclei[stressed]

    def is_strong(idx: int) -> bool:
        return 0 <= idx < len(out) and out[idx][1] and out[idx][0] in STRONG

    # A stressed i or u right next to a, e or o always carries the accent (país, río).
    forced = len(nuc) == 1 and out[nuc[0]][0] in WEAK and (is_strong(nuc[0] - 1) or is_strong(nuc[0] + 1))
    last = out[-1][0]
    ends_soft = out[-1][1] or (last in ("n", "s") and len(out) > 1 and out[-2][1])
    default = len(nuclei) - 2 if ends_soft else len(nuclei) - 1
    if forced or stressed != default:
        # The accent goes on a/e/o when the syllable has one; between two of
        # i/u/ü it goes on the one that's stressed (Portuguese "Brasil" -> "brazíu").
        stressed_letter = next((x for x in nuc if out[x][2]), nuc[-1])
        target = next((x for x in nuc if out[x][0] in STRONG), stressed_letter)
        out[target][0] = ACUTE[out[target][0]]


def to_spanish(ipa: str, lang: str | None = None) -> str:
    """Turn eSpeak IPA (one word or a phrase) into Spanish-letter spelling."""
    ipa = _LANG_TAG.sub(" ", ipa or "")
    words = [w for w in _SPLIT.split(ipa.strip()) if w]
    return " ".join(spelled for spelled in (_spell_word(w, lang) for w in words) if spelled)


def espeak_path() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def ipa_for(text: str, lang: str) -> str | None:
    """Ask eSpeak NG for the IPA of a word. None if eSpeak can't do it."""
    exe = espeak_path()
    voice = VOICES.get(lang)
    if not exe or not voice or not text.strip():
        return None
    for name in dict.fromkeys([voice, lang]):  # e.g. "pt-br", then plain "pt"
        try:
            result = subprocess.run(
                [exe, "-q", "--ipa", "-v", name],
                input=text, capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        ipa = " ".join(_LANG_TAG.sub(" ", result.stdout).split())
        if result.returncode == 0 and ipa:
            return ipa
    return None


def pronounce(text: str, lang: str) -> tuple[str | None, str | None]:
    """Return (Spanish-letter pronunciation, IPA) for a word, or (None, None)."""
    ipa = ipa_for(text, lang)
    if not ipa:
        return None, None
    spelled = to_spanish(ipa, lang)
    return (spelled or None), ipa
