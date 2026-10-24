# Contributing to poincare-orchestra

Thanks for helping. `poincare-orchestra` is the open-source reference implementation of the controller, ensemble and synthesis components of "LLM Orchestration with Geometry-Aware Memory" (IEEE ICBDML 2026), built on `poincare-memory`. Two rules keep it trustworthy: every number in the documentation comes from the evaluation harness with the bundled mock providers (say so when you add one), and the README's provenance paragraph stays as it is (a reference implementation written after the paper; the experimental system is not part of this repository).

The project is maintained by one person, so the rules below exist to keep review fast and predictable. Reading this file takes five minutes and saves a round-trip on almost every pull request.

## Before you start

- Every pull request answers exactly one issue. If there is no issue for what you want to change, open one first; for anything larger than a local fix, wait for a reply so the design is agreed before the work.
- To claim an issue, leave a comment. There is no assignment step. A claim lapses after 14 days without a draft pull request, and one open claim per person is enough.
- Read the issue's **Acceptance** line. That line is the definition of done; a pull request is reviewed against it and nothing else.

## Set up

Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<you>/poincare-orchestra && cd poincare-orchestra
uv venv && uv pip install -e ".[dev,docs,yaml]"
pre-commit install
```

## Checks that must pass

Run these locally before opening a pull request; CI runs the same commands.

```bash
ruff check . && ruff format --check .   # lint and formatting (ruff is pinned in pyproject)
mypy                                     # strict typing of src/
pytest                                   # the suite also executes every code block and CLI command in docs/
mkdocs build --strict                    # when you touched docs/
poincare-orchestra validate scenarios/<file>.yaml   # when you added or changed a scenario
```

## What a good pull request looks like

- Scope: the linked issue, and only that. No reformatting of unrelated code, no drive-by renames, no new dependencies without an issue that agrees to them.
- Tests: at least one test that fails without your change and passes with it. Controller, scheduler and synthesis changes: a test in `tests/` with the mock providers. Scenario changes: `poincare-orchestra eval` must still reach the recorded facet recall for the bundled scenarios.
- Docs: update the user-facing documentation when behaviour changes (`docs/` is built with MkDocs; its code blocks and commands are executed by the test suite, so examples must run) and add a line under *Unreleased* in `CHANGELOG.md`.
- Title in the imperative ("Add `--root` to the tree command"); fill in the pull request template; pull requests are squash-merged, so commit history inside the branch does not matter.

## Maintainer-only files

These are changed by the maintainer only, usually as part of a release. Pull requests that modify them are closed with a note; open an issue instead.

- `.github/` (workflows, templates, `CODEOWNERS`)
- `pyproject.toml` version and dependency pins, `src/*/__init__.py` version
- `CHANGELOG.md` release headings (add your line under *Unreleased*; the maintainer sets the version and date)
- `CITATION.cff`, `.zenodo.json`, `LICENSE`, `SECURITY.md`, `CODE_OF_CONDUCT.md`
- The README's provenance paragraph and citation block
- Recorded evaluation results in `docs/evaluation.md` (re-run the harness and update the whole table, never a single cell)

## AI-assisted contributions

Using an AI tool to write code or text is fine. What is not fine is submitting output you have not run and do not understand. The pull request template asks whether AI assistance was used; answer it, and be ready to explain a design choice in your own words during review. Pull requests that restate the issue without a working change, or whose checks were never run, are closed without further review.

## Review and merge

- Workflows for pull requests from forks run after the maintainer approves them, so there may be a short delay before CI reports.
- All CI jobs must be green. The maintainer reviews within about a week and may ask for one round of changes.
- Merges are squash merges by the maintainer. You keep authorship of the commit and are credited in the CHANGELOG line of the release that ships it.

## Licensing

The project is licensed under Apache-2.0, and contributions are accepted under the same licence (inbound = outbound). By opening a pull request you confirm that you wrote the change or otherwise have the right to submit it under that licence.

## Security

Do not report vulnerabilities in public issues; see `SECURITY.md`.
