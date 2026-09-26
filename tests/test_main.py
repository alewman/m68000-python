"""``python -m m68000_python``: loading images, the start address, the batch commands."""

from __future__ import annotations

import io
import zipfile
from contextlib import redirect_stdout

import pytest

from m68000_python.__main__ import main

PROGRAM = bytes.fromhex("7005 5380 66FC 33C0 0000 3000 4E72 2700".replace(" ", ""))


def run(*arguments: str) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        main([*arguments, "--batch"])
    return output.getvalue()


def test_load_and_pc_then_batch_commands(tmp_path) -> None:
    image = tmp_path / "program.bin"
    image.write_bytes(PROGRAM)

    text = run("--load", f"{image}@0x1000", "--pc", "$1000", "-c", "step 3", "-c", "m 0x1000 2")

    assert "m68000> registers\n" in text and "PC=001000" in text
    assert "001000  7005                     moveq #$5, D0" in text  # the opening disassembly
    assert "001004  bne $1002" in text
    assert "001000  70 05 53 80" in text


def test_zip_interleaves_an_even_odd_pair_and_loads_a_single_member(tmp_path) -> None:
    archive = tmp_path / "roms.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("even.bin", PROGRAM[0::2])
        bundle.writestr("odd.bin", PROGRAM[1::2])
        bundle.writestr("whole.bin", PROGRAM)

    paired = run("--zip", f"{archive}:even.bin,odd.bin@0x1000", "--pc", "0x1000", "-c", "step")
    single = run("--zip", f"{archive}:whole.bin@0x1000", "--pc", "0x1000", "-c", "step")

    assert "001000  moveq #$5, D0" in paired
    assert "001000  moveq #$5, D0" in single


def test_reset_starts_from_the_vectors_and_the_default_start_is_zero(tmp_path) -> None:
    vectors = tmp_path / "vectors.bin"
    vectors.write_bytes((0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big"))
    image = tmp_path / "program.bin"
    image.write_bytes(PROGRAM)

    text = run("--load", f"{vectors}@0", "--load", f"{image}@0x1000", "--reset", "-c", "regs")
    assert "PC=001000" in text and "SSP=00008000" in text

    text = run("--load", f"{image}@0")
    assert "PC=000000" in text and "000000  7005                     moveq #$5, D0" in text


def test_command_errors_are_reported_and_quit_ends_the_batch(tmp_path) -> None:
    image = tmp_path / "program.bin"
    image.write_bytes(PROGRAM)

    text = run("--load", f"{image}@0", "-c", "frobnicate", "-c", "quit", "-c", "step")

    assert "error: unknown command 'frobnicate' (try help)" in text
    assert "m68000> quit" in text and "m68000> step" not in text


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("{image}", "FILE@ADDRESS"),
        ("{image}@0xFFFFF0", "do not fit"),
        ("{image}@0x1000000", "out of range"),
    ],
)
def test_image_specifications_are_checked(tmp_path, spec: str, message: str) -> None:
    image = tmp_path / "program.bin"
    image.write_bytes(bytes(0x100))
    with pytest.raises(SystemExit, match=message):
        run("--load", spec.format(image=image))


def test_zip_specification_needs_an_archive_and_members(tmp_path) -> None:
    with pytest.raises(SystemExit, match="ZIPFILE:MEMBER"):
        run("--zip", "member@0")
