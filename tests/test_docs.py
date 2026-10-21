"""Every Python code block in the documentation runs, and every documented ``poincare-orchestra`` command succeeds.

A fence preceded by the line ``<!-- no-exec -->`` is skipped (used for blocks that need
network access or credentials). Python blocks of one page share a namespace, in order, so
a later block may use names defined by an earlier one. Blocks run with the current
directory set to a temporary copy of ``scenarios/`` so relative paths work and written
files (HTML inspectors, exported scenarios) do not land in the repository.
"""

from __future__ import annotations

import re
import shlex
import shutil
import textwrap
from pathlib import Path

import pytest

from poincare_orchestra.cli import main
from tests.conftest import ROOT, SCENARIO_DIR

DOCS = [*sorted((ROOT / "docs").glob("*.md")), ROOT / "README.md"]
SKIP_MARK = "<!-- no-exec -->"
FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<lang>[\w+-]+)(?P<info>[^\n]*)\n(?P<body>.*?)\n(?P=indent)```[ \t]*$",
    re.S | re.M,
)


def fences(path: Path, langs: set[str]) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    for m in FENCE.finditer(text):
        if m.group("lang") not in langs:
            continue
        preceding = text[: m.start()].rstrip().splitlines()
        if preceding and preceding[-1].strip() == SKIP_MARK:
            continue
        line = text[: m.start()].count("\n") + 1
        out.append((line, textwrap.dedent(m.group("body"))))
    return out


@pytest.fixture
def docs_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(SCENARIO_DIR, tmp_path / "scenarios")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_python_blocks_run(path: Path, docs_cwd: Path) -> None:
    blocks = fences(path, {"python", "py"})
    namespace: dict[str, object] = {"__name__": f"docs.{path.stem}"}
    for line, code in blocks:
        try:
            exec(compile(code, f"{path.name}:{line}", "exec"), namespace)
        except Exception as exc:  # pragma: no cover - only on a documentation bug
            pytest.fail(f"{path.name} line {line}: python block raised {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_cli_lines_run(path: Path, docs_cwd: Path) -> None:
    for line, body in fences(path, {"bash", "sh", "console", "shell"}):
        for raw in body.splitlines():
            cmd = raw.strip().removeprefix("$ ").strip()
            if not cmd.startswith("poincare-orchestra "):
                continue
            argv = shlex.split(cmd, comments=True)[1:]  # trailing "# ..." comments are not arguments
            assert main(argv) == 0, f"{path.name} line {line}: `{cmd}` failed"


def test_docs_have_executable_blocks() -> None:
    total = sum(len(fences(p, {"python", "py"})) for p in DOCS)
    assert total >= 10, "the documentation should carry runnable examples"
