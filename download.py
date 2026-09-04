#!/usr/bin/env python3
"""Download the YmerFlow demo data.

The data files are not committed to this repository - they are attached to a
GitHub release, so that cloning stays fast and only people who want the data
pay for it. This script fetches them into ``data/``.

Standard library only: no pip install needed to get the data.

    python3 download.py                       # the single line + system files (default)
    python3 download.py --dataset block       # the 26-line block, on request only
    python3 download.py --all                 # everything
    python3 download.py --list                # show what is available

Each file is verified against the SHA-256 recorded in ``manifest.json``, and
files already present and intact are skipped, so re-running is cheap and
interrupted downloads resume cleanly.
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request


REPO = "YmerFlow/ymerflow-demo-data"
MANIFEST = "manifest.json"
CHUNK = 1024 * 256


def asset_url(tag, filename):
    """Public download URL for one release asset.

    The tag is pinned rather than using /releases/latest/download/ - someone
    re-running a benchmark next year should get the same bytes, and `latest`
    silently changes underneath them.
    """
    return f"https://github.com/{REPO}/releases/download/{tag}/{filename}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fetch(url, dst, expect_size=None):
    """Download to a temporary path, then move into place on success."""
    tmp = dst + ".part"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:
            total = int(response.headers.get("Content-Length") or expect_size or 0)
            done = 0
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100.0 * done / total
                    print(f"\r    {human(done)} / {human(total)}  ({pct:.0f}%)",
                          end="", flush=True)
            print()
    except urllib.error.HTTPError as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        if exc.code == 404:
            raise SystemExit(
                f"\n{url}\n  404 - not found.\n"
                "  Either the release tag in manifest.json does not exist yet, or the\n"
                "  repository is still private. Check the releases page."
            )
        raise
    os.replace(tmp, dst)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", help="fetch only this dataset (e.g. line_300901, block, system)")
    parser.add_argument("--out", default=os.path.join(here, "data"), help="destination directory")
    parser.add_argument("--all", action="store_true", help="fetch every dataset, including the block")
    parser.add_argument("--list", action="store_true", help="list available files and exit")
    parser.add_argument("--force", action="store_true", help="re-download even if present and valid")
    args = parser.parse_args(argv)

    manifest_path = os.path.join(here, MANIFEST)
    if not os.path.exists(manifest_path):
        raise SystemExit(f"{MANIFEST} not found - this repository is incomplete.")
    with open(manifest_path) as fh:
        manifest = json.load(fh)

    files = manifest["files"]
    if not args.dataset and not args.all:
        # Default deliberately excludes the block: a free-tier user who downloads it
        # and tries to invert it as one job blocks the queue and gets nothing.
        files = [f for f in files if not f["dataset"].startswith("block")]
    if args.dataset:
        files = [f for f in files if f["dataset"].split("/")[0] == args.dataset]
        if not files:
            available = sorted({f["dataset"] for f in manifest["files"]})
            raise SystemExit(f"no dataset {args.dataset!r}; available: {', '.join(available)}")

    if args.list:
        print(f"{len(files)} file(s)")
        for f in files:
            print(f"  {human(f['size']):>10}  {f['dataset']}/{f['name']}")
        print(f"  {human(sum(f['size'] for f in files)):>10}  total")
        return 0

    total = sum(f["size"] for f in files)
    print(f"Fetching {len(files)} file(s), {human(total)}\n")

    fetched = skipped = 0
    for f in files:
        dst = os.path.join(args.out, f["dataset"], f["name"])
        if not args.force and os.path.exists(dst) and sha256(dst) == f["sha256"]:
            skipped += 1
            continue
        print(f"  {f['dataset']}/{f['name']}  ({human(f['size'])})")
        fetch(asset_url(f["release_tag"], f["name"]), dst, f["size"])
        got = sha256(dst)
        if got != f["sha256"]:
            os.remove(dst)
            raise SystemExit(f"    checksum mismatch - expected {f['sha256'][:12]}, "
                             f"got {got[:12]}. File removed; re-run to retry.")
        fetched += 1

    print(f"\n{fetched} downloaded, {skipped} already present and verified.")
    print(f"Data is in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
