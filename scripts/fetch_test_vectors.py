"""Fetch the pinned SingleStepTests 68000 corpora into tests/68000_test_vectors/.

The primary corpus is SingleStepTests/m68000 (MIT, generated from MAME's
microcoded 68000 core). It is fetched as the GitHub archive of one immutable
commit, its 127 ``v1/*.json.bin`` files are extracted, and every file is
walked to check its magic numbers and count cases. Nothing is fetched by
pytest; run this script once. See docs/validation.md for the tiers.

    python scripts/fetch_test_vectors.py                # full m68000 corpus
    python scripts/fetch_test_vectors.py --files NOP,ABCD.json.bin
                                                        # sparse: named files only
    python scripts/fetch_test_vectors.py --with-680x0   # also the older Harte
                                                        # corpus (no license file)

The archive URLs are derived from the pinned revisions so a corpus can never
be substituted from a moving branch. GitHub publishes no checksum for the
generated archives; the immutable commit hash is the recorded provenance.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import struct
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests" / "68000_test_vectors"

# Primary corpus: MIT, MAME microcoded-core derived. 127 files, 137,928,157 bytes.
M68000_REPOSITORY = "https://github.com/SingleStepTests/m68000"
M68000_REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"
M68000_SOURCE_DIRECTORY = "v1"

# Secondary corpus: Tom Harte's, no LICENSE file (issue #1 open since 2024-06).
# Fetched only on request, and only as a detector. 125 files, 202,594,760 bytes.
H680X0_REPOSITORY = "https://github.com/SingleStepTests/680x0"
H680X0_REVISION = "e0d5ece9670205cc84a0101081837deb446f86a3"
H680X0_SOURCE_DIRECTORY = "68000/v1"

# Magic numbers of the m68000 .json.bin container, from the repository's decode.py.
FILE_MAGIC = 0x1A3F5D71
TEST_MAGIC = 0xABC12367
NAME_MAGIC = 0x89ABCDEF
STATE_MAGIC = 0x01234567
TRANSACTIONS_MAGIC = 0x456789AB
REGISTER_COUNT = 19  # d0-d7, a0-a6, usp, ssp, sr, pc


def _download(url: str, target: Path) -> None:
    with urlopen(url, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output, 1024 * 1024)


def _extract(archive: Path, source_directory: str, destination: Path, suffix: str) -> int:
    """Extract ``*/<source_directory>/*<suffix>`` from a GitHub archive; return the count."""
    count = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
                continue
            relative = PurePosixPath(*parts[1:])
            if not relative.is_relative_to(source_directory):
                continue
            if not member.isfile() or not member.name.endswith(suffix):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError(f"cannot read {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            count += 1
    if count == 0:
        raise RuntimeError(f"archive holds no {suffix} files under {source_directory}")
    return count


def count_bin_cases(path: Path) -> int:
    """Walk one m68000 .json.bin file, checking every magic number; return its case count."""
    data = path.read_bytes()
    magic, tests = struct.unpack_from("<II", data, 0)
    if magic != FILE_MAGIC:
        raise RuntimeError(f"{path.name}: bad file magic {magic:#x}")
    offset = 8
    for _ in range(tests):
        _, magic = struct.unpack_from("<II", data, offset)
        if magic != TEST_MAGIC:
            raise RuntimeError(f"{path.name}: bad test magic at {offset}")
        offset += 8
        _, magic = struct.unpack_from("<II", data, offset)
        if magic != NAME_MAGIC:
            raise RuntimeError(f"{path.name}: bad name magic at {offset}")
        offset += 8
        (length,) = struct.unpack_from("<I", data, offset)
        offset += 4 + length
        for _ in range(2):  # initial, final
            _, magic = struct.unpack_from("<II", data, offset)
            if magic != STATE_MAGIC:
                raise RuntimeError(f"{path.name}: bad state magic at {offset}")
            offset += 8 + 4 * REGISTER_COUNT + 8  # registers, two prefetch words
            (rams,) = struct.unpack_from("<I", data, offset)
            offset += 4 + 6 * rams  # [u32 address, u16 word] pairs
        _, magic = struct.unpack_from("<II", data, offset)
        if magic != TRANSACTIONS_MAGIC:
            raise RuntimeError(f"{path.name}: bad transactions magic at {offset}")
        offset += 8
        _, transactions = struct.unpack_from("<II", data, offset)
        offset += 8
        for _ in range(transactions):
            (kind,) = struct.unpack_from("<B", data, offset)
            offset += 5  # kind byte, u32 cycles
            if kind != 0:
                offset += 20  # fc, address, data, uds, lds
    if offset != len(data):
        raise RuntimeError(f"{path.name}: {len(data) - offset} trailing bytes")
    return tests


def count_gz_cases(path: Path) -> int:
    with gzip.open(path) as handle:
        return len(json.load(handle))


def fetch_m68000(files: list[str] | None) -> None:
    target = DESTINATION / "m68000"
    if target.exists():
        raise SystemExit(f"{target} exists; remove it to refetch")
    target.mkdir(parents=True)
    if files:
        base = f"https://raw.githubusercontent.com/SingleStepTests/m68000/{M68000_REVISION}/v1/"
        (target / "v1").mkdir()
        for name in files:
            if not name.endswith(".json.bin"):
                name += ".json.bin"
            print(f"fetching {name}")
            _download(base + name, target / "v1" / name)
    else:
        with tempfile.TemporaryDirectory(dir=DESTINATION) as temporary:
            archive = Path(temporary) / "m68000.tar.gz"
            url = f"{M68000_REPOSITORY}/archive/{M68000_REVISION}.tar.gz"
            print(f"downloading {url}")
            _download(url, archive)
            _extract(archive, M68000_SOURCE_DIRECTORY, target, ".json.bin")
    (target / "REVISION").write_text(M68000_REVISION + "\n")
    _report("SingleStepTests/m68000", M68000_REVISION, target / "v1", ".json.bin", count_bin_cases)


def fetch_680x0() -> None:
    target = DESTINATION / "680x0"
    if target.exists():
        raise SystemExit(f"{target} exists; remove it to refetch")
    target.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=DESTINATION) as temporary:
        archive = Path(temporary) / "680x0.tar.gz"
        url = f"{H680X0_REPOSITORY}/archive/{H680X0_REVISION}.tar.gz"
        print(f"downloading {url}")
        _download(url, archive)
        _extract(archive, H680X0_SOURCE_DIRECTORY, target, ".json.gz")
    (target / "REVISION").write_text(H680X0_REVISION + "\n")
    _report(
        "SingleStepTests/680x0",
        H680X0_REVISION,
        target / "68000" / "v1",
        ".json.gz",
        count_gz_cases,
    )


def _report(name: str, revision: str, directory: Path, suffix: str, counter) -> None:
    files = sorted(directory.glob(f"*{suffix}"))
    total_cases = 0
    total_bytes = 0
    for path in files:
        cases = counter(path)
        total_cases += cases
        total_bytes += path.stat().st_size
        print(f"  {path.name:28s} {cases:7d} cases {path.stat().st_size:10d} bytes")
    print(f"{name} @ {revision}")
    print(f"  files: {len(files)}  cases: {total_cases}  bytes: {total_bytes}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--files", help="comma-separated m68000 file names for a sparse fetch")
    parser.add_argument(
        "--with-680x0", action="store_true", help="also fetch the Harte 680x0 corpus"
    )
    args = parser.parse_args()
    try:
        fetch_m68000([f.strip() for f in args.files.split(",")] if args.files else None)
        if args.with_680x0:
            fetch_680x0()
    except (OSError, RuntimeError, tarfile.TarError) as error:
        print(f"fetch failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
