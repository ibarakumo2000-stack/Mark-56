"""Guarded local coding workspace for Mark 56.

All file paths are confined to an explicitly configured workspace. Edits are
previewed as unified diffs and require an explicit confirmation plus the SHA-256
of the version that was reviewed. Tests run only from a small fixed command set.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_EDIT_BYTES = 1_000_000
TEST_TIMEOUT_SECONDS = 120


def _root() -> Path:
    raw = os.environ.get("MARK56_WORKSPACE", "").strip()
    root = Path(raw).expanduser() if raw else Path.cwd()
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Configured workspace directory does not exist.")
    return root


def _target(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A relative file path is required.")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("Absolute paths are not allowed.")
    root = _root()
    target = (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes the configured workspace.")
    if target == root:
        raise ValueError("A file path, not the workspace root, is required.")
    return target


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(relative_path: str) -> tuple[Path, bytes]:
    target = _target(relative_path)
    if not target.is_file():
        raise FileNotFoundError("File not found inside the workspace.")
    data = target.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 1 MB workspace read limit.")
    return target, data


def _run_tests(parameters: dict) -> str:
    suite = str(parameters.get("suite") or "unittest").lower()
    root = _root()
    if suite == "unittest":
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    elif suite == "pytest":
        command = [sys.executable, "-m", "pytest", "-q"]
    elif suite == "compile":
        command = [sys.executable, "-m", "compileall", "-q",
                   "main.py", "ui.py", "core", "actions", "plugins",
                   "dashboard", "memory", "tests"]
    else:
        return "Blocked: suite must be unittest, pytest, or compile."
    try:
        result = subprocess.run(
            command, cwd=root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=TEST_TIMEOUT_SECONDS, check=False,
            shell=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return f"Test command timed out after {TEST_TIMEOUT_SECONDS} seconds."
    except Exception as exc:
        return f"Test command failed to start ({type(exc).__name__})."
    output = (result.stdout or "")[-12000:]
    return json.dumps({
        "ok": result.returncode == 0,
        "suite": suite,
        "exit_code": result.returncode,
        "command": command,
        "output": output,
    }, ensure_ascii=False)


def run(parameters: dict, **_context) -> str:
    """Plugin API. Supported operations: list, read, propose, apply, test."""
    p = parameters or {}
    operation = str(p.get("operation") or "list").strip().lower()
    try:
        root = _root()
        if operation == "list":
            path = _target(p.get("path") or ".")
            if path.is_file():
                return json.dumps({"root": str(root), "files": [path.relative_to(root).as_posix()]})
            files = []
            for item in sorted(path.rglob("*")):
                if any(part in {".git", ".venv", "venv", "__pycache__", "node_modules",
                                "dist", "build"} for part in item.parts):
                    continue
                if item.is_file() and len(files) < 300:
                    try:
                        if item.stat().st_size <= MAX_FILE_BYTES:
                            files.append(item.relative_to(root).as_posix())
                    except OSError:
                        continue
            return json.dumps({"root": str(root), "files": files}, ensure_ascii=False)
        if operation == "read":
            target, data = _read(p.get("path"))
            return json.dumps({
                "path": target.relative_to(root).as_posix(),
                "sha256": _digest(data),
                "content": data.decode("utf-8", errors="replace")[:MAX_FILE_BYTES],
            }, ensure_ascii=False)
        if operation == "propose":
            target, old = _read(p.get("path"))
            new_text = p.get("content")
            if not isinstance(new_text, str):
                return "Provide proposed file content as a string."
            new = new_text.encode("utf-8")
            if len(new) > MAX_EDIT_BYTES:
                return "Refused: proposed content exceeds 1 MB."
            before = old.decode("utf-8", errors="replace").splitlines(keepends=True)
            after = new_text.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(
                before, after, fromfile=str(target.relative_to(root)), tofile="proposed"
            ))
            return json.dumps({
                "mode": "proposal_only",
                "path": target.relative_to(root).as_posix(),
                "current_sha256": _digest(old),
                "proposed_sha256": _digest(new),
                "diff": diff[:20000],
                "next_step": "Review this diff. No file has been changed.",
            }, ensure_ascii=False)
        if operation == "apply":
            if p.get("confirmed") is not True:
                return "Blocked: applying an edit requires confirmed=true after reviewing its diff."
            target, old = _read(p.get("path"))
            expected = p.get("expected_sha256")
            if not isinstance(expected, str) or expected != _digest(old):
                return "Blocked: file changed since review or expected_sha256 is missing. Read and propose again."
            content = p.get("content")
            if not isinstance(content, str):
                return "Provide proposed file content as a string."
            new = content.encode("utf-8")
            if len(new) > MAX_EDIT_BYTES:
                return "Refused: proposed content exceeds 1 MB."
            # Refuse symlinks and re-check the destination immediately before write.
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                return "Blocked: unsafe file target."
            target.write_bytes(new)
            return json.dumps({
                "ok": True, "path": target.relative_to(root).as_posix(),
                "sha256": _digest(new), "message": "Edit applied after confirmation.",
            })
        if operation == "test":
            return _run_tests(p)
        return "Unknown operation. Use list, read, propose, apply, or test."
    except (ValueError, FileNotFoundError, OSError) as exc:
        return f"Workspace request rejected: {exc}"


PLUGIN = {
    "name": "coding_workspace",
    "description": (
        "Guarded project workspace: list/read files, preview proposed edits as diffs, "
        "apply an exact reviewed edit only with confirmed=true and a matching SHA-256, "
        "or run a fixed unittest/pytest/compile suite. Paths stay inside MARK56_WORKSPACE "
        "or the current working directory. Does not run arbitrary shell commands."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {"type": "STRING", "description": "list | read | propose | apply | test"},
            "path": {"type": "STRING", "description": "Workspace-relative path"},
            "content": {"type": "STRING", "description": "Full proposed UTF-8 file content"},
            "expected_sha256": {"type": "STRING", "description": "SHA-256 returned by read/propose"},
            "confirmed": {"type": "BOOLEAN", "description": "Explicit approval to apply the reviewed edit"},
            "suite": {"type": "STRING", "description": "For test: unittest | pytest | compile"},
        },
        "required": ["operation"],
    },
}
