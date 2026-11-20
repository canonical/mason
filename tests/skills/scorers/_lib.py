"""shared helpers for mason's pats scorers. not a scorer itself (no exec bit, no
shebang) -- imported by each scorer_<id>.py via `from _lib import *`.

a scorer receives the graded pair's output dir (env PATS_SCORED_DIR) and scores
whatever's there. the dir holds, per *target* (a sliced package):

    <target>.yaml           the slice the agent produced
    <target>.expected.yaml  ground truth (knockout snapshot or denovo silver)

plus per *case* (env PATS_SCORED_TASK_NAME):

    <case>.task.yaml        the spread test task.yaml the agent wrote (if any)
    <case>.spread.txt       concatenated spread-test bundle text (if any)
    <case>.branch           the chisel-releases branch (recorded at clone time)
    <case>.format           the branch's manifest format (version-gated checks)

a rock task's pair dir holds instead (bin/stage --rock, bin/collect --rock):

    <case>.case.yaml          what the task expects (tasks/rock-*/<case>/case.yaml)
    rockcraft.yaml            the rock the agent left
    rockcraft.expected.yaml   rock-debug: the fixed file
    rockcraft-test.yaml       the test suite config, if any (spread.yaml if not renamed)
    tests.txt                 every spread task.yaml, each under a `# <path>` header
    tests.expected.txt        rock-debug: the tests the project came with
    rockcraft-test.expected.yaml  rock-debug: the suite config the project came with
    rocks.txt                 the packed *.rock files left in the project
    git-log.txt, git-status.txt

the *targets* are the stems of the `*.expected.yaml` files. single-target cases
have exactly one; multi-target (denovo) cases have several. per-target scorers
average across targets, so single-target is just the N=1 case.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "NA",
    "ORIENTATION_MARKERS",
    "OUT",
    "REJECTED_SLICE_NAMES",
    "SLICE",
    "TASK",
    "avg",
    "calls",
    "case",
    "content_paths",
    "declared_binaries",
    "emit",
    "expected",
    "final_text",
    "fmt",
    "fmt_compat",
    "has_slices",
    "iter_bodies",
    "iter_contents",
    "mutate_map",
    "mutate_paths",
    "packed",
    "parts",
    "path_penalty",
    "produced",
    "raw_text",
    "review_key",
    "rock",
    "rock_file",
    "slices_used",
    "stage_packages",
    "targets",
    "tests_passed",
    "tests_text",
    "transcript",
]

# lines orientation prints, spread through its output: harnesses truncate long
# tool output (codex keeps the tail), so any one of these hitting means it ran.
# "live releases:" is printed whether or not the cwd is a checkout.
ORIENTATION_MARKERS = (
    "working dir: ",
    "manifest format:",
    "existing slices:",
    "live releases:",
)

OUT = Path(os.environ["PATS_SCORED_DIR"])
TASK = os.environ["PATS_SCORED_TASK_NAME"]  # the case id (also the single-target package)

_EXP_SUFFIX = ".expected.yaml"


class NA(Exception):
    """raised by a scorer that does not apply to this case -> prints 'na'."""


def emit(fn: Callable[[], float]) -> None:
    """run a scorer and print its verdict: a [0,1] float, or 'na' on NA."""
    try:
        print(f"{fn():.4f}")
    except NA:
        print("na")


def targets() -> list[str]:
    """stems with a ground-truth file -- the set of packages that should exist."""
    ts = sorted(p.name[: -len(_EXP_SUFFIX)] for p in OUT.glob("*" + _EXP_SUFFIX))
    return ts or [TASK]  # fallback so a missing-expected run still scores (-> 0s)


def avg(fn: Callable[[str], float]) -> float:
    ts = targets()
    vals = [fn(t) for t in ts]
    return sum(vals) / len(vals) if vals else 1.0


def load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None


def produced(t: str) -> Any:
    return load(OUT / f"{t}.yaml")


def expected(t: str) -> Any:
    return load(OUT / f"{t}{_EXP_SUFFIX}")


def fmt() -> int | None:
    """Manifest format of the case's branch: <case>.format, which bin/stage reads
    from the cloned chisel.yaml."""
    f = OUT / f"{TASK}.format"
    if not f.exists():
        return None
    m = re.search(r"\d+", f.read_text(encoding="utf-8"))
    return int(m.group()) if m else None


# slice names the conventions reject (kb/_slice-conventions.md). packages coin
# their own names freely (python's `utils`, binutils' `linker`), so the check
# flags known-wrong names instead of demanding a fixed vocabulary.
REJECTED_SLICE_NAMES = {"bin", "lib", "configs", "dev", "all", "license", "notice", "rules"}
BIN_DIRS = ("/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/usr/libexec/")


def iter_contents(doc: Any):
    if not isinstance(doc, dict):
        return
    slices = doc.get("slices")
    if not isinstance(slices, dict):
        return
    for sname, body in slices.items():
        if not isinstance(body, dict):
            continue
        contents = body.get("contents")
        if not isinstance(contents, dict):
            continue
        for path, entry in contents.items():
            yield sname, path, entry


def iter_bodies(doc: Any):
    if not isinstance(doc, dict):
        return
    slices = doc.get("slices")
    if not isinstance(slices, dict):
        return
    for name, body in slices.items():
        if isinstance(body, dict):
            yield name, body


def mutate_map(doc: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, body in iter_bodies(doc):
        m = body.get("mutate")
        if isinstance(m, str) and m.strip():
            out[name] = m
    return out


def mutate_paths(script: str) -> set[str]:
    return set(re.findall(r'content\.(?:read|write)\s*\(\s*["\']([^"\']+)["\']', script))


def content_paths(doc: Any) -> set[str]:
    return {str(p).lower() for _, p, _ in iter_contents(doc)}


def has_slices(doc: Any) -> bool:
    """doc has a non-empty slices: dict -- i.e. is shaped like a real SDF, not
    some other invented schema. compliance scorers (no forbidden path, sorted
    keys, ...) gate on this: absence of slices is not evidence of compliance."""
    return isinstance(doc, dict) and isinstance(doc.get("slices"), dict) and bool(doc["slices"])


def declared_binaries(doc: Any) -> set[str]:
    out: set[str] = set()
    for _, path, _ in iter_contents(doc):
        if not any(path.startswith(d) for d in BIN_DIRS):
            continue
        if path.endswith("/") or "*" in path or "?" in path:
            continue
        out.add(path.rsplit("/", 1)[-1])
    return out


def path_penalty(matches: Callable[[str], bool], allow: Callable[[str, Any], bool] = lambda p, d: False) -> Callable[[str], float]:
    def f(t: str) -> float:
        doc = produced(t)
        if not has_slices(doc):
            return 0.0
        total = bad = 0
        for _, path, _ in iter_contents(doc):
            total += 1
            if allow(path, doc):
                continue
            if matches(path):
                bad += 1
        return 1.0 if total == 0 else (total - bad) / total
    return f


# --- transcript parsing ------------------------------------------------------
# shared by scorers that read the agent's event stream rather than its files.

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "patch"}
_PATH_KEYS = ("file_path", "filePath", "path", "notebook_path")
_PI_EVENTS = {"session", "agent_start", "turn_start", "message_start", "message_update", "message_end",
              "turn_end", "agent_end", "agent_settled", "tool_execution_start", "tool_execution_update",
              "tool_execution_end"}


def _jsonl(path: Path):
    """yield parsed json objects from a jsonl file, skipping non-json lines."""
    import json
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "")


def calls() -> dict:
    """the agent's tool calls and text from stdout.log, in order, any harness.

        calls   one dict per tool call: tool (lowercased name), input (dict),
                command (bash command or ""), output (str), error (bool),
                done (a result came back), paths (files a write/edit-style
                call touched)
        texts   assistant-visible text, not tool results
        parsed  False when no known format matched (only stderr/raw left)

    formats: claude stream-json, opencode --format json, codex --json, pi
    --mode json.
    """
    out: list[dict] = []
    texts: list[str] = []
    by_id: dict[str, dict] = {}
    parsed = False

    def add(tool: str, inp: Any, cid: Any = None, output: str = "", error: bool = False, done: bool = True) -> dict:
        inp = inp if isinstance(inp, dict) else {}
        tool = str(tool or "").lower()
        c = {
            "tool": tool,
            "input": inp,
            "command": str(inp.get("command", "")) if tool in ("bash", "shell") or "command" in inp else "",
            "output": output,
            "error": error,
            "done": done,
            "paths": [str(inp[k]) for k in _PATH_KEYS if k in inp] if tool in _WRITE_TOOLS else [],
        }
        out.append(c)
        if cid is not None:
            by_id[str(cid)] = c
        return c

    for ev in _jsonl(OUT / "stdout.log"):
        t = ev.get("type")
        # codex: {"type": "item.completed", "item": {...}}. item.started would double-count.
        item = ev.get("item")
        if isinstance(item, dict) and str(t or "").startswith("item."):
            parsed = True
            if t != "item.completed":
                continue
            kind = item.get("type")
            if kind == "agent_message":
                texts.append(str(item.get("text", "")))
            elif kind == "command_execution":
                add("bash", {"command": item.get("command", "")}, output=str(item.get("aggregated_output") or ""),
                    error=item.get("exit_code") not in (0, None))
            elif kind == "file_change":
                c = add("patch", {})
                c["paths"] = [str(ch["path"]) for ch in item.get("changes") or [] if isinstance(ch, dict) and ch.get("path")]
            continue
        # opencode: a tool_use event carries input and result together.
        part = ev.get("part")
        if isinstance(part, dict):
            parsed = True
            if t == "text":
                texts.append(str(part.get("text", "")))
            elif t == "tool_use":
                st = part.get("state") or {}
                add(part.get("tool", ""), st.get("input"), output=str(st.get("output") or st.get("error") or ""),
                    error=st.get("status") == "error")
            continue
        # pi: calls and results as their own events, text on the finished message.
        if t in _PI_EVENTS and "session_id" not in ev:
            parsed = True
            if t == "tool_execution_start":
                add(ev.get("toolName", ""), ev.get("args"), ev.get("toolCallId"), done=False)
            elif t == "tool_execution_end":
                c = by_id.get(str(ev.get("toolCallId")))
                if c is not None:
                    r = ev.get("result")
                    c["output"] = _text_of(r.get("content")) if isinstance(r, dict) else str(r or "")
                    c["error"] = bool(ev.get("isError"))
                    c["done"] = True
            elif t == "message_end":
                m = ev.get("message") or {}
                if m.get("role") == "assistant":
                    texts.extend(str(c.get("text", "")) for c in m.get("content") or []
                                 if isinstance(c, dict) and c.get("type") == "text")
            continue
        # claude: tool_use on assistant messages, tool_result on user messages.
        if "message" in ev or "session_id" in ev:
            parsed = True
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and msg.get("role") == "assistant":
                texts.append(str(c.get("text", "")))
            elif c.get("type") == "tool_use":
                add(c.get("name", ""), c.get("input"), c.get("id"), done=False)
            elif c.get("type") == "tool_result":
                r = by_id.get(str(c.get("tool_use_id")))
                if r is not None:
                    r["output"] = _text_of(c.get("content"))
                    r["error"] = bool(c.get("is_error"))
                    r["done"] = True
    return {"calls": out, "texts": texts, "parsed": parsed}


def raw_text() -> str:
    """ansi-stripped stdout + stderr, for the plain-text fallback."""
    chunks = []
    for name in ("stdout.log", "stderr.log"):
        p = OUT / name
        if p.exists():
            chunks.append(_ANSI.sub("", p.read_text(encoding="utf-8", errors="replace")))
    return "\n".join(chunks)


def final_text() -> str:
    """the agent's last non-empty message: the answer an autonomous run ends on."""
    c = calls()
    texts = [t for t in c["texts"] if t.strip()]
    if texts:
        return texts[-1]
    if not c["parsed"]:
        return raw_text()
    return ""


def review_key() -> dict:
    """the reviewer task's key.yaml: expected verdict and seeded defects."""
    p = Path(os.environ.get("PATS_SCORED_TASK_DIR", "")) / "key.yaml"
    if not p.is_file():
        raise NA
    return yaml.safe_load(p.read_text()) or {}


def transcript() -> dict:
    """what the agent said and did, flattened (see calls() for the ordered form).

        texts     assistant-visible output text (NOT tool results -- a scorer
                  grepping for skill phrases must not match the skill file the
                  agent read)
        commands  bash commands the agent ran
        writes    file paths touched via write/edit-style tools
        parsed    True when a structured format matched; False -> plain-text
                  fallback, only `raw` is meaningful
        raw       ansi-stripped stdout+stderr, all formats
    """
    c = calls()
    return {
        "texts": c["texts"],
        "commands": [x["command"] for x in c["calls"] if x["command"]],
        "writes": [p for x in c["calls"] for p in x["paths"]],
        "parsed": c["parsed"],
        "raw": raw_text(),
    }


def fmt_compat(uses: Callable[[Any], bool], min_ok_fmt: int, exact_ok: int | None = None) -> float:
    """branch-gated per-target compat. NA when the branch is unknown."""
    f_ = fmt()
    if f_ is None:
        raise NA

    def f(t: str) -> float:
        doc = produced(t)
        if not isinstance(doc, dict):
            return 0.0
        if f_ >= min_ok_fmt or (exact_ok is not None and f_ == exact_ok):
            return 1.0
        return 0.0 if uses(doc) else 1.0
    return avg(f)


# --- rock tasks -----------------------------------------------------------------

# <package>_<slice>: a stage-packages entry with an underscore is a slice.
SLICE = re.compile(r"^[a-z0-9][a-z0-9.+-]*_[a-z0-9][a-z0-9-]*$")

# a test run where every task passed: test-rock's summary line, or rockcraft's
# own when the agent ran `rockcraft test` directly.
_TESTS_PASSED = re.compile(r"tasks: \{passed: [1-9][0-9]*, failed: 0, aborted: 0\}|Testing successful\.")


def case() -> dict:
    """the rock task's expectations; NA for any other task."""
    c = load(OUT / f"{TASK}.case.yaml")
    if not isinstance(c, dict):
        raise NA
    return c


def rock_file(name: str = "rockcraft.yaml") -> dict | None:
    d = load(OUT / name)
    return d if isinstance(d, dict) else None


def rock() -> dict | None:
    return rock_file()


def parts(doc: dict | None) -> dict:
    p = (doc or {}).get("parts")
    return {k: (v if isinstance(v, dict) else {}) for k, v in p.items()} if isinstance(p, dict) else {}


def stage_packages(doc: dict | None) -> list[str]:
    return [str(x) for p in parts(doc).values() for x in (p.get("stage-packages") or [])]


def slices_used(doc: dict | None) -> set[str]:
    """slices in stage-packages, plus the args of any manual `chisel cut`."""
    used = {s for s in stage_packages(doc) if SLICE.match(s)}
    for p in parts(doc).values():
        for k, v in p.items():
            if str(k).startswith("override-") and isinstance(v, str) and "chisel cut" in v:
                used.update(t for t in v.replace("\\\n", " ").split() if SLICE.match(t))
    return used


def tests_text() -> str | None:
    p = OUT / "tests.txt"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None


def packed() -> float:
    """1.0 a pack ran and left a .rock; 0.5 a pack ran but left none; 0 never packed."""
    t = transcript()
    cmds = "\n".join(t["commands"]) if t["parsed"] else t["raw"]
    if "pack-rock.py" not in cmds and "rockcraft pack" not in cmds:
        return 0.0
    rocks = OUT / "rocks.txt"
    return 1.0 if rocks.exists() and rocks.read_text().strip() else 0.5


def tests_passed() -> float:
    """1.0 a test run passed every task; 0.5 tests ran, not all passing; 0 never ran."""
    t = transcript()
    cmds = "\n".join(t["commands"]) if t["parsed"] else t["raw"]
    if "test-rock.py" not in cmds and "rockcraft test" not in cmds:
        return 0.0
    return 1.0 if _TESTS_PASSED.search(t["raw"]) else 0.5
