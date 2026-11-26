#!/usr/bin/env python3
"""Sanity checks for HOLOMAP after splitting the data out of index.html.

Checks:
  1. every data/*.json file listed in the page loader exists, is valid JSON
     and matches the version hash written in index.html (cache busting);
  2. no DATA key is missing or duplicated across the files;
  3. every file referenced by the image index (PK) exists on disk;
  4. optionally (--against REF): the split data is identical to the data
     embedded in the monolithic index.html of a git revision, e.g. HEAD.

Usage:
    python3 scripts/check_holomap.py [--against HEAD]
Exit code is 0 when everything passes, 1 otherwise.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOLOMAP = ROOT / "holomap"

errors = []


def fail(msg):
    errors.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg):
    print(f"  ok    {msg}")


def load_split():
    html = (HOLOMAP / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const F=(\[\[.*?\]\]);", html)
    if not m:
        fail("loader not found in index.html (page not split?)")
        return None, None
    files = json.loads(m.group(1))
    data, pk = {}, None
    for name, version in files:
        path = HOLOMAP / "data" / f"{name}.json"
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
            continue
        raw = path.read_bytes()
        if hashlib.sha1(raw).hexdigest()[:10] != version:
            fail(f"{name}.json changed but its version in index.html was not updated")
        obj = json.loads(raw)
        if name == "images":
            pk = obj
            continue
        dup = set(obj) & set(data)
        if dup:
            fail(f"keys defined twice ({name}.json): {sorted(dup)}")
        data.update(obj)
    ok(f"{len(files)} data files, {len(data)} DATA keys, {len(pk or {})} image entries")
    return data, pk


def load_monolithic(ref):
    html = subprocess.run(
        ["git", "show", f"{ref}:holomap/index.html"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    dec = json.JSONDecoder()
    data, _ = dec.raw_decode(html, html.index("const DATA=") + len("const DATA="))
    pk, _ = dec.raw_decode(html, html.index("const PK=") + len("const PK="))
    return data, pk


def check_images(pk):
    missing = []
    for key, entry in pk.items():
        target = entry if isinstance(entry, str) else entry[0]
        if not (HOLOMAP / target).exists():
            missing.append(target)
    missing = sorted(set(missing))
    if missing:
        fail(f"{len(missing)} referenced image files are missing, e.g. {missing[:5]}")
    else:
        ok("all files referenced by the image index exist")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", metavar="REF", help="git revision with the monolithic index.html")
    args = ap.parse_args()

    print("HOLOMAP checks")
    data, pk = load_split()
    if data is None:
        sys.exit(1)
    if pk is not None:
        check_images(pk)

    if args.against:
        ref_data, ref_pk = load_monolithic(args.against)
        if data == ref_data and pk == ref_pk:
            ok(f"split data identical to the inline data at {args.against}")
        else:
            diff = sorted(k for k in set(data) | set(ref_data) if data.get(k) != ref_data.get(k))
            fail(f"split data differs from {args.against}: keys {diff[:10]}"
                 + ("" if pk == ref_pk else " (and image index)"))

    print("PASSED" if not errors else f"FAILED ({len(errors)} problems)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
