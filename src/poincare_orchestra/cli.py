"""``poincare-orchestra list | run | eval | inspect | export | validate``.

Every command that takes a scenario accepts a bundled name (``list`` prints
them) or the path to a ``.json`` / ``.yaml`` scenario file. Exit codes: 0 on
success, 1 when ``validate`` finds a problem, 2 when a scenario cannot be loaded.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .scenario import Scenario, list_scenarios, load_scenario

logger = logging.getLogger("poincare_orchestra")


class _StderrHandler(logging.Handler):
    """Writes to whatever ``sys.stderr`` is at emit time (so output stays visible under test capture)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except Exception:  # pragma: no cover
            self.handleError(record)


def configure_logging(verbosity: int) -> None:
    """Send the ``poincare_orchestra`` logger to stderr: warnings by default, ``-v`` INFO, ``-vv`` DEBUG."""
    logger.setLevel(logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING)
    if not any(isinstance(h, _StderrHandler) for h in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)


def _load(spec: str) -> Scenario | None:
    try:
        return load_scenario(spec)
    except (KeyError, FileNotFoundError, ValueError, ImportError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {msg}", file=sys.stderr)
        return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poincare-orchestra", description="Scenario-first LLM orchestration with geometry-aware memory."
    )
    p.add_argument(
        "-v", "--verbose", action="count", default=0, help="log pipeline stages to stderr (-vv for debug)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list bundled scenarios")

    s = sub.add_parser("run", help="run one question through a scenario (offline mock providers by default)")
    s.add_argument("scenario", help="bundled name or path to a .json/.yaml scenario")
    s.add_argument("question")
    s.add_argument(
        "--degrade-after",
        type=int,
        default=None,
        help="simulate throttling on the first provider after N calls",
    )
    s.add_argument(
        "--fail-after", type=int, default=None, help="simulate an outage of the first provider after N calls"
    )
    s.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="NAME=MODEL",
        help="use a real model through LiteLLM for provider NAME (repeatable), e.g. provider-a=openai/gpt-4o-mini",
    )
    s.add_argument(
        "--timeout", type=float, default=None, help="per-call timeout in seconds for --model providers"
    )
    s.add_argument(
        "--json", action="store_true", help="print the RunResult as JSON instead of the explanation"
    )

    s = sub.add_parser("eval", help="run a scenario's bundled tasks and report facet recall")
    s.add_argument("scenario", help="bundled name or path to a .json/.yaml scenario")
    s.add_argument("--json", action="store_true", help="print the EvalReport as JSON")

    s = sub.add_parser("inspect", help="write the scenario memory's interactive HTML inspector")
    s.add_argument("scenario", help="bundled name or path to a .json/.yaml scenario")
    s.add_argument("-o", "--out", type=Path, default=None, help="output file (default: <scenario name>.html)")

    s = sub.add_parser(
        "export", help="write a scenario as a JSON or YAML file (a starting point for your own)"
    )
    s.add_argument("scenario", help="bundled name or path to a .json/.yaml scenario")
    s.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="output file; the suffix picks the format (default: stdout)",
    )
    s.add_argument(
        "--format",
        choices=["json", "yaml"],
        default=None,
        help="format when it cannot be inferred (default: yaml)",
    )

    s = sub.add_parser("validate", help="load a scenario file and report problems")
    s.add_argument("scenario", help="bundled name or path to a .json/.yaml scenario")
    return p


def _providers(sc: Scenario, a: argparse.Namespace) -> list[object] | None:
    from .ensemble import LiteLLMProvider, MockProvider

    if a.model:
        providers: list[object] = []
        for spec in a.model:
            name, sep, model = spec.partition("=")
            if not sep or not name or not model:
                raise ValueError(f"--model expects NAME=MODEL, got {spec!r}")
            providers.append(LiteLLMProvider(name, model, timeout_s=a.timeout))
        return providers
    if a.degrade_after is None and a.fail_after is None:
        return None
    names = sorted({pr.provider for pr in sc.profiles})
    return [
        MockProvider(
            n,
            degrade_after=a.degrade_after if i == 0 else None,
            fail_after=a.fail_after if i == 0 else None,
        )
        for i, n in enumerate(names)
    ]


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    configure_logging(a.verbose)

    if a.cmd == "list":
        for name in list_scenarios():
            sc = load_scenario(name)
            print(f"{name:18s} {sc.title} — {sc.description}")
        return 0

    if a.cmd == "validate":
        try:
            sc = load_scenario(a.scenario)
        except (KeyError, FileNotFoundError, ValueError, ImportError) as exc:
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            print(f"invalid: {msg}", file=sys.stderr)
            return 1
        print(
            f"ok: {sc.name} — {len(sc.knowledge)} knowledge items, {len(sc.profiles)} profiles, "
            f"{len(sc.roles)} roles, {len(sc.tasks)} tasks, decay={sc.policy.decay}"
        )
        return 0

    sc_or_none = _load(a.scenario)
    if sc_or_none is None:
        return 2
    sc = sc_or_none

    if a.cmd == "export":
        try:
            if a.out is not None:
                sc.to_file(a.out, format=a.format)
                print(f"wrote {a.out}")
            elif (a.format or "yaml") == "json":
                print(sc.model_dump_json(indent=2, exclude_defaults=True, exclude_none=True))
            else:
                from .scenario import _yaml

                print(_yaml().safe_dump(sc.to_dict(), sort_keys=False, allow_unicode=True, width=100), end="")
        except (ValueError, ImportError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0

    from .orchestrator import Orchestrator

    if a.cmd == "run":
        try:
            providers = _providers(sc, a)
        except (ValueError, ImportError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        res = Orchestrator(sc, providers=providers).run(a.question)  # type: ignore[arg-type]
        print(res.to_json() if a.json else res.explain())
    elif a.cmd == "eval":
        rep = Orchestrator(sc).evaluate()
        if a.json:
            print(rep.to_json())
        else:
            print(rep.summary())
            for t in rep.per_task:
                print(
                    f"  recall={t['facet_recall']:.2f} J={t['J']:.3f} subtasks={t['subtasks']} missing={t['missing']}  {t['question']}"
                )
    elif a.cmd == "inspect":
        out = a.out or Path(f"{sc.name}.html")
        sc.build_memory().inspect(out, title=f"poincare-orchestra · {sc.title}")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
