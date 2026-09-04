#!/usr/bin/env python3
"""Write manifest.json describing the release assets that download.py fetches.

Run after building the dataset and before creating the GitHub release. The
manifest records a SHA-256 per file so download.py can verify what it fetched
and skip what is already correct.

    python3 tools/make_manifest.py --tag v0.1.0

Asset names are flattened - GitHub release assets live in a single namespace
with no directories - so the manifest carries the dataset separately and
download.py reassembles the tree locally.
"""

import argparse
import hashlib
import json
import os
import sys

# Each top-level dataset ships on its OWN release, so `download.py` fetches only
# the single line by default and the block only on request.
DATASETS = ("line_300901/as_delivered", "line_300901/agf_inversion",
            "block/as_delivered", "block/agf_inversion", "system")
RELEASE_FOR = {"line_300901": "line-v0.1.0", "block": "block-v0.1.0", "system": "line-v0.1.0"}
CHUNK = 1024 * 256


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=os.path.join(repo, "data"))
    parser.add_argument("--out", default=os.path.join(repo, "manifest.json"))
    args = parser.parse_args(argv)

    files, clashes = [], {}
    for dataset in DATASETS:
        d = os.path.join(args.data, dataset)
        if not os.path.isdir(d):
            print(f"  skipping {dataset}/ - not built")
            continue
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not os.path.isfile(path) or name.startswith("."):
                continue
            if name in clashes:
                raise SystemExit(
                    f"asset name collision: {name} appears in both {clashes[name]}/ "
                    f"and {dataset}/. Release assets share one namespace, so names "
                    f"must be unique across datasets.")
            clashes[name] = dataset
            top = dataset.split("/")[0]
            files.append({"name": name, "dataset": dataset, "release_tag": RELEASE_FOR[top],
                          "size": os.path.getsize(path), "sha256": sha256(path)})
            print(f"  {files[-1]['size']/1048576:8.2f} MB  {dataset}/{name}")

    manifest = {"files": files}
    with open(args.out, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    total = sum(f["size"] for f in files)
    print(f"\n{len(files)} file(s), {total/1048576:.1f} MB -> {os.path.basename(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
