"""Architecture boundary tests.

These tests use Python AST scanning to enforce the project's most
important dependency boundaries:

* Only ``src/dev_knowledge_agent/adapters/lightrag/`` may import LightRAG.
* No LightRAG type may be re-exported upward from the adapter package.
* ``tools/`` may not import ``adapters/`` (Tool depends on the Port, not
  the concrete Adapter).
* ``protocols/`` may not import ``adapters/``, ``tools/`` or ``agent/``.
* ``evidence/`` may not import LightRAG, adapters, tools or agent.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "dev_knowledge_agent"
ALLOWED_IMPORT_DIR = SRC_ROOT / "adapters" / "lightrag"

FORBIDDEN_MODULE_ROOT = "lightrag"

BANNED_BINDINGS = ("LightRAG", "QueryParam")

FAILURE_TEMPLATE = "Forbidden LightRAG dependency:\n{file}:{line}\n{codeline}"


def _iter_python_files(root: Path) -> Iterable[Path]:
    return sorted(root.rglob("*.py"))


def _is_allowed(file: Path) -> bool:
    try:
        file.resolve().relative_to(ALLOWED_IMPORT_DIR.resolve())
        return True
    except ValueError:
        return False


def _startswith_forbidden(value: str) -> bool:
    """Whether a module name targets the forbidden LightRAG root."""
    return value == FORBIDDEN_MODULE_ROOT or value.startswith(f"{FORBIDDEN_MODULE_ROOT}.")


def _first_arg_is_constant_str(call_node: ast.Call) -> str | None:
    """Return the first call argument's string value, if it is a constant string."""
    if not call_node.args:
        return None
    arg = call_node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _extract_dynamic_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Find ``importlib.import_module("lightrag...")`` / ``__import__("...")`` calls."""
    findings: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            value = _first_arg_is_constant_str(node)
            if value is not None and _startswith_forbidden(value):
                findings.append((node.lineno, f"importlib.import_module({value!r})"))
        elif isinstance(func, ast.Name) and func.id == "__import__":
            value = _first_arg_is_constant_str(node)
            if value is not None and _startswith_forbidden(value):
                findings.append((node.lineno, f"__import__({value!r})"))
    return findings


def _re_export_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Check for re-export of LightRAG / QueryParam names inside the adapter __init__."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            #: star import from lightrag re-exports everything including types
            star_import = node.names == [ast.alias(name="*")]
            if node.module and star_import and _startswith_forbidden(node.module):
                violations.append((node.lineno, "from lightrag import *"))
            for alias in node.names:
                if alias.name in BANNED_BINDINGS:
                    module = node.module or "?"
                    violations.append((node.lineno, f"from {module} import {alias.name}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                binds_banned = alias.asname is None and alias.name in BANNED_BINDINGS
                if binds_banned or (alias.asname is not None and alias.asname in BANNED_BINDINGS):
                    violations.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in BANNED_BINDINGS:
                    violations.append((node.lineno, f"assignment re-exports {target.id}"))
    return violations


def _scan_file(file: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise AssertionError(f"Syntax error while scanning {file}: {exc}") from exc

    violations: list[tuple[int, str]] = []

    if not _is_allowed(file):
        for node in ast.walk(tree):
            #: import lightrag / import lightrag.xxx
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _startswith_forbidden(alias.name):
                        violations.append((node.lineno, f"import {alias.name}"))
                continue
            #: from lightrag import ... / from lightrag.xxx import ...
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and _startswith_forbidden(node.module)
            ):
                names = ", ".join(a.name for a in node.names)
                violations.append((node.lineno, f"from {node.module} import {names}"))
        violations.extend(_extract_dynamic_imports(tree))

    #: re-export protection applies to the adapter __init__.py itself
    if file.resolve() == (ALLOWED_IMPORT_DIR / "__init__.py").resolve():
        violations.extend(_re_export_violations(tree))

    return violations


def _collect_violations() -> list[str]:
    messages: list[str] = []
    for file in _iter_python_files(SRC_ROOT):
        for lineno, codeline in _scan_file(file):
            rel_path = file.relative_to(PROJECT_ROOT).as_posix()
            messages.append(FAILURE_TEMPLATE.format(file=rel_path, line=lineno, codeline=codeline))
    return messages


def test_no_forbidden_lightrag_import_outside_adapter() -> None:
    """Production code may import LightRAG only inside adapters/lightrag."""
    violations = _collect_violations()
    assert violations == [], "\n".join(violations)


def test_adapter_init_does_not_re_export_lightrag_types() -> None:
    """adapters/lightrag/__init__.py must not re-export LightRAG/QueryParam."""
    init_file = ALLOWED_IMPORT_DIR / "__init__.py"
    tree = ast.parse(init_file.read_text(encoding="utf-8"))
    violations = _re_export_violations(tree)
    assert violations == [], "\n".join(
        FAILURE_TEMPLATE.format(file="adapters/lightrag/__init__.py", line=line, codeline=codeline)
        for line, codeline in violations
    )


def test_adapter_package_imports_are_isolated() -> None:
    """Importing the adapter package must not leak LightRAG types upward."""
    from dev_knowledge_agent.adapters import lightrag as lightrag_adapter

    assert not hasattr(lightrag_adapter, "LightRAG")
    assert not hasattr(lightrag_adapter, "QueryParam")


# --------------------------------------------------------------------------- #
# Stage 2 additions: keep the layers decoupled
# --------------------------------------------------------------------------- #

#: forbidden module prefixes, relative to dev_knowledge_agent.*
TOOLS_FORBIDDEN_ADAPTER = ("dev_knowledge_agent.adapters",)

PROTOCOL_FORBIDDEN = (
    "dev_knowledge_agent.adapters",
    "dev_knowledge_agent.tools",
    "dev_knowledge_agent.agent",
)

EVIDENCE_FORBIDDEN = (
    "dev_knowledge_agent.adapters",
    "dev_knowledge_agent.tools",
    "dev_knowledge_agent.agent",
)


def _iter_import_tuples(tree: ast.Module):
    """Yield (lineno, imported_name) for every static import/from-import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def _imports_under_package(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return list(_iter_import_tuples(tree))


def _assert_layer_does_not_import(
    layer_dir: Path,
    forbidden_prefixes: tuple[str, ...],
    extra: tuple[str, ...] = (),
) -> None:
    """Assert no file under ``layer_dir`` imports any forbidden prefix."""
    forbidden = tuple(forbidden_prefixes) + tuple(extra)
    violations: list[str] = []
    for file in _iter_python_files(layer_dir):
        for lineno, imported in _imports_under_package(file):
            if imported.startswith(forbidden):
                rel = file.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{rel}:{lineno}: import {imported}")
    assert violations == [], "\n".join(violations)


def test_tools_do_not_import_adapters() -> None:
    """tools/ must not import adapters/ (Tool -> Port, not concrete Adapter)."""
    layer = SRC_ROOT / "tools"
    _assert_layer_does_not_import(layer, TOOLS_FORBIDDEN_ADAPTER)


def test_tools_do_not_import_lightrag() -> None:
    """tools/ must not import LightRAG at all."""
    layer = SRC_ROOT / "tools"
    _assert_layer_does_not_import(layer, (FORBIDDEN_MODULE_ROOT,))


def test_protocols_do_not_import_downstream_layers() -> None:
    """protocols/ must be an upstream abstraction (no adapters/tools/agent)."""
    layer = SRC_ROOT / "protocols"
    _assert_layer_does_not_import(layer, PROTOCOL_FORBIDDEN)


def test_evidence_do_not_import_downstream_layers() -> None:
    """evidence/ must be domain-only (no LightRAG/adapters/tools/agent)."""
    layer = SRC_ROOT / "evidence"
    _assert_layer_does_not_import(layer, EVIDENCE_FORBIDDEN, extra=(FORBIDDEN_MODULE_ROOT,))
