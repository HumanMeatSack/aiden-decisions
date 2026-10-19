"""Check the distributable file set and decision-layer dependency boundary."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "output", "dist", "build", "__pycache__"}


def release_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True,
    )
    if result.returncode == 0:
        return sorted({ROOT / item.decode() for item in result.stdout.split(b"\0") if item})
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and not any(
        part in SKIP or part.startswith(".venv") or part.endswith(".egg-info")
        for part in p.relative_to(ROOT).parts
    ))


def main():
    errors = []
    files = release_files()
    patterns = {
        "absolute personal path": re.compile(r"/[U]sers/|/[h]ome/[^/\s]+/"),
        "private tailnet hostname": re.compile(r"[.]ts[.]net\b"),
        "private LAN address": re.compile(r"\b192[.]168[.]\d+[.]\d+\b"),
        "private key material": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
        "credential token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9]{20,}"),
    }
    for path in files:
        rel = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"{rel}: symlinks are not part of this release")
            continue
        if path.suffix.lower() in {".safetensors", ".gguf", ".pt", ".pem", ".key"} or "secrets" in rel.parts:
            errors.append(f"{rel}: private configuration/model material")
        if path.stat().st_size > 512 * 1024:
            errors.append(f"{rel}: unexpectedly large release file")
        try:
            text = path.read_text()
        except UnicodeError:
            errors.append(f"{rel}: unexpected binary release file")
            continue
        for label, pattern in patterns.items():
            if pattern.search(text):
                errors.append(f"{rel}: {label}")
        if path.suffix == ".json":
            json.loads(text)
        if rel.parts[:2] == ("src", "aiden_decisions") and path.suffix == ".py":
            for node in ast.walk(ast.parse(text)):
                roots = []
                if isinstance(node, ast.Import):
                    roots = [item.name.split(".")[0] for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    roots = [(node.module or "").split(".")[0]]
                for name in roots:
                    if name not in sys.stdlib_module_names | {"aiden_decisions", "mcp", "pydantic"}:
                        errors.append(f"{rel}: non-decision dependency {name}")
    print(json.dumps({"files_checked": len(files), "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
