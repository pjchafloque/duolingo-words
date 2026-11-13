#!/usr/bin/env python3
"""Temporary check: does the open course have Guidebook key phrases, and in what shape?

Prints a summary to the Actions log. It never prints the token, and it hides
the user id. Delete this file and .github/workflows/probe.yml afterwards.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync  # noqa: E402

jwt = sync.clean_token(os.environ.get("DUOLINGO_JWT", ""))
uid = sync.user_id_from(jwt)


def hide(text: str) -> str:
    return text.replace(uid, "<uid>")


def show(label: str, obj, limit: int = 2500) -> None:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    print(f"{label}: {hide(text)[:limit]}")


def fetch(url: str, auth: bool):
    headers = {"User-Agent": sync.USER_AGENT, "Accept": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {jwt}"
        headers["Cookie"] = f"jwt_token={jwt}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Content-Type"), err.read().decode("utf-8", "replace")[:300]
    except Exception as err:  # noqa: BLE001
        return None, None, str(err)


urls: list[str] = []
for version in ("2017-06-30", "2023-05-23"):
    print(f"\n===== {version}")
    try:
        data = sync.call("GET", f"/{version}/users/{uid}?fields=currentCourse", jwt)
    except Exception as err:  # noqa: BLE001
        print("failed:", err)
        continue
    course = (data or {}).get("currentCourse") or {}
    print("course:", course.get("learningLanguage"), "from", course.get("fromLanguage"), "| id:", course.get("id"))
    print("course keys:", sorted(course.keys()))
    raw = hide(json.dumps(course, ensure_ascii=False))
    print("size:", len(raw), "| mentions of 'guide':", raw.lower().count("guide"), "| 'tip':", raw.lower().count("tip"),
          "| 'phrase':", raw.lower().count("phrase"))
    for m in re.finditer(r'"([^"]*guide[^"]*)"\s*:\s*("(?:[^"\\]|\\.)*"|\{[^{}]*\}|null|true|false|\d+)', raw, re.I):
        printed = globals().setdefault("printed", [0])
        if printed[0] < 40:
            printed[0] += 1
            print("  guide field:", m.group(1), "=", m.group(2)[:240])
        for u in re.findall(r"https?://[^\"\\\s]+", m.group(2)):
            if u not in urls:
                urls.append(u)
    sections = course.get("pathSectioned") or []
    print("sections:", len(sections))
    for si, sec in enumerate(sections):
        units = (sec or {}).get("units") or []
        print(f" section {si}: keys={sorted((sec or {}).keys())} units={len(units)}")
        for ui, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            states = [lv.get("state") for lv in unit.get("levels") or [] if isinstance(lv, dict)]
            reached = any(s and s != "locked" for s in states)
            if (si == 0 and ui < 3) or reached:
                small = {k: v for k, v in unit.items() if k != "levels"}
                print(f"  unit s{si}u{ui} reached={reached} states={states}")
                show("   unit fields", small, 1200)
                if si == 0 and ui == 0 and unit.get("levels"):
                    show("   first level", unit["levels"][0], 1500)
    if sections:
        break

print("\n===== guidebook urls found:", len(urls))
for u in urls[:6]:
    print(" ", hide(u))
for u in urls[:2]:
    for auth in (False, True):
        status, ctype, body = fetch(u, auth)
        print(f"\nGET {hide(u)} auth={auth} -> {status} {ctype} {len(body)} chars")
        show(" body", body, 6000)
        if status == 200:
            break
