#!/usr/bin/env python3
"""Build the class notebook (the "Aula" tab of the Portuguese notebook).

data/aula.json holds what you learned in class, written by hand. This script:

  1. conjugates every verb listed there in the tenses from class and writes
     data/aula-verbos.json,
  2. writes a pronunciation with Spanish letters for every word and verb form,
     the same way scripts/sync.py does for your Duolingo words, into
     data/aula-pron.json. Earlier results are reused, so after the first run it
     only works on what's new.

Your fixes in data/overrides.json under "pt" apply here too.

The sync workflow runs this on every run. To run it by hand:

    python3 scripts/aula.py

Without eSpeak NG installed it still writes the verb tables and keeps the
pronunciations it already had.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pronounce  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "aula.json"
VERBS_OUT = DATA / "aula-verbos.json"
PRON_OUT = DATA / "aula-pron.json"
OVERRIDES = DATA / "overrides.json"

PERSONS = ["eu", "você, ele, ela", "nós", "vocês, eles, elas"]
TENSES = [
    ("pres", "Presente"),
    ("pret", "Pretérito perfeito"),
    ("imp", "Imperfeito"),
    ("ir", "Futuro com ir"),
    ("fut", "Futuro do presente"),
    ("sp", "Presente do subjuntivo"),
    ("sf", "Futuro do subjuntivo"),
    ("ip", "Infinitivo pessoal"),
]
REFLEXIVE = ["me", "se", "nos", "se"]


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# --- Conjugation ------------------------------------------------------------
#
# Regular verbs follow the endings below. Spelling changes that keep a sound
# (ficar -> fiquei, conhecer -> conheço) are part of the regular pattern, so
# they don't count as irregular. Everything else is listed by hand.

def split(inf: str) -> tuple[str, str]:
    if inf == "pôr":
        return "p", "or"
    return inf[:-2], inf[-2:]


def soft_e(stem: str) -> str:
    """-ar verbs before e: fic -> fiqu, jog -> jogu, danç -> danc."""
    if stem.endswith("c"):
        return stem[:-1] + "qu"
    if stem.endswith("g"):
        return stem[:-1] + "gu"
    if stem.endswith("ç"):
        return stem[:-1] + "c"
    return stem


def soft_ao(stem: str) -> str:
    """-er/-ir verbs before o and a: conhec -> conheç, proteg -> protej, segu -> seg."""
    if stem.endswith("gu"):
        return stem[:-2] + "g"
    if stem.endswith("c"):
        return stem[:-1] + "ç"
    if stem.endswith("g"):
        return stem[:-1] + "j"
    return stem


def subj_from_eu(eu: str, end: str) -> list[str]:
    base = eu[:-1]
    if end == "ar":
        base = soft_e(base)
        return [base + "e", base + "e", base + "emos", base + "em"]
    return [base + "a", base + "a", base + "amos", base + "am"]


def fut_subj_from(pret_they: str) -> list[str]:
    base = pret_they[:-3]  # fizeram -> fize
    if base.endswith("í"):  # saíram -> sair, sairmos, saírem
        plain = base[:-1] + "i"
        return [plain + "r", plain + "r", plain + "rmos", base + "rem"]
    return [base + "r", base + "r", base + "rmos", base + "rem"]


FUTURE_STEM = {"fazer": "far", "dizer": "dir", "trazer": "trar", "pôr": "por"}


def regular(inf: str, eu: str | None = None) -> dict:
    stem, end = split(inf)
    if end == "ar":
        e = soft_e(stem)
        pres = [stem + "o", stem + "a", stem + "amos", stem + "am"]
        pret = [e + "ei", stem + "ou", stem + "amos", stem + "aram"]
        imp = [stem + "ava", stem + "ava", stem + "ávamos", stem + "avam"]
        ger, part = stem + "ando", stem + "ado"
    else:
        v = "e" if end == "er" else "i"
        pres = [soft_ao(stem) + "o", stem + "e", stem + v + "mos", stem + "em"]
        pret = [stem + "i", stem + ("eu" if v == "e" else "iu"), stem + v + "mos", stem + v + "ram"]
        imp = [stem + "ia", stem + "ia", stem + "íamos", stem + "iam"]
        ger, part = stem + v + "ndo", stem + "ido"
    if eu:
        pres[0] = eu
    return {
        "pres": pres,
        "pret": pret,
        "imp": imp,
        "fut": [inf + "ei", inf + "á", inf + "emos", inf + "ão"],
        "sp": subj_from_eu(pres[0], end),
        "sf": fut_subj_from(pret[3]),
        "ip": [inf, inf, inf + "mos", inf + "em"],
        "ger": ger,
        "part": part,
    }


# Present "eu" forms that change their vowel or consonant. The rest of the
# present is regular, and the present subjunctive is built from this form.
EU = {
    "dormir": "durmo", "cobrir": "cubro", "descobrir": "descubro", "tossir": "tusso",
    "preferir": "prefiro", "mentir": "minto", "sentir": "sinto", "vestir": "visto",
    "servir": "sirvo", "repetir": "repito", "competir": "compito", "sugerir": "sugiro",
    "seguir": "sigo", "conseguir": "consigo", "divertir": "divirto",
    "pedir": "peço", "ouvir": "ouço", "perder": "perco",
}

# Verbs with their own forms. Anything missing is built the regular way
# (the present subjunctive from the "eu" form, the future subjunctive from
# the "eles" form of the pretérito).
IRREGULAR = {
    "ser": {"pres": ["sou", "é", "somos", "são"], "pret": ["fui", "foi", "fomos", "foram"],
            "imp": ["era", "era", "éramos", "eram"], "sp": ["seja", "seja", "sejamos", "sejam"],
            "ger": "sendo", "part": "sido"},
    "estar": {"pres": ["estou", "está", "estamos", "estão"],
              "pret": ["estive", "esteve", "estivemos", "estiveram"],
              "sp": ["esteja", "esteja", "estejamos", "estejam"]},
    "ter": {"pres": ["tenho", "tem", "temos", "têm"], "pret": ["tive", "teve", "tivemos", "tiveram"],
            "imp": ["tinha", "tinha", "tínhamos", "tinham"]},
    "ir": {"pres": ["vou", "vai", "vamos", "vão"], "pret": ["fui", "foi", "fomos", "foram"],
           "sp": ["vá", "vá", "vamos", "vão"]},
    "vir": {"pres": ["venho", "vem", "vimos", "vêm"], "pret": ["vim", "veio", "viemos", "vieram"],
            "imp": ["vinha", "vinha", "vínhamos", "vinham"], "part": "vindo"},
    "ver": {"pres": ["vejo", "vê", "vemos", "veem"], "pret": ["vi", "viu", "vimos", "viram"],
            "part": "visto"},
    "fazer": {"pres": ["faço", "faz", "fazemos", "fazem"], "pret": ["fiz", "fez", "fizemos", "fizeram"],
              "part": "feito"},
    "dizer": {"pres": ["digo", "diz", "dizemos", "dizem"],
              "pret": ["disse", "disse", "dissemos", "disseram"], "part": "dito"},
    "trazer": {"pres": ["trago", "traz", "trazemos", "trazem"],
               "pret": ["trouxe", "trouxe", "trouxemos", "trouxeram"]},
    "pôr": {"pres": ["ponho", "põe", "pomos", "põem"], "pret": ["pus", "pôs", "pusemos", "puseram"],
            "imp": ["punha", "punha", "púnhamos", "punham"], "ip": ["pôr", "pôr", "pormos", "porem"],
            "ger": "pondo", "part": "posto"},
    "saber": {"pres": ["sei", "sabe", "sabemos", "sabem"],
              "pret": ["soube", "soube", "soubemos", "souberam"],
              "sp": ["saiba", "saiba", "saibamos", "saibam"]},
    "querer": {"pres": ["quero", "quer", "queremos", "querem"],
               "pret": ["quis", "quis", "quisemos", "quiseram"],
               "sp": ["queira", "queira", "queiramos", "queiram"]},
    "poder": {"pres": ["posso", "pode", "podemos", "podem"],
              "pret": ["pude", "pôde", "pudemos", "puderam"]},
    "dar": {"pres": ["dou", "dá", "damos", "dão"], "pret": ["dei", "deu", "demos", "deram"],
            "sp": ["dê", "dê", "demos", "deem"]},
    "ler": {"pres": ["leio", "lê", "lemos", "leem"]},
    "sair": {"pres": ["saio", "sai", "saímos", "saem"], "pret": ["saí", "saiu", "saímos", "saíram"],
             "imp": ["saía", "saía", "saíamos", "saíam"], "sp": ["saia", "saia", "saiamos", "saiam"],
             "sf": ["sair", "sair", "sairmos", "saírem"], "ip": ["sair", "sair", "sairmos", "saírem"],
             "part": "saído"},
    "construir": {"pres": ["construo", "constrói", "construímos", "constroem"],
                  "pret": ["construí", "construiu", "construímos", "construíram"],
                  "imp": ["construía", "construía", "construíamos", "construíam"],
                  "sf": ["construir", "construir", "construirmos", "construírem"],
                  "ip": ["construir", "construir", "construirmos", "construírem"], "part": "construído"},
    "destruir": {"pres": ["destruo", "destrói", "destruímos", "destroem"],
                 "pret": ["destruí", "destruiu", "destruímos", "destruíram"],
                 "imp": ["destruía", "destruía", "destruíamos", "destruíam"],
                 "sf": ["destruir", "destruir", "destruirmos", "destruírem"],
                 "ip": ["destruir", "destruir", "destruirmos", "destruírem"], "part": "destruído"},
    # -ear and odiar add an i where the stress falls: passeio, odeio.
    "passear": {"pres": ["passeio", "passeia", "passeamos", "passeiam"],
                "sp": ["passeie", "passeie", "passeemos", "passeiem"]},
    "pentear": {"pres": ["penteio", "penteia", "penteamos", "penteiam"],
                "sp": ["penteie", "penteie", "penteemos", "penteiem"]},
    "barbear": {"pres": ["barbeio", "barbeia", "barbeamos", "barbeiam"],
                "sp": ["barbeie", "barbeie", "barbeemos", "barbeiem"]},
    "odiar": {"pres": ["odeio", "odeia", "odiamos", "odeiam"],
              "sp": ["odeie", "odeie", "odiemos", "odeiem"]},
    # Participles that aren't -ado/-ido.
    "abrir": {"part": "aberto"},
    "escrever": {"part": "escrito"},
    "cobrir": {"part": "coberto"},
    "descobrir": {"part": "descoberto"},
    "pagar": {"part": "pago"},
    "gastar": {"part": "gasto"},
    "ganhar": {"part": "ganho"},
}


def conjugate(inf: str) -> dict:
    """All the class tenses of one verb (without -se)."""
    forms = regular(inf, EU.get(inf))
    if inf in FUTURE_STEM:  # farei, direi, trarei, porei
        stem = FUTURE_STEM[inf]
        forms["fut"] = [stem + "ei", stem + "á", stem + "emos", stem + "ão"]
    own = IRREGULAR.get(inf, {})
    for key, value in own.items():
        forms[key] = list(value) if isinstance(value, list) else value
    _, end = split(inf)
    if "sp" not in own and ("pres" in own or inf in EU):
        forms["sp"] = subj_from_eu(forms["pres"][0], end)
    if "sf" not in own:
        forms["sf"] = fut_subj_from(forms["pret"][3])
    if inf == "ir":  # "vou ir" isn't needed: the present already says it
        forms["ir"] = list(forms["pres"])
    else:
        forms["ir"] = [f"{aux} {inf}" for aux in ("vou", "vai", "vamos", "vão")]
    return forms


def reflexive(forms: dict, inf: str) -> dict:
    """levantar-se: me levanto, se levanta, nos levantamos, se levantam."""
    out = dict(forms)
    for key in ("pres", "pret", "imp", "fut", "sp", "sf", "ip"):
        out[key] = [f"{p} {f}" for p, f in zip(REFLEXIVE, forms[key])]
    out["ir"] = [f"{aux} {p} {inf}" for aux, p in zip(("vou", "vai", "vamos", "vão"), REFLEXIVE)]
    out["ger"] = forms["ger"] + "-se"
    return out


def build_verbs(entries: list[dict]) -> list[dict]:
    built = []
    seen = set()
    for entry in entries:
        name = nfc(str(entry.get("v", "")).strip())
        if not name or name in seen:
            continue
        seen.add(name)
        is_refl = name.endswith("-se")
        inf = name[:-3] if is_refl else name
        if not (inf.endswith(("ar", "er", "ir")) or inf == "pôr"):
            print(f"Skipped {name}: it doesn't look like a verb.")
            continue
        forms = conjugate(inf)
        plain = regular(inf)
        mine = entry.get("forms") or {}
        for key, value in mine.items():  # your own fixes from data/aula.json
            if key in forms:
                forms[key] = value
        flags = {}
        for key, _ in TENSES:
            if key == "ir":
                continue
            ref = plain.get(key)
            flags[key] = [int(ref is not None and f != r) for f, r in zip(forms[key], ref or forms[key])]
        part_irr = int(forms["part"] != plain["part"])
        if is_refl:
            forms = reflexive(forms, inf)
        item = {
            "v": name,
            "es": entry.get("es", ""),
            "lessons": entry.get("lessons", []),
            "t": {key: forms[key] for key, _ in TENSES},
            "x": {k: v for k, v in flags.items() if any(v)},
            "ger": forms["ger"],
            "part": forms["part"],
        }
        if part_irr:
            item["xp"] = 1
        if entry.get("note"):
            item["note"] = entry["note"]
        if item["x"] or part_irr:
            item["irr"] = True
        built.append(item)
    return built


# --- Pronunciations -----------------------------------------------------------

def strings_to_say(source: dict, verbs: list[dict]) -> list[str]:
    """Every word and verb form that gets a pronunciation on the page."""
    out: list[str] = []

    def add(text):
        if isinstance(text, str) and text.strip():
            out.append(nfc(text.strip()))

    for section in source.get("sections", []):
        for item in section.get("items", []):
            for row in item.get("words", []) or []:
                if row:
                    add(row[0])
            for block in item.get("blocks", []) or []:
                for row in block.get("words", []) or []:
                    if row:
                        add(row[0])
                for row in block.get("sounds", []) or []:
                    for word in row[2] if len(row) > 2 else []:
                        add(word)
                for row in block.get("patterns", []) or []:
                    for pair in row[2] if len(row) > 2 else []:
                        add(pair[1] if isinstance(pair, list) else pair)
    for verb in verbs:
        add(verb["v"])
        for forms in verb["t"].values():
            for form in forms:
                add(form)
        add(verb["ger"])
        add(verb["part"])
    return list(dict.fromkeys(out))


def fixes_from(overrides: dict) -> dict:
    table = overrides.get("pt-es") or overrides.get("pt") or {}
    fixes = {}
    if isinstance(table, dict):
        for text, fix in table.items():
            if text.startswith("_"):
                continue
            if isinstance(fix, str):
                fixes[nfc(text)] = fix
            elif isinstance(fix, dict) and isinstance(fix.get("pron"), str) and fix["pron"].strip():
                fixes[nfc(text)] = fix["pron"].strip()
    return fixes


def say(text: str) -> tuple[str | None, str | None]:
    """Pronunciation of a word or phrase. "o médico / a médica" is done in parts."""
    parts = [p.strip() for p in text.split(" / ")] if " / " in text else [text]
    prons, ipas = [], []
    for part in parts:
        spelled, ipa = pronounce.pronounce(part, "pt")
        if not spelled:
            return None, None
        prons.append(spelled)
        ipas.append(ipa or "")
    return " / ".join(prons), " / ".join(ipas)


def build_pron(texts: list[str], fixes: dict) -> tuple[dict, list[str]]:
    notes = []
    try:
        old = json.loads(PRON_OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    old_map = old.get("pron", {}) if old.get("version") == pronounce.VERSION else {}
    can_speak = bool(pronounce.espeak_path())
    result: dict[str, list] = {}
    todo = []
    for text in texts:
        if text in fixes:
            result[text] = [nfc(fixes[text]), "", "you"]
        elif text in old_map and (len(old_map[text]) < 3 or old_map[text][2] != "you"):
            result[text] = old_map[text][:2]
        elif can_speak:
            todo.append(text)
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for text, (spelled, ipa) in zip(todo, pool.map(say, todo)):
                if spelled:
                    result[text] = [spelled, ipa or ""]
        notes.append(f"Wrote {len(todo)} class pronunciations.")
    if not can_speak:
        missing = sum(1 for t in texts if t not in result)
        notes.append("eSpeak NG isn't installed here, so no new class pronunciations were written"
                     + (f" ({missing} still missing)." if missing else "."))
    return {"version": pronounce.VERSION, "pron": dict(sorted(result.items()))}, notes


def write_if_changed(path: Path, data: dict) -> bool:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    try:
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"Couldn't read data/aula.json ({err}). The class notebook keeps its last version.")
        return 0
    try:
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        if not isinstance(overrides, dict):
            overrides = {}
    except (OSError, ValueError):
        overrides = {}

    verbs = build_verbs(source.get("verbs", []))
    verbs_out = {
        "version": 1,
        "persons": PERSONS,
        "tenses": [{"id": k, "name": n} for k, n in TENSES],
        "verbs": verbs,
    }
    changed = write_if_changed(VERBS_OUT, verbs_out)
    print(f"Conjugated {len(verbs)} verbs" + (" (saved data/aula-verbos.json)." if changed else ", no changes."))

    texts = strings_to_say(source, verbs)
    pron, notes = build_pron(texts, fixes_from(overrides))
    for note in notes:
        print(note)
    if write_if_changed(PRON_OUT, pron):
        print(f"Saved data/aula-pron.json ({len(pron['pron'])} of {len(texts)} words and forms).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:  # never break the word sync because of the class notebook
        print(f"The class notebook couldn't be built: {err}")
        sys.exit(0)
