"""AST lint guard: ensure target file constructs no stateful singletons or app
instances at module-import time.

Detects:
- Direct calls:                 ``app = create_app()``
- Aliased calls:                ``builder = create_app; app = builder()``
- Calls inside top-level if/try/with/for blocks (still execute at import time)
- Calls inside class bodies but outside method definitions
                                ``class C: x = StateStore()``

Skips:
- Calls inside def / async def bodies (not import-time)
- Calls inside lambdas (the lambda body is not run at import time)

Usage:
    python scripts/check_no_global_state.py --self-test
        Run built-in good/bad samples; exit 0 if both behave as expected.

    python scripts/check_no_global_state.py PATH
        Scan PATH; exit 1 on violation, 0 on clean, 2 on usage error.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_BASE = {
    "StateStore",
    "RunManager",
    "OperationCoordinator",
    "RuntimeModelConfig",
    "FastAPI",
    "create_app",
}


def _called_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _collect_aliases(module: ast.Module) -> set[str]:
    """Fixed-point alias resolution at module top level."""
    forbidden = set(FORBIDDEN_BASE)
    changed = True
    while changed:
        changed = False
        for node in module.body:
            if isinstance(node, ast.Assign):
                value = node.value
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                targets = [node.target]
            else:
                continue
            if isinstance(value, ast.Name) and value.id in forbidden:
                for tgt in targets:
                    if isinstance(tgt, ast.Name) and tgt.id not in forbidden:
                        forbidden.add(tgt.id)
                        changed = True
    return forbidden


def _walk_import_time(node: ast.AST):
    """Yield every node executed at module-import time.

    Skip function bodies and lambda bodies, but DO descend into class bodies
    (class statements run at import time when the class is created).
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _walk_import_time(child)


def _scan(module: ast.Module, forbidden: set[str]) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    for top in module.body:
        # Top-level def / async def define a function; the body does not run
        # at import time, only when the function is later called.
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # ClassDef body executes when the class object is built (import time),
        # so descend into it. _walk_import_time still skips method def bodies.
        for sub in _walk_import_time(top):
            if isinstance(sub, ast.Call):
                name = _called_name(sub)
                if name in forbidden:
                    bad.append((sub.lineno, name))
    return bad


_GOOD_SAMPLE = """\
def create_app():
    from somewhere import StateStore
    return StateStore()

class Foo:
    def method(self):
        return create_app()
"""

_BAD_SAMPLES: dict[str, str] = {
    "direct top-level call": (
        "from x import create_app\n"
        "app = create_app()\n"
    ),
    "aliased top-level call": (
        "from x import create_app\n"
        "builder = create_app\n"
        "app = builder()\n"
    ),
    "if-block top-level call": (
        "from x import create_app\n"
        "if True:\n"
        "    app = create_app()\n"
    ),
    "class-body attribute": (
        "from x import StateStore\n"
        "class C:\n"
        "    x = StateStore()\n"
    ),
}


def _self_test() -> int:
    """In-memory check: good sample passes, all bad samples fail."""
    tree_good = ast.parse(_GOOD_SAMPLE)
    bad_in_good = _scan(tree_good, _collect_aliases(tree_good))
    if bad_in_good:
        print(f"SELF-TEST FAIL: good sample wrongly flagged: {bad_in_good}")
        return 1

    for label, src in _BAD_SAMPLES.items():
        tree = ast.parse(src)
        bad = _scan(tree, _collect_aliases(tree))
        if not bad:
            print(f"SELF-TEST FAIL: bad sample '{label}' not detected")
            return 1

    print(
        f"SELF-TEST OK: 1 good + {len(_BAD_SAMPLES)} bad samples behave as expected"
    )
    return 0


def main() -> int:
    if len(sys.argv) <= 1 or "--self-test" in sys.argv[1:]:
        return _self_test()
    target = Path(sys.argv[1])
    if not target.exists():
        print(f"FAIL: {target} not found")
        return 2
    # utf-8-sig transparently strips a leading BOM; ast.parse rejects it otherwise.
    tree = ast.parse(target.read_text(encoding="utf-8-sig"))
    forbidden = _collect_aliases(tree)
    bad = _scan(tree, forbidden)
    if bad:
        print(
            f"FAIL: {target} has module-import-time construction of stateful singletons:"
        )
        for ln, name in bad:
            print(f"  line {ln}: {name}() -- must move inside create_app() or main.py")
        print(f"Detected forbidden symbols (incl. aliases): {sorted(forbidden)}")
        return 1
    print(f"OK: {target} is side-effect free at module level")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
