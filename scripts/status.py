#!/usr/bin/env python3
"""Write status.json for the page: when the sync last ran and whether it worked.

Used by the publish job in .github/workflows/sync.yml. It reads the sync job's
results from environment variables the workflow sets.
"""

import json
import os
import sys
from datetime import datetime, timezone

out = sys.argv[1] if len(sys.argv) > 1 else "_site/status.json"
ok_flag = os.environ.get("SYNC_OK", "")
result = os.environ.get("SYNC_RESULT", "")
message = os.environ.get("SYNC_MESSAGE", "").strip()

if ok_flag:
    ok = ok_flag == "true"
else:  # the sync step never got to report, so go by the job's result
    ok = result in ("success", "skipped")
    if not ok and not message:
        message = "The sync stopped before it could say why. Open the run on GitHub to see the log."

status = {
    "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "ok": ok,
    "message": message,
    "repo": os.environ.get("REPO", ""),
    "run_url": os.environ.get("RUN_URL", ""),
}
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(status, fh, ensure_ascii=False, indent=1)
print(json.dumps(status, ensure_ascii=False))
