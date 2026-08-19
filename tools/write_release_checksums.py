#!/usr/bin/env python
"""Write SHA-256 checksums for the ORZIP distribution tree."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

RELEASE_FILES = (
    "orzip.exe",
    "DOCS/README.md",
    "DOCS/README-ORZIP.md",
    "DOCS/USER_GUIDE.md",
    "DOCS/ORZIP_EXE_User_Guide.md",
    "DOCS/ORZIP_EXE_User_Guide.pdf",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("DIST"))
    parser.add_argument("-o", "--output", type=Path, default=Path("DIST/SHA256SUMS.txt"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    expected = {Path(name).as_posix() for name in RELEASE_FILES}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != output
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing release files: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected release files: {', '.join(unexpected)}")
        raise SystemExit("; ".join(details))

    lines = []
    for name in RELEASE_FILES:
        path = root / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {Path(name).as_posix()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print(f"Wrote {output} with {len(RELEASE_FILES)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
