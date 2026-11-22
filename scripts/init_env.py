"""Create .env from .env.example with fresh random secrets (standard library only).

    python scripts/init_env.py            # refuses to overwrite an existing .env
    python scripts/init_env.py --force    # replace it (the old file is kept as .env.bak)

Fills JWT_SECRET, POSTGRES_PASSWORD (and DATABASE_URL to match) and DEMO_PASSWORD. The values are
written only to .env, which git ignores; the script prints where, never the values.
"""

from __future__ import annotations

import re
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    target, example = ROOT / ".env", ROOT / ".env.example"
    if target.exists() and "--force" not in sys.argv:
        print(f"{target} exists; nothing changed (use --force to replace it).")
        return 1
    if target.exists():
        shutil.copy2(target, ROOT / ".env.bak")
    text = example.read_text(encoding="utf-8")
    db_password = secrets.token_urlsafe(18)
    values = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": db_password,
        "DEMO_PASSWORD": "demo-" + secrets.token_urlsafe(12),
    }
    for key, value in values.items():
        text, n = re.subn(rf"^{key}=.*$", f"{key}={value}", text, flags=re.MULTILINE)
        if not n:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
    text = text.replace("change-me-local-only", db_password)  # DATABASE_URL uses the same password
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {target} with new JWT_SECRET, POSTGRES_PASSWORD and DEMO_PASSWORD.")
    print("Demo accounts: viewer, operator, approver, admin; the password is DEMO_PASSWORD in .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
