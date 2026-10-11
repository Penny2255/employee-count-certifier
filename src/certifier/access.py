"""Per-user access codes for the hosted service.

Each person gets an access code (shown once). The service stores only its SHA-256 hash, in the
CERTIFIER_ACCESS_CODES environment variable: comma- or newline-separated `name:hash` entries.
Revoke someone by deleting their entry (or listing their name in CERTIFIER_REVOKED) and
redeploying. Codes are sent as `Authorization: Bearer <code>` (web page, API, Claude request
headers) or entered once on the OAuth sign-in page (Claude custom connector).

    certifier-access new alice      # prints a new code for alice and the line to add
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sys

PREFIX = "ecc_"


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def new_code() -> str:
    return PREFIX + secrets.token_urlsafe(24)


class AccessCodes:
    """The configured access codes (hashes only). Reads the environment on every check, so a
    redeploy with an edited variable takes effect immediately."""

    def __init__(self, env: dict[str, str] | None = None):
        self._env = env

    def _get(self, key: str) -> str:
        return (self._env if self._env is not None else os.environ).get(key, "")

    def entries(self) -> dict[str, str]:
        """name -> hash, excluding revoked names."""
        revoked = {n.strip() for n in re.split(r"[,\n]", self._get("CERTIFIER_REVOKED")) if n.strip()}
        out = {}
        for item in re.split(r"[,\n]", self._get("CERTIFIER_ACCESS_CODES")):
            if ":" not in item:
                continue
            name, digest = (part.strip() for part in item.split(":", 1))
            if name and re.fullmatch(r"[0-9a-f]{64}", digest) and name not in revoked:
                out[name] = digest
        return out

    def verify(self, code: str | None) -> str | None:
        """The name the code belongs to, or None. Constant-time comparison."""
        if not code or not code.startswith(PREFIX):
            return None
        digest = hash_code(code)
        match = None
        for name, stored in self.entries().items():
            if hmac.compare_digest(digest, stored):
                match = name
        return match

    def is_active(self, name: str) -> bool:
        return name in self.entries()


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "new" and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", args[1]):
        code = new_code()
        print(f"Access code for {args[1]} (give this to them; it is shown only once):\n\n  {code}\n")
        print("Add this entry to CERTIFIER_ACCESS_CODES on the server (comma-separated with any others):\n")
        print(f"  {args[1]}:{hash_code(code)}")
    elif len(args) == 2 and args[0] == "hash":
        print(hash_code(args[1]))
    else:
        sys.exit("usage: certifier-access new NAME   |   certifier-access hash CODE")


if __name__ == "__main__":
    main()
