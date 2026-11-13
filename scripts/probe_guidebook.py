#!/usr/bin/env python3
"""Temporary check: print the Guidebook of the first units, compactly.

Never prints the token. Delete this file and .github/workflows/probe.yml afterwards.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync  # noqa: E402

jwt = sync.clean_token(os.environ.get("DUOLINGO_JWT", ""))
uid = sync.user_id_from(jwt)


def text_of(node) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("styledString"), dict):
            return node["styledString"].get("text") or ""
        if isinstance(node.get("text"), str):
            return node["text"]
    return ""


data = sync.call("GET", f"/2017-06-30/users/{uid}?fields=currentCourse", jwt)
course = (data or {}).get("currentCourse") or {}
for si, sec in enumerate(course.get("pathSectioned") or []):
    print(f"section {si}: {sec.get('title')!r} | {sec.get('subtitle')!r} | cefr={sec.get('cefr')} | done {sec.get('completedUnits')}/{sec.get('totalUnits')}")
    if si:
        continue
    for ui, unit in enumerate(sec.get("units") or []):
        states = [lv.get("state") for lv in unit.get("levels") or []]
        print(f"  unit {unit.get('unitIndex')}: {unit.get('teachingObjective')!r} states={states}")
        if ui > 2:
            continue
        url = (unit.get("guidebook") or {}).get("url")
        req = urllib.request.Request(url, headers={"User-Agent": sync.USER_AGENT})
        with urllib.request.urlopen(req, timeout=40) as resp:
            book = json.loads(resp.read().decode("utf-8"))
        print("   top keys:", sorted(book.keys()))
        for el in book.get("elements") or []:
            kind = el.get("type")
            sec_i = (el.get("meta") or {}).get("sectionIndex")
            body = el.get("element")
            if kind == "verticalSpace":
                continue
            if kind == "dialogue":
                for ph in (body or {}).get("phrases") or []:
                    print(f"   [{sec_i}] dialogue: {text_of(ph.get('text'))!r} = {text_of(ph.get('subtext'))!r} "
                          f"tts={'yes' if ph.get('ttsURL') else 'no'} keys={sorted(ph.keys())}")
            elif kind == "text":
                print(f"   [{sec_i}] text: {text_of(body)[:300]!r}")
            else:
                print(f"   [{sec_i}] {kind}: {json.dumps(body, ensure_ascii=False)[:400]}")
