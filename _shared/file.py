#!/usr/bin/env python3
"""A reduced file(1): describe what each path is, from its bytes.

Usage: file.py [-b] [-h] [--] PATH...

Stand-in for file(1) where it is not installed. Prints one line per path in
file(1)'s own vocabulary for the cases slice authoring cares about -- ELF
executables and shared objects (class, endianness, machine, interpreter), scripts
by shebang, symbolic links with their target, compressed data, text -- and
"data" for everything else. Symbolic links are described, never followed.
-b drops the "path: " prefix; -h is accepted for command-line compatibility.
"""

from __future__ import annotations

import os
import struct
import sys

MACHINES = {
    0x03: "Intel 80386",
    0x28: "ARM",
    0x3E: "x86-64",
    0xB7: "ARM aarch64",
    0x15: "64-bit PowerPC or cisco 7500",
    0x16: "IBM S/390",
    0xF3: "UCB RISC-V",
}

MAGIC = (
    (b"\x1f\x8b", "gzip compressed data"),
    (b"\xfd7zXZ\x00", "XZ compressed data"),
    (b"BZh", "bzip2 compressed data"),
    (b"\x28\xb5\x2f\xfd", "Zstandard compressed data"),
    (b"PK\x03\x04", "Zip archive data"),
    (b"!<arch>\n", "current ar archive"),
    (b"%PDF", "PDF document"),
    (b"\x89PNG", "PNG image data"),
    (b"\xff\xd8\xff", "JPEG image data"),
    (b"\x7fELF", None),  # handled by elf()
)

SHEBANG_KINDS = (
    (("sh", "dash", "bash", "ash"), "POSIX shell script"),
    (("python", "python3"), "Python script"),
    (("perl",), "Perl script"),
    (("ruby",), "Ruby script"),
    (("node", "nodejs"), "Node.js script"),
    (("lua",), "Lua script"),
    (("awk", "gawk", "mawk"), "awk script"),
)


def elf(head: bytes, path: str) -> str:
    """ELF 64-bit LSB pie executable, ARM aarch64, dynamically linked, interpreter ..."""
    if len(head) < 20:
        return "ELF"
    bits = {1: "32-bit", 2: "64-bit"}.get(head[4], "")
    little = head[5] == 1
    endian = "LSB" if little else "MSB"
    order = "<" if little else ">"
    e_type, e_machine = struct.unpack_from(order + "HH", head, 16)
    machine = MACHINES.get(e_machine, f"machine {e_machine:#x}")
    interp = elf_interp(path, head, bits == "64-bit", order)
    if e_type == 2:
        kind = "executable"
    elif e_type == 3:
        kind = "pie executable" if interp else "shared object"
    elif e_type == 1:
        kind = "relocatable"
    elif e_type == 4:
        kind = "core file"
    else:
        kind = f"type {e_type}"
    parts = [f"ELF {bits} {endian} {kind}", machine]
    if e_type in (2, 3):
        parts.append("dynamically linked" if interp else "statically linked")
    if interp:
        parts.append(f"interpreter {interp}")
    return ", ".join(parts)


def elf_interp(path: str, head: bytes, is64: bool, order: str) -> str | None:
    """The PT_INTERP path, if any: what makes a DYN object a pie executable
    rather than a shared library."""
    try:
        if is64:
            e_phoff, = struct.unpack_from(order + "Q", head, 32)
            e_phentsize, e_phnum = struct.unpack_from(order + "HH", head, 54)
        else:
            e_phoff, = struct.unpack_from(order + "I", head, 28)
            e_phentsize, e_phnum = struct.unpack_from(order + "HH", head, 42)
        with open(path, "rb") as f:
            f.seek(e_phoff)
            table = f.read(e_phentsize * e_phnum)
            for i in range(e_phnum):
                off = i * e_phentsize
                p_type, = struct.unpack_from(order + "I", table, off)
                if p_type != 3:  # PT_INTERP
                    continue
                if is64:
                    p_offset, = struct.unpack_from(order + "Q", table, off + 8)
                    p_filesz, = struct.unpack_from(order + "Q", table, off + 32)
                else:
                    p_offset, = struct.unpack_from(order + "I", table, off + 4)
                    p_filesz, = struct.unpack_from(order + "I", table, off + 16)
                f.seek(p_offset)
                return f.read(p_filesz).rstrip(b"\0").decode("ascii", "replace")
    except (OSError, struct.error):
        return None
    return None


def text_kind(head: bytes) -> str:
    if b"\0" in head:
        return "data"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "data"
    if all(b in b"\t\n\r\x0c\x0b" or 32 <= b < 127 for b in head):
        return "ASCII text"
    return "Unicode text, UTF-8 text"


def shebang(head: bytes) -> str | None:
    if not head.startswith(b"#!"):
        return None
    line = head.split(b"\n", 1)[0][2:].decode("utf-8", "replace").strip()
    words = line.split()
    if not words:
        return "script"
    interp = os.path.basename(words[0])
    if interp == "env" and len(words) > 1:
        interp = os.path.basename(next((w for w in words[1:] if not w.startswith("-")), words[1]))
    base = interp.rstrip("0123456789.") or interp
    for names, kind in SHEBANG_KINDS:
        if interp in names or base in names:
            return f"{kind}, {text_kind(head)} executable"
    return f"a {interp} script, {text_kind(head)} executable"


def describe(path: str) -> str:
    try:
        st = os.lstat(path)
    except OSError as e:
        return f"cannot open `{path}' ({e.strerror})"
    if os.path.islink(path):
        return f"symbolic link to {os.readlink(path)}"
    if os.path.isdir(path):
        return "directory"
    if st.st_size == 0:
        return "empty"
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError as e:
        return f"cannot open `{path}' ({e.strerror})"
    if head.startswith(b"\x7fELF"):
        return elf(head, path)
    for magic, name in MAGIC:
        if name and head.startswith(magic):
            return name
    script = shebang(head)
    if script:
        return script
    return text_kind(head)


def main(argv: list[str]) -> int:
    brief = False
    paths: list[str] = []
    it = iter(argv)
    for a in it:
        if paths or a == "--":
            paths.extend([a] if a != "--" else [])
            paths.extend(it)
            break
        if a in ("-b", "--brief"):
            brief = True
        elif a in ("-h", "--no-dereference"):
            pass
        elif a.startswith("-") and len(a) > 1:
            for ch in a[1:]:
                if ch == "b":
                    brief = True
                elif ch != "h":
                    print(f"file.py: unknown option -{ch}", file=sys.stderr)
                    return 2
        else:
            paths.append(a)
    if not paths:
        print("usage: file.py [-b] [-h] [--] PATH...", file=sys.stderr)
        return 2
    for p in paths:
        line = describe(p)
        print(line if brief else f"{p}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
