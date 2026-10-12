"""file.py: the reduced file(1) that deb-list.py falls back to."""

from __future__ import annotations

import gzip
import importlib.util
import os
import struct
import tempfile
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "_shared" / "file.py"


def describe(*paths: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location("file", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [module.describe(str(p)) for p in paths]


def elf64(e_type: int, machine: int, interp: bytes | None) -> bytes:
    """A minimal little-endian ELF64 image: header, one program header
    (PT_INTERP when interp is given), then the interpreter string."""
    phoff, phentsize = 64, 56
    phnum = 1 if interp else 0
    interp_off = phoff + phentsize * phnum
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    header = ident + struct.pack(
        "<HHIQQQIHHHHHH",
        e_type,
        machine,
        1,
        0,
        phoff,
        0,
        0,
        64,
        phentsize,
        phnum,
        64,
        0,
        0,
    )
    body = header
    if interp:
        body += struct.pack(
            "<IIQQQQQQ", 3, 4, interp_off, 0, 0, len(interp) + 1, len(interp) + 1, 1
        )
        body += interp + b"\0"
    return body


def test_kinds() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "sh").write_bytes(b"#!/bin/sh\necho hi\n")
        (d / "py").write_bytes(b"#!/usr/bin/env python3\nprint(1)\n")
        (d / "ascii").write_bytes(b"plain\n")
        (d / "utf8").write_bytes(b"caf\xc3\xa9\n")
        (d / "empty").write_bytes(b"")
        (d / "gz").write_bytes(gzip.compress(b"x"))
        (d / "bin").write_bytes(b"\0\1\2")
        os.symlink("ascii", d / "link")
        (d / "dir").mkdir()
        (d / "pie").write_bytes(elf64(3, 0xB7, b"/lib/ld-linux-aarch64.so.1"))
        (d / "so").write_bytes(elf64(3, 0x3E, None))
        (d / "exe").write_bytes(elf64(2, 0x3E, b"/lib64/ld-linux-x86-64.so.2"))
        out = describe(
            *(
                d / n
                for n in (
                    "sh",
                    "py",
                    "ascii",
                    "utf8",
                    "empty",
                    "gz",
                    "bin",
                    "link",
                    "dir",
                    "pie",
                    "so",
                    "exe",
                    "missing",
                )
            )
        )
    assert out == [
        "POSIX shell script, ASCII text executable",
        "Python script, ASCII text executable",
        "ASCII text",
        "Unicode text, UTF-8 text",
        "empty",
        "gzip compressed data",
        "data",
        "symbolic link to ascii",
        "directory",
        "ELF 64-bit LSB pie executable, ARM aarch64, dynamically linked, interpreter /lib/ld-linux-aarch64.so.1",
        "ELF 64-bit LSB shared object, x86-64, statically linked",
        "ELF 64-bit LSB executable, x86-64, dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2",
        f"cannot open `{d / 'missing'}' (No such file or directory)",
    ], out


def test_is_a_module() -> None:
    # deb-list imports it; nothing runs it as a command
    assert 'if __name__ == "__main__":' not in MODULE.read_text()
