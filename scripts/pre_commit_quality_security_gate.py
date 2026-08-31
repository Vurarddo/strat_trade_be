#!/usr/bin/env python3
"""Pre-Commit Quality & Security Gate (Git hook).

1) Security: scan staged text for token/credential patterns (e.g. POCKET_OPTION_SSID literals).
2) Lint & format: ``ruff format`` / black on staged ``.py``; ``ruff check`` on ``src`` + ``tests``;
   ``mypy src/strat_trade`` (requires dev extra ``mypy``).
3) Backtest sanity: pytest on indicator + mock-DataFrame (~100 bars) tests.

If ``black`` / ``isort`` are on PATH they run (isort then black);
otherwise Ruff handles imports + format.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _git_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    return Path(out)


def _venv_bin(name: str) -> list[str]:
    root = _git_root()
    candidate = root / ".venv" / "bin" / name
    if candidate.is_file():
        return [str(candidate)]
    win = root / ".venv" / "Scripts" / f"{name}.exe"
    if win.is_file():
        return [str(win)]
    return [name]


def _python_for_modules() -> list[str]:
    root = _git_root()
    unix_py = root / ".venv" / "bin" / "python"
    if unix_py.is_file():
        return [str(unix_py)]
    win_py = root / ".venv" / "Scripts" / "python.exe"
    if win_py.is_file():
        return [str(win_py)]
    return [sys.executable]


def _ruff_argv() -> list[str]:
    exe = _venv_bin("ruff")[0]
    if exe != "ruff" and Path(exe).is_file():
        return [exe]
    if shutil.which("ruff"):
        return ["ruff"]
    return [*_python_for_modules(), "-m", "ruff"]


def _mypy_argv() -> list[str]:
    exe = _venv_bin("mypy")[0]
    if exe != "mypy" and Path(exe).is_file():
        return [exe]
    if shutil.which("mypy"):
        return ["mypy"]
    return [*_python_for_modules(), "-m", "mypy"]


def _pytest_argv() -> list[str]:
    exe = _venv_bin("pytest")[0]
    if exe != "pytest" and Path(exe).is_file():
        return [exe]
    if shutil.which("pytest"):
        return ["pytest"]
    return [*_python_for_modules(), "-m", "pytest"]


def _staged_paths() -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        text=True,
    )
    return [p for p in out.splitlines() if p.strip()]


def _read_staged_blob(path: str) -> str | None:
    try:
        return subprocess.check_output(["git", "show", f":{path}"], text=True, errors="replace")
    except subprocess.CalledProcessError:
        return None


_TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".env",
    ".txt",
    ".sh",
    ".ini",
    ".cfg",
}


def _is_probably_text(path: str) -> bool:
    suf = Path(path).suffix.lower()
    return suf in _TEXT_SUFFIXES or "." not in Path(path).name


def _line_allows_secret_placeholder(line: str) -> bool:
    lowered = line.lower()
    if "getenv" in lowered or "environ" in lowered:
        return True
    if "settings" in lowered and "=" in line:
        return True
    if "example" in lowered or "placeholder" in lowered or "your_" in lowered:
        return True
    if "# noqa" in lowered and "secret" in lowered:
        return True
    return False


def _scan_secrets(paths: list[str]) -> list[str]:
    violations: list[str] = []

    compiled: list[tuple[str, re.Pattern[str]]] = [
        ("pem_private_key", re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY-----")),
        ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("github_classic_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
        ("gitlab_pat", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
        ("stripe_live_secret", re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ]

    pocket_ssid_assign = re.compile(
        r'(?i)pocket_option_ssid\s*=\s*["\']([^"\']{30,})["\']',
    )
    long_ssid_kw = re.compile(
        r'(?i)\bssid\s*=\s*["\']([A-Za-z0-9_-]{40,})["\']',
    )
    password_literal = re.compile(
        r'(?i)\b(password|passwd)\s*=\s*["\']([^"\']{16,})["\']',
    )

    for path in paths:
        if not _is_probably_text(path):
            continue
        content = _read_staged_blob(path)
        if content is None:
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if _line_allows_secret_placeholder(line):
                continue
            for label, pat in compiled:
                if pat.search(line):
                    violations.append(f"{path}:{i}: possible {label} in staged content")
            if pocket_ssid_assign.search(line) and not re.search(r"[%{]", line):
                violations.append(
                    f"{path}:{i}: literal POCKET_OPTION_SSID-like assignment "
                    "(use env / Settings, not hardcoded secrets)"
                )
            if long_ssid_kw.search(line) and "Fake" not in line and "fake" not in line.lower():
                violations.append(
                    f"{path}:{i}: long ssid=... literal "
                    "(possible Pocket Option / broker credential)"
                )
            if path.endswith(".py") and password_literal.search(line):
                violations.append(
                    f"{path}:{i}: possible hardcoded password=... literal (use env / Settings)"
                )
    return violations


def _format_python(py_files: list[str]) -> None:
    if not py_files:
        return
    os.chdir(_git_root())
    black = shutil.which("black")
    isort = shutil.which("isort")
    if isort:
        subprocess.run([isort, *py_files], check=True)
    else:
        subprocess.run(
            [*_ruff_argv(), "check", "--fix", "--select", "I", *py_files],
            check=True,
        )
    if black:
        subprocess.run([black, *py_files], check=True)
    else:
        subprocess.run([*_ruff_argv(), "format", *py_files], check=True)


def _readd_files(paths: list[str]) -> None:
    if paths:
        subprocess.run(["git", "add", "--", *paths], check=True)


def _run_ruff_check_repo() -> None:
    root = _git_root()
    os.chdir(root)
    subprocess.run([*_ruff_argv(), "check", "src", "tests"], check=True)


def _run_mypy_app() -> None:
    root = _git_root()
    os.chdir(root)
    subprocess.run([*_mypy_argv(), "src/strat_trade"], check=True)


def _run_sanity_tests() -> None:
    root = _git_root()
    os.chdir(root)
    tests = [
        root / "tests" / "test_rsi_indicator.py",
        root / "tests" / "test_indicator_payload.py",
        root / "tests" / "test_backtest_sanity_mock_df.py",
    ]
    existing = [str(p) for p in tests if p.is_file()]
    if not existing:
        return
    subprocess.run([*_pytest_argv(), "-q", *existing], check=True)


def main() -> int:
    root = _git_root()
    os.chdir(root)
    staged = _staged_paths()

    violations = _scan_secrets(staged)
    if violations:
        sys.stderr.write(
            "Pre-commit blocked: possible secrets in staged files.\n"
            "Fix or use env/Settings; for intentional test fixtures keep lines short "
            "or add getenv/settings usage.\n\n",
        )
        for v in violations:
            sys.stderr.write(f"  - {v}\n")
        return 1

    py_staged = [p for p in staged if p.endswith(".py")]
    if py_staged:
        _format_python(py_staged)
        _readd_files(py_staged)

    try:
        _run_ruff_check_repo()
        _run_mypy_app()
        _run_sanity_tests()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            "Pre-commit blocked: ruff / mypy / sanity tests failed "
            f"(cmd exit {getattr(exc, 'returncode', '?')}).\n",
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
