"""Fetch the referee emulators at pinned commits and build their drivers.

    python validation/referees/build_referees.py            # fetch if needed, build both
    python validation/referees/build_referees.py winuae     # one referee
    python validation/referees/build_referees.py --clean    # remove build/ first

Sources land in validation/referees/src/<name>-<pin>/ and builds in
validation/referees/build/<name>/, both ignored by git: no third-party source
is committed.  What each referee is, and what it can judge, is in
docs/referees.md.

WinUAE: the CPU tester's 68000 core.  cpudefs.cpp is the tree's own
(build68k's output from table68k, committed upstream).  gencpu, compiled with
CPU_TESTER set (the tester's documented build step), generates
cpuemu_90_test.cpp and its table; winuae_referee.cpp #includes the tester's
cputest.cpp and drives that core.  Two Unix adjustments, both made to copies
in build/: od-unix's machdep/m68k.h defines cctrue() inline where the tester
defines its own (the Windows header only declares it), and gencpu.cpp's
CPU_TESTER switch is a #define set to 0.

Musashi: m68kmake generates m68kops.c from m68k_in.c; m68kconf.h is copied
with the 68010-68040 cores off and address errors on.
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

WINUAE_REPOSITORY = "https://github.com/tonioni/WinUAE"
WINUAE_REVISION = "1977af501f6c3389c2eefe119ecb10c82d6582f3"  # 2026-09-17
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


def build_winuae() -> Path:
    source = fetch("winuae", WINUAE_REPOSITORY, WINUAE_REVISION)
    out = BUILD / "winuae"
    out.mkdir(parents=True, exist_ok=True)
    gen = out / "gen"
    gen.mkdir(exist_ok=True)
    overlay = out / "overlay" / "machdep"
    overlay.mkdir(parents=True, exist_ok=True)

    # od-unix defines cctrue() inline; the tester defines it itself.
    header = (source / "od-unix" / "machdep" / "m68k.h").read_text()
    header, count = re.subn(
        r"static inline int cctrue\(int cc\)\n\{.*?\n\}\n",
        "extern int cctrue(int cc);\n",
        header,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("od-unix/machdep/m68k.h: cctrue() not found where expected")
    (overlay / "m68k.h").write_text(header)
    shutil.copy(HERE / "winuae_shim.h", out / "winuae_shim.h")

    include = [
        f"-I{out / 'overlay'}",
        f"-I{gen}",
        f"-I{source / 'od-unix'}",
        f"-I{source}",
        f"-I{source / 'include'}",
        f"-I{source / 'cputest'}",
    ]
    flags = [
        "-w",
        "-fpermissive",
        "-std=gnu++17",
        "-include",
        str(out / "winuae_shim.h"),
        "-DUAE_TARGET_UNIX=1",
        "-DUAE_NOGUI=1",
    ]

    print("winuae: gencpu (CPU_TESTER)", flush=True)
    # gencpu with the tester switch on
    gencpu = (source / "gencpu.cpp").read_text()
    if "#define CPU_TESTER 0\n" not in gencpu:
        raise SystemExit("gencpu.cpp: CPU_TESTER switch not found")
    (out / "gencpu_tester.cpp").write_text(
        gencpu.replace("#define CPU_TESTER 0\n", "#define CPU_TESTER 1\n")
    )
    run(
        [
            "g++",
            *flags,
            *include,
            "-O1",
            "-o",
            str(out / "gencpu_tester"),
            str(out / "gencpu_tester.cpp"),
            str(source / "readcpu.cpp"),
            str(source / "cpudefs.cpp"),
            str(HERE / "winuae_shim.cpp"),
        ],
        out,
    )
    subprocess.run([str(out / "gencpu_tester")], cwd=gen, check=True, stdout=subprocess.DEVNULL)

    defines = [f"-DCPUEMU_{n}" for n in range(90, 96)] + ["-DCPU_TESTER"]
    units = [
        gen / "cpustbl_test.cpp",
        *[gen / f"cpuemu_{n}_test.cpp" for n in range(90, 96)],
        source / "cpudefs.cpp",
        source / "cputest_support.cpp",
        source / "newcpu_common.cpp",
        source / "readcpu.cpp",
        source / "disasm.cpp",
        source / "fpp.cpp",
        source / "fpp_softfloat.cpp",
        source / "softfloat" / "softfloat.cpp",
        source / "softfloat" / "softfloat_decimal.cpp",
        source / "softfloat" / "softfloat_fpsp.cpp",
        source / "ini.cpp",
        HERE / "winuae_shim.cpp",
        HERE / "winuae_referee.cpp",
    ]
    objects = []
    jobs = []
    for unit in units:
        obj = out / (unit.stem + ".o")
        objects.append(obj)
        jobs.append(
            (["g++", *flags, *defines, *include, "-O2", "-c", str(unit), "-o", str(obj)], out)
        )
    print(f"winuae: compiling {len(units)} units ({JOBS} jobs)", flush=True)
    compile_all(jobs)
    binary = out / "winuae_referee"
    run(["g++", "-o", str(binary), *map(str, objects), "-lz"], out)
    (out / "PIN").write_text(WINUAE_REVISION + "\n")
    print(f"built {binary}", flush=True)
    return binary


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Not choices=["winuae", "musashi"]: argparse's own validation of a
    # nargs='*' positional against its default empty list is broken on
    # Python 3.11 (checked: reproduces under PyPy 3.11.15's argparse, not
    # under CPython 3.14) -- it raises "invalid choice: []" for zero
    # arguments, rather than validating per element. Validated by hand below
    # instead, which works the same on every version.
    parser.add_argument("referees", nargs="*", default=[])
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    for name in args.referees:
        if name not in ("winuae", "musashi"):
            parser.error(
                f"argument referees: invalid choice: {name!r} (choose from 'winuae', 'musashi')"
            )
    if args.clean and BUILD.exists():
        shutil.rmtree(BUILD)
    for name in args.referees or ["winuae", "musashi"]:
        {"winuae": build_winuae, "musashi": build_musashi}[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
