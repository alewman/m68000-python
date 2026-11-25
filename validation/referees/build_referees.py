# SPDX-License-Identifier: MIT
"""Fetch the Musashi referee at its pinned commit and build its driver.

    python validation/referees/build_referees.py            # fetch if needed, build
    python validation/referees/build_referees.py musashi    # the same, by name
    python validation/referees/build_referees.py --clean    # remove build/ first

Sources land in validation/referees/src/<name>-<pin>/ and builds in
validation/referees/build/<name>/, both ignored by git: no third-party source
is committed.  What each referee is, and what it can judge, is in
docs/referees.md.

Musashi: m68kmake generates m68kops.c from m68k_in.c; m68kconf.h is copied
with the 68010-68040 cores off and address errors on.

WinUAE's CPU-tester referee is not built here, and no WinUAE source is
fetched here.  Its driver is WinUAE-derived and GPL-2.0-only as built, so it
lives outside this MIT repository and its packages: since 2026-11-24 it is the
tool ``tools/winuae`` of emu-tools-gpl2 (winuae-referee 0.2.0, WinUAE 6e0d5ae;
from 2026-11-19 it was the stand-alone m68000-winuae-referee, now archived).
referee.py runs the built binary at
``$EMU_TOOLS_GPL2/tools/winuae/build/winuae_referee`` (docs/referees.md).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "src"
BUILD = HERE / "build"

MUSASHI_REPOSITORY = "https://github.com/kstenerud/Musashi"
MUSASHI_REVISION = "313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd"  # 2026-03-08

JOBS = min(8, os.cpu_count() or 1)
NICE = ["nice", "-n", "10"]


def fetch(name: str, repository: str, revision: str) -> Path:
    """Download and extract ``repository`` at ``revision``; return the tree."""
    target = SOURCES / f"{name}-{revision[:12]}"
    if (target / ".complete").exists():
        return target
    if target.exists():
        shutil.rmtree(target)
    SOURCES.mkdir(parents=True, exist_ok=True)
    url = f"{repository}/archive/{revision}.tar.gz"
    print(f"downloading {url}", flush=True)
    with tempfile.TemporaryDirectory(dir=SOURCES) as temporary:
        archive = Path(temporary) / "source.tar.gz"
        with urlopen(url, timeout=300) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output, 1 << 20)
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(temporary, filter="data")
        (root,) = [p for p in Path(temporary).iterdir() if p.is_dir()]
        root.rename(target)
    (target / ".complete").write_text(revision + "\n")
    return target


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(NICE + command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"failed in {cwd}: {' '.join(command[:4])} ...")


def compile_all(jobs: list[tuple[list[str], Path]]) -> None:
    with ThreadPoolExecutor(JOBS) as pool:
        list(pool.map(lambda job: run(*job), jobs))


def build_musashi() -> Path:
    source = fetch("musashi", MUSASHI_REPOSITORY, MUSASHI_REVISION)
    out = BUILD / "musashi"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(source, out)
    conf = (out / "m68kconf.h").read_text()
    settings = {
        "M68K_EMULATE_010": "M68K_OPT_OFF",
        "M68K_EMULATE_EC020": "M68K_OPT_OFF",
        "M68K_EMULATE_020": "M68K_OPT_OFF",
        "M68K_EMULATE_030": "M68K_OPT_OFF",
        "M68K_EMULATE_040": "M68K_OPT_OFF",
        "M68K_EMULATE_ADDRESS_ERROR": "M68K_OPT_ON",
        "M68K_EMULATE_TRACE": "M68K_OPT_OFF",
        "M68K_EMULATE_PREFETCH": "M68K_OPT_OFF",
    }
    for name, value in settings.items():
        conf, count = re.subn(rf"(#define {name}\s+)M68K_OPT_\w+", rf"\g<1>{value}", conf)
        if count != 1:
            raise SystemExit(f"m68kconf.h: {name} not found")
    (out / "m68kconf.h").write_text(conf)
    print("musashi: m68kmake, compile", flush=True)
    run(["gcc", "-O1", "-o", "m68kmake", "m68kmake.c"], out)
    run(["./m68kmake", ".", "m68k_in.c"], out)
    shutil.copy(HERE / "musashi_referee.c", out / "musashi_referee.c")
    units = ["m68kcpu.c", "m68kops.c", "m68kdasm.c", "softfloat/softfloat.c", "musashi_referee.c"]
    jobs = [
        (["gcc", "-O2", "-w", "-I.", "-c", unit, "-o", Path(unit).stem + ".o"], out)
        for unit in units
    ]
    compile_all(jobs)
    binary = out / "musashi_referee"
    run(["gcc", "-o", str(binary), *[Path(unit).stem + ".o" for unit in units], "-lm"], out)
    (out / "PIN").write_text(MUSASHI_REVISION + "\n")
    print(f"built {binary}", flush=True)
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    # Not choices=[...]: argparse's own validation of a nargs='*' positional
    # against its default empty list is broken on Python 3.11 (it raises
    # "invalid choice: []" for zero arguments), so validated by hand below.
    parser.add_argument("referees", nargs="*", default=[])
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    for name in args.referees:
        if name == "winuae":
            parser.error(
                "the WinUAE referee is the GPL-2.0-only tool tools/winuae of emu-tools-gpl2:"
                ' build it there (python3 -I "$EMU_TOOLS_GPL2/tools/winuae/build_winuae.py";'
                " docs/referees.md)"
            )
        if name != "musashi":
            parser.error(f"argument referees: invalid choice: {name!r} (choose from 'musashi')")
    if args.clean and BUILD.exists():
        shutil.rmtree(BUILD)
    build_musashi()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
