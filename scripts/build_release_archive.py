#!/usr/bin/env python3
"""Build a deterministic, fail-closed Marketing Machine release archive.

The release is assembled from an explicit set of project roots.  Runtime data,
local environments, caches, credentials and existing build artifacts are never
copied.  Files are read and validated before the archive is opened, so a failed
validation cannot leave a seemingly usable release behind.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import math
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, cast
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 1
DEFAULT_ARCHIVE_ROOT = "wamocon-marketing-machine"
DEFAULT_SOURCE_DATE_EPOCH = 0
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RELEASE_BYTES = 512 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 64 * 1024 * 1024

PROJECT_DIRECTORIES = (
    "config",
    "db",
    "deploy",
    "docs",
    "Kampagnen",
    "requirements",
    "scripts",
    "src",
    "tests",
    "Zielgruppen",
)

ROOT_FILES = {
    ".gitattributes",
    ".dockerignore",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "bot_architektur.json",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
}

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime-lock-check",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "candidate-runtime-data",
    "dist",
    "node_modules",
    "qa_output",
    "runtime-data",
    "test-results",
    "venv",
}


def _is_excluded_directory_name(name: str) -> bool:
    """Return whether a directory contains generated, local-only material."""

    lowered = name.casefold()
    return lowered in EXCLUDED_DIRECTORY_NAMES or lowered.endswith(".egg-info")

# These locations may legitimately exist on an operator workstation.  They are
# excluded without reading them; credential-like files elsewhere fail closed.
PRIVATE_DIRECTORY_NAMES = {
    ".credentials",
    ".secrets",
    "certificates",
    "certs",
    "credentials",
    "private",
    "secrets",
}

RUNTIME_SUFFIXES = {
    ".bak",
    ".db",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".swp",
    ".tmp",
}
PRIVATE_SUFFIXES = {
    ".cer",
    ".crt",
    ".der",
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
}
ARCHIVE_SUFFIXES = (
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
    ".txz",
    ".xz",
    ".zip",
)
IMAGE_SIGNATURES = {
    ".gif": (b"GIF87a", b"GIF89a"),
    ".ico": (b"\x00\x00\x01\x00",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".jpg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".webp": (b"RIFF",),
}
SAFE_DOCX_PATH = "docs/WAMOCON-Marketing-Handbuch.docx"
SAFE_ARCHIVE_ROOT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

SECRET_NAME_RE = re.compile(
    r"(?:^|[._-])(?:api[_-]?key|client[_-]?secret|credential|htpasswd|"
    r"password|passwd|private[_-]?key|secret|token)(?:$|[._-])",
    re.IGNORECASE,
)
PEM_RE = re.compile(
    r"-----BEGIN\s+(?:(?:RSA|EC|OPENSSH|DSA)\s+)?(?:PRIVATE KEY|CERTIFICATE)-----",
    re.IGNORECASE,
)
KNOWN_CREDENTIAL_RES = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    re.compile(r"\beyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\b"),
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?im)(?<![A-Za-z0-9])"
    r"[\"']?(?:api[_-]?key|private[_-]?key|encryption[_-]?key|"
    r"(?:[A-Za-z0-9]+[_-])+(?:secret|token|password|passwd)|"
    r"secret|token|password|passwd)[\"']?"
    r"[ \t]*[:=][ \t]*"
    r"(?:\$\{(?P<shell>[^{}\r\n]{1,256})\}|"
    r"\"(?P<double>[^\"\r\n]*)\"|'(?P<single>[^'\r\n]*)'|(?P<bare>[^\s,#]+))"
)
SAFE_PLACEHOLDER_VALUES = frozenset(
    {
        "change-me",
        "changeme",
        "configured",
        "demo",
        "dummy",
        "example",
        "fake",
        "local-dev-key",
        "mock",
        "not-configured",
        "ollama",
        "placeholder",
        "redacted",
        "replace-me",
        "replace-with-32-random-bytes-or-valid-key",
        "replace-with-64-random-characters",
        "replace-with-a-long-random-password",
        "replace-with-random-app-secret",
        "replace-with-random-password",
        "replace-with-random-root-password",
        "replace-with-random-secret",
        "sample",
        "secret-value",
        "test",
        "your-key",
        "your-secret",
        "your-token",
    }
)
ENV_REFERENCE_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\Z")
HTTP_HEADER_REFERENCE_RE = re.compile(
    r"X-[A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,}\Z",
    re.IGNORECASE,
)
TEST_PLACEHOLDER_RE = re.compile(
    r"(?:test-only|actor-test|fixture|mock|dummy)-[A-Za-z0-9._-]+\Z",
    re.IGNORECASE,
)
SHELL_PLACEHOLDER_RE = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*"
    r"(?::(?P<shell_operator>[?+\-=])(?P<shell_fallback>[^{}\r\n]{0,160}))?\}\Z"
)
SHELL_PLACEHOLDER_INNER_RE = re.compile(
    r"[A-Z_][A-Z0-9_]*"
    r":(?P<shell_operator>[?+\-=])(?P<shell_fallback>[^{}\r\n]{0,160})\Z"
)
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_.:-]{1,80}>\Z")
TEMPLATE_PLACEHOLDER_RE = re.compile(r"=?\{\{[^{}\r\n]{1,256}\}\}\Z")
RUNTIME_SECRET_LOOKUP_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|getenv|self\.env\.get|config\.get|settings\.get|checks\.get|"
    r"load_secret|_secret_file)"
    r"\(\s*(?:[\"'][A-Za-z_][A-Za-z0-9_]*[\"']|"
    r"[A-Za-z_][A-Za-z0-9_.]{0,127})"
    r"(?:\s*,\s*(?P<runtime_fallback>[^()]*)\s*)?\)\Z"
)
RUNTIME_SECRET_LOOKUP_PREFIX_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|getenv|self\.env\.get|config\.get|settings\.get|checks\.get|"
    r"load_secret|_secret_file)"
    r"\(\s*(?:[\"'][A-Za-z_][A-Za-z0-9_]*[\"']|"
    r"[A-Za-z_][A-Za-z0-9_.]{0,127})\Z"
)
RUNTIME_SECRET_LITERAL_DEFAULT_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|getenv|self\.env\.get|config\.get|settings\.get|checks\.get|"
    r"load_secret|_secret_file)"
    r"\(\s*(?P<runtime_key>[\"']?[A-Za-z_][A-Za-z0-9_]*[\"']?|"
    r"[A-Za-z_][A-Za-z0-9_.]{0,127})\s*,\s*"
    r"(?:\"(?P<runtime_double_default>[^\"\r\n]*)\"|"
    r"'(?P<runtime_single_default>[^'\r\n]*)')\s*\)"
)
RUNTIME_SECRET_LOOKUP_NAMES = frozenset(
    {
        "os.environ.get",
        "os.getenv",
        "getenv",
        "self.env.get",
        "config.get",
        "settings.get",
        "checks.get",
        "load_secret",
        "_secret_file",
    }
)
RUNTIME_SECRET_FILE_LOOKUP_RE = re.compile(
    r"\$\$?\(cat (?:/run/secrets|deploy/secrets)/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\)\Z"
)
PROCESS_ENV_LOOKUP_RE = re.compile(
    r"process\.env\.[A-Za-z_][A-Za-z0-9_]*\Z"
)
ENV_MAPPING_LOOKUP_RE = re.compile(
    r"(?:self\.)?env\[[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\]\Z"
)
SOURCE_CALL_EXPRESSION_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.]*\([A-Za-z_][A-Za-z0-9_.]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_.]*)*\)?\Z"
)
PYTHON_SECRET_FILE_LOOKUP_RE = re.compile(
    r"Path\([A-Za-z_][A-Za-z0-9_.]*\)\.read_text\(encoding=[\"']utf-8[\"']\)\.strip\(\)\Z"
)


class ReleaseBuildError(RuntimeError):
    """Raised when a source tree cannot be packaged safely."""


@dataclass(frozen=True)
class ReleaseFile:
    path: str
    content: bytes
    mode: int
    sha256: str

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class BuildResult:
    archive: Path
    sha256_sidecar: Path
    inventory: Path
    archive_sha256: str
    archive_size: int
    file_count: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_generated_env(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(".generated.env") or lowered.endswith(".env.generated")


def _is_env_file(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == ".env"
        or lowered.startswith(".env.")
        or lowered.endswith(".env")
        or ".env." in lowered
    )


def _is_example_env(name: str) -> bool:
    lowered = name.lower()
    markers = ("example", "sample", "template")
    return _is_env_file(lowered) and any(
        lowered.endswith(f".{marker}")
        or lowered.endswith(f".{marker}.env")
        or f".{marker}.env." in lowered
        for marker in markers
    )


def _is_existing_archive(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _is_root_file_allowed(path: Path) -> bool:
    return path.name in ROOT_FILES or path.suffix.lower() == ".md"


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 for character in value)


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    frequencies: dict[str, int] = {}
    for character in value:
        frequencies[character] = frequencies.get(character, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in frequencies.values()
    )


def _looks_like_real_secret(value: str) -> bool:
    raw_candidate = value.strip()
    if RUNTIME_SECRET_LOOKUP_PREFIX_RE.fullmatch(raw_candidate):
        return False
    candidate = raw_candidate.strip("\"'")
    lowered = candidate.lower()
    if not candidate or lowered in SAFE_PLACEHOLDER_VALUES:
        return False
    if (
        ENV_REFERENCE_RE.fullmatch(candidate)
        or HTTP_HEADER_REFERENCE_RE.fullmatch(candidate)
        or TEST_PLACEHOLDER_RE.fullmatch(candidate)
    ):
        return False
    parsed_candidate = urlsplit(candidate)
    if parsed_candidate.scheme.casefold() in {"http", "https"}:
        return False
    shell_lookup = SHELL_PLACEHOLDER_RE.fullmatch(candidate)
    if shell_lookup:
        if shell_lookup.group("shell_operator") == "?":
            return False
        fallback = shell_lookup.group("shell_fallback")
        return bool(fallback and _looks_like_real_secret(fallback))
    shell_inner = SHELL_PLACEHOLDER_INNER_RE.fullmatch(candidate)
    if shell_inner:
        if shell_inner.group("shell_operator") == "?":
            return False
        fallback = shell_inner.group("shell_fallback")
        return bool(fallback and _looks_like_real_secret(fallback))
    runtime_lookup = RUNTIME_SECRET_LOOKUP_RE.fullmatch(candidate)
    if runtime_lookup:
        fallback = runtime_lookup.group("runtime_fallback")
        return bool(fallback and _looks_like_real_secret(fallback))
    # The assignment scanner intentionally stops at commas. A lookup with a
    # default may therefore arrive here as ``os.getenv("NAME"``; its literal
    # default is inspected separately over the complete source line below.
    if RUNTIME_SECRET_LOOKUP_PREFIX_RE.fullmatch(candidate):
        return False
    if (
        ANGLE_PLACEHOLDER_RE.fullmatch(candidate)
        or TEMPLATE_PLACEHOLDER_RE.fullmatch(candidate)
        or RUNTIME_SECRET_FILE_LOOKUP_RE.fullmatch(candidate)
        or PROCESS_ENV_LOOKUP_RE.fullmatch(candidate)
        or ENV_MAPPING_LOOKUP_RE.fullmatch(candidate)
        or SOURCE_CALL_EXPRESSION_RE.fullmatch(candidate)
        or PYTHON_SECRET_FILE_LOOKUP_RE.fullmatch(candidate)
    ):
        return False
    return len(candidate) >= 24 and _entropy(candidate) >= 3.5


def _looks_like_literal_secret_value(value: str) -> bool:
    """Apply a tighter token shape when correlating unrelated call arguments."""

    candidate = str(value or "").strip().strip("\"'")
    if not _looks_like_real_secret(candidate):
        return False
    if (
        not candidate
        or any(character.isspace() for character in candidate)
        or SECRET_NAME_RE.search(candidate)
        or candidate.startswith(("$", "--", "/"))
        or ("_" in candidate and candidate.isidentifier())
        or "=" in candidate
        or not any(character.isupper() for character in candidate)
        or not any(character.islower() for character in candidate)
        or not any(character.isdigit() for character in candidate)
    ):
        return False
    return True


def _python_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _python_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _python_import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "os":
                    aliases[item.asname or item.name] = "os"
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for item in node.names:
                if item.name == "getenv":
                    aliases[item.asname or item.name] = "os.getenv"
    return aliases


def _canonical_python_call_name(node: ast.AST, aliases: dict[str, str]) -> str:
    raw = _python_call_name(node)
    head, separator, tail = raw.partition(".")
    mapped = aliases.get(head)
    if not mapped:
        return raw
    return f"{mapped}.{tail}" if separator else mapped


def _constant_python_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_python_string(node.left)
        right = _constant_python_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                value = _constant_python_string(part.value)
                if value is None or part.format_spec is not None:
                    return None
                if part.conversion not in {-1, ord("s")}:
                    return None
                parts.append(value)
                continue
            value = _constant_python_string(part)
            if value is None:
                return None
            parts.append(value)
        return "".join(parts)
    return None


def _python_expression_strings(node: ast.AST) -> list[str]:
    """Return statically recoverable strings from every expression subtree.

    Looking at the complete call subtree deliberately makes the credential
    check independent of how a valid Python call is spelled.  It therefore
    covers literal ``*args``, assigned function aliases and ``getattr`` calls
    without trying to emulate Python name binding.
    """

    values: list[str] = []
    for child in ast.walk(node):
        value = _constant_python_string(child)
        if value is not None:
            values.append(value)
    return values


_PYTHON_UNRESOLVED = object()


@dataclass(frozen=True)
class _PythonStaticAlternatives:
    values: tuple[object, ...]


@dataclass(frozen=True)
class _PythonStaticParameter:
    index: int


@dataclass(frozen=True)
class _PythonStaticCallable:
    return_value: object
    parameter_names: tuple[str, ...] = ()
    positional_count: int = 0
    defaults: tuple[object, ...] = ()


@dataclass(frozen=True)
class _PythonStaticClass:
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class _PythonStaticInstance:
    fields: tuple[tuple[str, object], ...]


def _python_static_options(value: object) -> tuple[object, ...]:
    if isinstance(value, _PythonStaticAlternatives):
        return value.values
    return (value,)


def _python_static_choice(values: Iterable[object]) -> object:
    unique: list[object] = []
    for value in values:
        if value is _PYTHON_UNRESOLVED:
            continue
        if not any(value == existing for existing in unique):
            unique.append(value)
    if not unique:
        return _PYTHON_UNRESOLVED
    if len(unique) == 1:
        return unique[0]
    return _PythonStaticAlternatives(tuple(unique))


def _python_static_add(left: object, right: object) -> object:
    results: list[object] = []
    for left_value in _python_static_options(left):
        for right_value in _python_static_options(right):
            if isinstance(left_value, str) and isinstance(right_value, str):
                results.append(left_value + right_value)
            elif isinstance(left_value, tuple) and isinstance(right_value, tuple):
                results.append(left_value + right_value)
    return _python_static_choice(results)


def _python_static_percent(left: object, right: object) -> object:
    results: list[object] = []
    for left_value in _python_static_options(left):
        for right_value in _python_static_options(right):
            if not isinstance(left_value, str):
                continue
            try:
                rendered = left_value % right_value
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(rendered, str):
                results.append(rendered)
    return _python_static_choice(results)


def _substitute_python_static_parameters(
    value: object,
    arguments: tuple[object, ...],
) -> object:
    if isinstance(value, _PythonStaticParameter):
        if value.index >= len(arguments):
            return _PYTHON_UNRESOLVED
        return arguments[value.index]
    if isinstance(value, _PythonStaticAlternatives):
        return _python_static_choice(
            _substitute_python_static_parameters(alternative, arguments)
            for alternative in value.values
        )
    if isinstance(value, tuple):
        resolved = tuple(
            _substitute_python_static_parameters(item, arguments) for item in value
        )
        if any(item is _PYTHON_UNRESOLVED for item in resolved):
            return _PYTHON_UNRESOLVED
        return resolved
    if isinstance(value, dict):
        resolved_mapping: dict[str, object] = {}
        for key, item in value.items():
            resolved_item = _substitute_python_static_parameters(item, arguments)
            if resolved_item is _PYTHON_UNRESOLVED:
                return _PYTHON_UNRESOLVED
            resolved_mapping[key] = resolved_item
        return resolved_mapping
    return value


def _invoke_python_static_callable(
    callable_value: _PythonStaticCallable,
    node: ast.Call,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> object:
    if any(isinstance(argument, ast.Starred) for argument in node.args):
        return _PYTHON_UNRESOLVED
    if any(keyword.arg is None for keyword in node.keywords):
        return _PYTHON_UNRESOLVED
    if len(node.args) > callable_value.positional_count:
        return _PYTHON_UNRESOLVED

    arguments = list(callable_value.defaults)
    for index, argument in enumerate(node.args):
        arguments[index] = _python_static_value(argument, symbols, functions)
    for keyword in node.keywords:
        if keyword.arg not in callable_value.parameter_names:
            return _PYTHON_UNRESOLVED
        index = callable_value.parameter_names.index(keyword.arg)
        if index < len(node.args):
            return _PYTHON_UNRESOLVED
        arguments[index] = _python_static_value(keyword.value, symbols, functions)
    if any(argument is _PYTHON_UNRESOLVED for argument in arguments):
        return _PYTHON_UNRESOLVED
    return _substitute_python_static_parameters(
        callable_value.return_value,
        tuple(arguments),
    )


def _construct_python_static_instance(
    class_value: _PythonStaticClass,
    node: ast.Call,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> object:
    if any(isinstance(argument, ast.Starred) for argument in node.args):
        return _PYTHON_UNRESOLVED
    if any(keyword.arg is None for keyword in node.keywords):
        return _PYTHON_UNRESOLVED
    if len(node.args) > len(class_value.fields):
        return _PYTHON_UNRESOLVED

    fields = dict(class_value.fields)
    field_names = tuple(fields)
    for field_name, argument in zip(field_names, node.args, strict=False):
        fields[field_name] = _python_static_value(argument, symbols, functions)
    for keyword in node.keywords:
        if keyword.arg not in fields:
            return _PYTHON_UNRESOLVED
        fields[keyword.arg] = _python_static_value(keyword.value, symbols, functions)
    if any(value is _PYTHON_UNRESOLVED for value in fields.values()):
        return _PYTHON_UNRESOLVED
    return _PythonStaticInstance(tuple(fields.items()))


def _invoke_python_static_value(
    value: object,
    node: ast.Call,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> object:
    results: list[object] = []
    for option in _python_static_options(value):
        if isinstance(option, _PythonStaticCallable):
            results.append(
                _invoke_python_static_callable(option, node, symbols, functions)
            )
        elif isinstance(option, _PythonStaticClass):
            results.append(
                _construct_python_static_instance(option, node, symbols, functions)
            )
    return _python_static_choice(results)


def _python_static_value(
    node: ast.AST,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> object:
    """Evaluate a deliberately small, side-effect-free Python constant subset."""

    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (str, int, float, bool)):
            return node.value
        return _PYTHON_UNRESOLVED
    if isinstance(node, ast.Name):
        name = _python_call_name(node)
        if name in symbols:
            return symbols[name]
        if name in functions:
            return functions[name]
        return _PYTHON_UNRESOLVED
    if isinstance(node, ast.Attribute):
        name = _python_call_name(node)
        if name in symbols:
            return symbols[name]
        if name in functions:
            return functions[name]
        receiver = _python_static_value(node.value, symbols, functions)
        values: list[object] = []
        for receiver_value in _python_static_options(receiver):
            if isinstance(
                receiver_value,
                (_PythonStaticClass, _PythonStaticInstance),
            ):
                fields = dict(receiver_value.fields)
                if node.attr in fields:
                    values.append(fields[node.attr])
        return _python_static_choice(values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _python_static_value(node.left, symbols, functions)
        right = _python_static_value(node.right, symbols, functions)
        return _python_static_add(left, right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        left = _python_static_value(node.left, symbols, functions)
        right = _python_static_value(node.right, symbols, functions)
        return _python_static_percent(left, right)
    if isinstance(node, ast.IfExp):
        condition = _python_static_value(node.test, symbols, functions)
        if isinstance(condition, bool):
            branch = node.body if condition else node.orelse
            return _python_static_value(branch, symbols, functions)
        return _python_static_choice(
            (
                _python_static_value(node.body, symbols, functions),
                _python_static_value(node.orelse, symbols, functions),
            )
        )
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                value = _python_static_value(part.value, symbols, functions)
                if value is _PYTHON_UNRESOLVED:
                    return _PYTHON_UNRESOLVED
                if part.conversion == ord("r"):
                    rendered = repr(value)
                elif part.conversion == ord("a"):
                    rendered = ascii(value)
                else:
                    rendered = str(value)
                if part.format_spec is not None:
                    specification = _python_static_value(
                        part.format_spec,
                        symbols,
                        functions,
                    )
                    if not isinstance(specification, str):
                        return _PYTHON_UNRESOLVED
                    try:
                        rendered = format(value, specification)
                    except (TypeError, ValueError):
                        return _PYTHON_UNRESOLVED
                parts.append(rendered)
                continue
            value = _python_static_value(part, symbols, functions)
            if not isinstance(value, str):
                return _PYTHON_UNRESOLVED
            parts.append(value)
        return "".join(parts)
    if isinstance(node, (ast.Tuple, ast.List)):
        sequence_values = tuple(
            _python_static_value(item, symbols, functions) for item in node.elts
        )
        if any(value is _PYTHON_UNRESOLVED for value in sequence_values):
            return _PYTHON_UNRESOLVED
        return sequence_values
    if isinstance(node, ast.Dict):
        mapping_values: dict[str, object] = {}
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            if key_node is None:
                expanded = _python_static_value(value_node, symbols, functions)
                if not isinstance(expanded, dict):
                    return _PYTHON_UNRESOLVED
                mapping_values.update(expanded)
                continue
            key = _python_static_value(key_node, symbols, functions)
            value = _python_static_value(value_node, symbols, functions)
            if not isinstance(key, str) or value is _PYTHON_UNRESOLVED:
                return _PYTHON_UNRESOLVED
            mapping_values[key] = value
        return mapping_values
    if isinstance(node, ast.Subscript):
        container = _python_static_value(node.value, symbols, functions)
        key = _python_static_value(node.slice, symbols, functions)
        try:
            if isinstance(container, dict) and isinstance(key, str):
                return container.get(key, _PYTHON_UNRESOLVED)
            if isinstance(container, tuple) and isinstance(key, int):
                return container[key]
        except IndexError:
            return _PYTHON_UNRESOLVED
        return _PYTHON_UNRESOLVED
    if isinstance(node, ast.Call):
        function_name = _python_call_name(node.func)
        callable_value = functions.get(
            function_name,
            symbols.get(function_name, _PYTHON_UNRESOLVED),
        )
        invoked = _invoke_python_static_value(
            callable_value,
            node,
            symbols,
            functions,
        )
        if invoked is not _PYTHON_UNRESOLVED:
            return invoked
        if not isinstance(node.func, ast.Attribute):
            return _PYTHON_UNRESOLVED
        receiver = _python_static_value(node.func.value, symbols, functions)
        if node.func.attr in {"upper", "lower", "casefold", "strip"}:
            if node.args or node.keywords:
                return _PYTHON_UNRESOLVED
            normalized_values: list[object] = []
            for value in _python_static_options(receiver):
                if isinstance(value, str):
                    normalized_values.append(getattr(value, node.func.attr)())
            return _python_static_choice(normalized_values)
        if node.func.attr == "join" and isinstance(receiver, str):
            if len(node.args) != 1 or node.keywords:
                return _PYTHON_UNRESOLVED
            items = _python_static_value(node.args[0], symbols, functions)
            if isinstance(items, tuple) and all(isinstance(item, str) for item in items):
                return receiver.join(items)
        if node.func.attr == "format" and isinstance(receiver, str):
            arguments: list[object] = []
            keywords: dict[str, object] = {}
            for argument in node.args:
                value = _python_static_value(argument, symbols, functions)
                if value is _PYTHON_UNRESOLVED:
                    return _PYTHON_UNRESOLVED
                arguments.append(value)
            for keyword in node.keywords:
                if keyword.arg is None:
                    return _PYTHON_UNRESOLVED
                value = _python_static_value(keyword.value, symbols, functions)
                if value is _PYTHON_UNRESOLVED:
                    return _PYTHON_UNRESOLVED
                keywords[keyword.arg] = value
            try:
                return receiver.format(*arguments, **keywords)
            except (IndexError, KeyError, TypeError, ValueError):
                return _PYTHON_UNRESOLVED
        if node.func.attr == "replace":
            if len(node.args) not in {2, 3} or node.keywords:
                return _PYTHON_UNRESOLVED
            argument_values = [
                _python_static_value(argument, symbols, functions)
                for argument in node.args
            ]
            replacements: list[object] = []
            for receiver_value in _python_static_options(receiver):
                for old_value in _python_static_options(argument_values[0]):
                    for new_value in _python_static_options(argument_values[1]):
                        counts = (
                            _python_static_options(argument_values[2])
                            if len(argument_values) == 3
                            else (-1,)
                        )
                        for count in counts:
                            if not (
                                isinstance(receiver_value, str)
                                and isinstance(old_value, str)
                                and isinstance(new_value, str)
                                and isinstance(count, int)
                            ):
                                continue
                            replacements.append(
                                receiver_value.replace(old_value, new_value, count)
                            )
            return _python_static_choice(replacements)
    if isinstance(node, ast.Lambda):
        return _python_static_callable(
            node.args,
            (ast.Return(value=node.body),),
            symbols,
            functions,
        )
    return _PYTHON_UNRESOLVED


def _python_static_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, _PythonStaticParameter):
        return []
    if isinstance(value, _PythonStaticAlternatives):
        return [
            item
            for alternative in value.values
            for item in _python_static_strings(alternative)
        ]
    if isinstance(value, _PythonStaticCallable):
        return [
            item
            for callable_item in (value.return_value, *value.defaults)
            for item in _python_static_strings(callable_item)
        ]
    if isinstance(value, (_PythonStaticClass, _PythonStaticInstance)):
        return [
            item
            for name, field_value in value.fields
            for item in (name, *_python_static_strings(field_value))
        ]
    if isinstance(value, tuple):
        return [item for value_item in value for item in _python_static_strings(value_item)]
    if isinstance(value, dict):
        return [
            item
            for key, value_item in value.items()
            for item in (key, *_python_static_strings(value_item))
        ]
    return []


def _bind_python_static_target(
    target: ast.AST,
    value: object,
    symbols: dict[str, object],
    *,
    prefix: str = "",
) -> bool:
    if value is _PYTHON_UNRESOLVED:
        return False
    if isinstance(target, (ast.Name, ast.Attribute)):
        name = _python_call_name(target)
        if not name:
            return False
        name = f"{prefix}.{name}" if prefix else name
        previous = symbols.get(name, _PYTHON_UNRESOLVED)
        combined = _python_static_choice(
            (*_python_static_options(previous), *_python_static_options(value))
        )
        if combined == previous:
            return False
        symbols[name] = combined
        return True
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, tuple):
        if len(target.elts) != len(value):
            return False
        return any(
            _bind_python_static_target(item, item_value, symbols, prefix=prefix)
            for item, item_value in zip(target.elts, value, strict=True)
        )
    return False


def _set_python_static_target(
    target: ast.AST,
    value: object,
    symbols: dict[str, object],
) -> bool:
    if value is _PYTHON_UNRESOLVED:
        return False
    if isinstance(target, (ast.Name, ast.Attribute)):
        name = _python_call_name(target)
        if not name:
            return False
        changed = symbols.get(name, _PYTHON_UNRESOLVED) != value
        symbols[name] = value
        return changed
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, tuple):
        if len(target.elts) != len(value):
            return False
        changed = False
        for item, item_value in zip(target.elts, value, strict=True):
            changed = _set_python_static_target(item, item_value, symbols) or changed
        return changed
    return False


def _python_static_parameter_spec(
    arguments: ast.arguments,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> tuple[tuple[str, ...], int, tuple[object, ...]] | None:
    if arguments.vararg is not None or arguments.kwarg is not None:
        return None
    positional = (*arguments.posonlyargs, *arguments.args)
    parameters = (*positional, *arguments.kwonlyargs)
    parameter_names = tuple(parameter.arg for parameter in parameters)
    defaults: list[object] = [_PYTHON_UNRESOLVED] * len(parameters)
    first_positional_default = len(positional) - len(arguments.defaults)
    for offset, default_node in enumerate(arguments.defaults):
        defaults[first_positional_default + offset] = _python_static_value(
            default_node,
            symbols,
            functions,
        )
    for offset, keyword_default_node in enumerate(arguments.kw_defaults):
        if keyword_default_node is not None:
            defaults[len(positional) + offset] = _python_static_value(
                keyword_default_node,
                symbols,
                functions,
            )
    return parameter_names, len(positional), tuple(defaults)


def _python_static_callable(
    arguments: ast.arguments,
    body: tuple[ast.stmt, ...] | list[ast.stmt],
    symbols: dict[str, object],
    functions: dict[str, object],
) -> object:
    specification = _python_static_parameter_spec(arguments, symbols, functions)
    if specification is None:
        return _PYTHON_UNRESOLVED
    parameter_names, positional_count, defaults = specification
    local_symbols = dict(symbols)
    for index, parameter_name in enumerate(parameter_names):
        local_symbols[parameter_name] = _PythonStaticParameter(index)

    statements = [
        statement
        for statement in body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    for statement in statements:
        if isinstance(statement, ast.Return):
            return_value = (
                None
                if statement.value is None
                else _python_static_value(statement.value, local_symbols, functions)
            )
            if return_value is _PYTHON_UNRESOLVED:
                return _PYTHON_UNRESOLVED
            return _PythonStaticCallable(
                return_value,
                parameter_names,
                positional_count,
                defaults,
            )
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value_node = statement.value
            if value_node is None:
                return _PYTHON_UNRESOLVED
            if isinstance(statement, ast.AugAssign):
                left = _python_static_value(
                    statement.target,
                    local_symbols,
                    functions,
                )
                right = _python_static_value(value_node, local_symbols, functions)
                value = (
                    _python_static_add(left, right)
                    if isinstance(statement.op, ast.Add)
                    else _PYTHON_UNRESOLVED
                )
            else:
                value = _python_static_value(value_node, local_symbols, functions)
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if value is _PYTHON_UNRESOLVED:
                return _PYTHON_UNRESOLVED
            for target in targets:
                if not _set_python_static_target(target, value, local_symbols):
                    target_names = _python_assignment_targets(target)
                    if target_names and all(
                        local_symbols.get(name, _PYTHON_UNRESOLVED) == value
                        for name in target_names
                    ):
                        continue
                    return _PYTHON_UNRESOLVED
            continue
        return _PYTHON_UNRESOLVED
    return _PYTHON_UNRESOLVED


def _python_static_class(
    node: ast.ClassDef,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> _PythonStaticClass:
    fields: dict[str, object] = {}
    for statement in node.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        if statement.value is None:
            continue
        value = _python_static_value(statement.value, symbols, functions)
        if value is _PYTHON_UNRESOLVED:
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        for target in targets:
            if isinstance(target, ast.Name):
                fields[target.id] = value
    return _PythonStaticClass(tuple(fields.items()))


def _python_static_bindings(
    tree: ast.AST,
) -> tuple[dict[str, object], dict[str, object]]:
    symbols: dict[str, object] = {}
    functions: dict[str, object] = {}
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr))
    ]
    function_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    loop_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.AsyncFor))
        and any(
            isinstance(child, ast.Call)
            and _python_call_name(child.func) in RUNTIME_SECRET_LOOKUP_NAMES
            for statement in node.body
            for child in ast.walk(statement)
        )
    ]
    class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    class_assignments = [
        (class_node.name, statement)
        for class_node in ast.walk(tree)
        if isinstance(class_node, ast.ClassDef)
        for statement in class_node.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
    ]
    class_function_nodes = [
        (class_node.name, statement)
        for class_node in ast.walk(tree)
        if isinstance(class_node, ast.ClassDef)
        for statement in class_node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for _ in range(
        len(assignments) + len(function_nodes) + len(loop_nodes) + len(class_nodes) + 2
    ):
        changed = False
        for node in assignments:
            value_node = node.value
            if value_node is None:
                continue
            if isinstance(node, ast.AugAssign):
                left = _python_static_value(node.target, symbols, functions)
                right = _python_static_value(value_node, symbols, functions)
                value = (
                    _python_static_add(left, right)
                    if isinstance(node.op, ast.Add)
                    else _PYTHON_UNRESOLVED
                )
            else:
                value = _python_static_value(value_node, symbols, functions)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                changed = _bind_python_static_target(target, value, symbols) or changed
        for loop_node in loop_nodes:
            iterable = _python_static_value(loop_node.iter, symbols, functions)
            for iterable_option in _python_static_options(iterable):
                if not isinstance(iterable_option, tuple):
                    continue
                for item in iterable_option:
                    changed = (
                        _bind_python_static_target(loop_node.target, item, symbols)
                        or changed
                    )
        for class_name, class_assignment in class_assignments:
            if class_assignment.value is None:
                continue
            value = _python_static_value(class_assignment.value, symbols, functions)
            targets = (
                class_assignment.targets
                if isinstance(class_assignment, ast.Assign)
                else [class_assignment.target]
            )
            for target in targets:
                changed = (
                    _bind_python_static_target(
                        target,
                        value,
                        symbols,
                        prefix=class_name,
                    )
                    or changed
                )
        for class_node in class_nodes:
            value = _python_static_class(class_node, symbols, functions)
            previous = symbols.get(class_node.name, _PYTHON_UNRESOLVED)
            if value != previous:
                symbols[class_node.name] = value
                changed = True
        for function_node in function_nodes:
            value = _python_static_callable(
                function_node.args,
                function_node.body,
                symbols,
                functions,
            )
            if value is not _PYTHON_UNRESOLVED:
                previous = functions.get(function_node.name, _PYTHON_UNRESOLVED)
                combined = _python_static_choice(
                    (*_python_static_options(previous), *_python_static_options(value))
                )
                if combined != previous:
                    functions[function_node.name] = combined
                    changed = True
        for class_name, function_node in class_function_nodes:
            value = _python_static_callable(
                function_node.args,
                function_node.body,
                symbols,
                functions,
            )
            if value is _PYTHON_UNRESOLVED:
                continue
            name = f"{class_name}.{function_node.name}"
            previous = functions.get(name, _PYTHON_UNRESOLVED)
            combined = _python_static_choice(
                (*_python_static_options(previous), *_python_static_options(value))
            )
            if combined != previous:
                functions[name] = combined
                changed = True
        if not changed:
            break
    return symbols, functions


def _python_resolved_expression_strings(
    node: ast.AST,
    symbols: dict[str, object],
    functions: dict[str, object],
) -> list[str]:
    values = _python_expression_strings(node)
    for child in ast.walk(node):
        values.extend(
            _python_static_strings(_python_static_value(child, symbols, functions))
        )
    return values


def _python_call_keywords(node: ast.Call) -> tuple[dict[str, ast.AST], bool]:
    values: dict[str, ast.AST] = {}
    opaque = False
    for keyword in node.keywords:
        if keyword.arg is not None:
            values[keyword.arg] = keyword.value
            continue
        if not isinstance(keyword.value, ast.Dict):
            opaque = True
            continue
        for key_node, value_node in zip(
            keyword.value.keys,
            keyword.value.values,
            strict=True,
        ):
            key = _constant_python_string(key_node) if key_node is not None else None
            if key is None:
                opaque = True
                continue
            values[key] = value_node
    return values, opaque


def _python_runtime_key_and_default(
    node: ast.Call,
) -> tuple[ast.AST | None, ast.AST | None, bool]:
    keywords, opaque = _python_call_keywords(node)
    key_node = node.args[0] if node.args else (keywords.get("key") or keywords.get("name"))
    default_node = (
        node.args[1]
        if len(node.args) >= 2
        else (keywords.get("default") or keywords.get("fallback"))
    )
    return key_node, default_node, opaque


def _python_assignment_targets(
    node: ast.AST,
    symbols: dict[str, object] | None = None,
    functions: dict[str, object] | None = None,
) -> list[str]:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return [_python_call_name(node)]
    if isinstance(node, ast.Subscript):
        container = _python_call_name(node.value)
        keys = (
            _python_static_strings(
                _python_static_value(node.slice, symbols, functions or {})
            )
            if symbols is not None
            else []
        )
        constant_key = _constant_python_string(node.slice)
        if constant_key:
            keys.append(constant_key)
        if keys:
            return [
                name
                for key in keys
                for name in (key, f"{container}.{key}" if container else key)
            ]
        return [container] if container else []
    if isinstance(node, (ast.Tuple, ast.List)):
        return [
            name
            for item in node.elts
            for name in _python_assignment_targets(item, symbols, functions)
        ]
    return []


def _python_sensitive_assignments(
    tree: ast.AST,
    symbols: dict[str, object] | None = None,
    functions: dict[str, object] | None = None,
) -> list[tuple[list[str], ast.AST]]:
    assignments: list[tuple[list[str], ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [
                name
                for target in node.targets
                for name in _python_assignment_targets(target, symbols, functions)
            ]
            assignments.append((targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append(
                (_python_assignment_targets(node.target, symbols, functions), node.value)
            )
        elif isinstance(node, ast.AugAssign):
            assignments.append(
                (_python_assignment_targets(node.target, symbols, functions), node.value)
            )
        elif isinstance(node, ast.NamedExpr):
            assignments.append(
                (_python_assignment_targets(node.target, symbols, functions), node.value)
            )
    return assignments


def _python_regex_declaration(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return _python_call_name(node.func) == "re.compile"
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts) and all(_python_regex_declaration(item) for item in node.elts)
    return False


def _safe_python_runtime_default(
    node: ast.AST,
    aliases: dict[str, str],
) -> bool:
    if isinstance(node, ast.Constant):
        if node.value is None:
            return True
        if isinstance(node.value, str):
            return not node.value or node.value.strip().casefold() in SAFE_PLACEHOLDER_VALUES
        return False
    if (
        isinstance(node, ast.Call)
        and _canonical_python_call_name(node.func, aliases) in RUNTIME_SECRET_LOOKUP_NAMES
    ):
        _, nested_default, opaque = _python_runtime_key_and_default(node)
        if opaque:
            return False
        if nested_default is None:
            return True
        return _safe_python_runtime_default(nested_default, aliases)
    return False


def _scan_python_runtime_secret_defaults(text: str, relative_path: str) -> None:
    if not relative_path.casefold().endswith(".py"):
        return
    try:
        tree = ast.parse(text, filename=relative_path)
    except SyntaxError:
        # General credential patterns below still scan snippets and templates.
        return
    aliases = _python_import_aliases(tree)
    symbols, functions = _python_static_bindings(tree)
    for name, value in symbols.items():
        if SECRET_NAME_RE.search(name) and any(
            _looks_like_real_secret(item) for item in _python_static_strings(value)
        ):
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )
    for targets, value in _python_sensitive_assignments(tree, symbols, functions):
        if not any(SECRET_NAME_RE.search(target) for target in targets):
            continue
        if _python_regex_declaration(value):
            continue
        resolved_strings = _python_static_strings(
            _python_static_value(value, symbols, functions)
        )
        if any(_looks_like_real_secret(item) for item in resolved_strings):
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )
        if not resolved_strings:
            for child in ast.walk(value):
                if (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                    and _looks_like_real_secret(child.value)
                ):
                    raise ReleaseBuildError(
                        f"high-entropy credential assignment found in {relative_path}"
                    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        expression_strings = _python_resolved_expression_strings(
            node,
            symbols,
            functions,
        )
        if (
            any(SECRET_NAME_RE.search(value) for value in expression_strings)
            and any(
                _looks_like_literal_secret_value(value)
                for value in expression_strings
            )
        ):
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )
        if _canonical_python_call_name(node.func, aliases) not in RUNTIME_SECRET_LOOKUP_NAMES:
            continue
        key_node, default_node, opaque = _python_runtime_key_and_default(node)
        if opaque:
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )
        key = _constant_python_string(key_node) if key_node is not None else None
        if default_node is None:
            continue
        sensitive_key = bool(key and SECRET_NAME_RE.search(key))
        constant_default = _constant_python_string(default_node)
        unsafe_computed_default = bool(
            constant_default is not None and _looks_like_real_secret(constant_default)
        )
        if (
            (sensitive_key and not _safe_python_runtime_default(default_node, aliases))
            or (key is None and unsafe_computed_default)
        ):
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )


def _scan_text_for_credentials(text: str, relative_path: str) -> None:
    _scan_python_runtime_secret_defaults(text, relative_path)
    if PEM_RE.search(text):
        raise ReleaseBuildError(f"certificate or private key material found in {relative_path}")
    for pattern in KNOWN_CREDENTIAL_RES:
        if pattern.search(text):
            raise ReleaseBuildError(f"credential material found in {relative_path}")
    for match in RUNTIME_SECRET_LITERAL_DEFAULT_RE.finditer(text):
        runtime_key = str(match.group("runtime_key") or "").strip("\"'")
        fallback = next(
            (
                value
                for value in (
                    match.group("runtime_double_default"),
                    match.group("runtime_single_default"),
                )
                if value is not None
            ),
            "",
        )
        if SECRET_NAME_RE.search(runtime_key) and _looks_like_real_secret(fallback):
            raise ReleaseBuildError(
                f"high-entropy credential assignment found in {relative_path}"
            )
    for match in SENSITIVE_ASSIGNMENT_RE.finditer(text):
        shell_value = match.group("shell")
        value = (
            f"${{{shell_value}}}"
            if shell_value is not None
            else next(
                (
                    group
                    for group in (
                        match.group("double"),
                        match.group("single"),
                        match.group("bare"),
                    )
                    if group is not None
                ),
                "",
            )
        )
        if (
            match.group("bare") is not None
            and match.group(0)[:1] in {"\"", "'"}
            and value.endswith(match.group(0)[0])
        ):
            value = value[:-1]
        if _looks_like_real_secret(value):
            raise ReleaseBuildError(f"high-entropy credential assignment found in {relative_path}")


def _safe_local_hyperlink(target: str, relative_path: str) -> bool:
    """Return whether a relative Word hyperlink stays inside the release root."""

    parsed = urlsplit(target)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or target.startswith(("/", "\\"))
        or "\\" in target
    ):
        return False

    decoded_path = unquote(parsed.path)
    if (
        not (decoded_path or parsed.fragment)
        or decoded_path.startswith(("/", "\\"))
        or "\\" in decoded_path
        or ":" in decoded_path
        or _has_control_characters(decoded_path)
    ):
        return False

    resolved_parts = list(PurePosixPath(relative_path).parent.parts)
    for part in PurePosixPath(decoded_path).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                return False
            resolved_parts.pop()
            continue
        resolved_parts.append(part)
    return bool(resolved_parts or parsed.fragment)


def _validate_external_relationships(payload: bytes, relative_path: str) -> None:
    try:
        relationships = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ReleaseBuildError(f"invalid Word relationship XML in {relative_path}") from exc
    for relationship in relationships:
        if relationship.attrib.get("TargetMode", "").casefold() != "external":
            continue
        relationship_type = relationship.attrib.get("Type", "")
        target = relationship.attrib.get("Target", "")
        parsed = urlsplit(target)
        is_hyperlink = relationship_type.casefold().endswith("/hyperlink")
        is_safe_https_hyperlink = (
            parsed.scheme.casefold() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not _has_control_characters(target)
            and not _has_control_characters(unquote(target))
        )
        is_safe_hyperlink = is_hyperlink and (
            is_safe_https_hyperlink or _safe_local_hyperlink(target, relative_path)
        )
        if not is_safe_hyperlink:
            raise ReleaseBuildError(f"unsafe external Word relationship found in {relative_path}")


def _validate_docx(content: bytes, relative_path: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            member_names = document.namelist()
            names = set(member_names)
            if len(names) != len(member_names):
                raise ReleaseBuildError(f"duplicate Word package member in {relative_path}")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ReleaseBuildError(f"invalid Word document structure in {relative_path}")

            expanded_size = 0
            for entry in document.infolist():
                member = entry.filename
                member_path = PurePosixPath(member)
                if (
                    "\\" in member
                    or member.startswith("/")
                    or ".." in member_path.parts
                    or _has_control_characters(member)
                ):
                    raise ReleaseBuildError(f"unsafe Word package member in {relative_path}")
                unix_mode = (entry.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise ReleaseBuildError(f"symlink found inside Word document {relative_path}")
                if entry.flag_bits & 0x1:
                    raise ReleaseBuildError(f"encrypted Word package member in {relative_path}")
                lowered = member.lower()
                if (
                    "vbaproject" in lowered
                    or lowered.startswith("word/activex/")
                    or lowered.startswith("word/embeddings/")
                ):
                    raise ReleaseBuildError(f"active or embedded content found in {relative_path}")
                expanded_size += entry.file_size
                if expanded_size > MAX_DOCX_EXPANDED_BYTES:
                    raise ReleaseBuildError(f"expanded Word document is too large: {relative_path}")
                if lowered.endswith((".xml", ".rels")):
                    payload = document.read(entry)
                    if lowered.endswith(".rels"):
                        _validate_external_relationships(payload, relative_path)
                    _scan_text_for_credentials(
                        payload.decode("utf-8", errors="replace"), relative_path
                    )
            bad_member = document.testzip()
            if bad_member:
                raise ReleaseBuildError(
                    f"corrupt Word package member {bad_member!r} in {relative_path}"
                )
    except (zipfile.BadZipFile, OSError) as exc:
        raise ReleaseBuildError(f"invalid Word document {relative_path}: {exc}") from exc


def _validate_content(content: bytes, relative_path: str) -> None:
    suffix = Path(relative_path).suffix.lower()
    if relative_path == SAFE_DOCX_PATH:
        _validate_docx(content, relative_path)
        return
    if suffix == ".docx":
        raise ReleaseBuildError(
            f"unexpected Word document {relative_path}; only {SAFE_DOCX_PATH} is allowed"
        )
    if suffix in IMAGE_SIGNATURES:
        signatures = IMAGE_SIGNATURES[suffix]
        if not any(content.startswith(signature) for signature in signatures):
            raise ReleaseBuildError(f"invalid image signature in {relative_path}")
        if suffix == ".webp" and content[8:12] != b"WEBP":
            raise ReleaseBuildError(f"invalid WebP signature in {relative_path}")
        return
    if b"\x00" in content:
        raise ReleaseBuildError(f"unsupported binary file in release source: {relative_path}")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseBuildError(f"non-UTF-8 file in release source: {relative_path}") from exc
    _scan_text_for_credentials(text, relative_path)


def _relative_posix(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or ".." in PurePosixPath(relative).parts
        or _has_control_characters(relative)
    ):
        raise ReleaseBuildError(f"unsafe release path: {relative!r}")
    return relative


def _classify_path(path: Path, relative_path: str) -> str:
    """Return ``include``, ``exclude`` or raise for unsafe path names."""

    name = path.name
    lowered = name.lower()
    if name.startswith("~$"):
        return "exclude"
    if _is_generated_env(name):
        return "exclude"
    if _is_env_file(name) and not _is_example_env(name):
        raise ReleaseBuildError(f"private environment file found: {relative_path}")
    if lowered.endswith(".pdf") or _is_existing_archive(name):
        return "exclude"
    if path.suffix.lower() in RUNTIME_SUFFIXES:
        return "exclude"
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        raise ReleaseBuildError(f"private key or certificate file found: {relative_path}")
    if SECRET_NAME_RE.search(name):
        raise ReleaseBuildError(f"secret-looking file name found: {relative_path}")
    return "include"


def _read_release_file(path: Path, root: Path) -> ReleaseFile | None:
    relative_path = _relative_posix(path, root)
    if _classify_path(path, relative_path) == "exclude":
        return None
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot inspect {relative_path}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReleaseBuildError(f"unsupported filesystem object: {relative_path}")
    if before.st_size > MAX_FILE_BYTES:
        raise ReleaseBuildError(f"release source file exceeds size limit: {relative_path}")
    try:
        content = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot read {relative_path}: {exc}") from exc
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise ReleaseBuildError(f"release source changed while being read: {relative_path}")
    if len(content) != before.st_size:
        raise ReleaseBuildError(f"release source changed while being read: {relative_path}")
    _validate_content(content, relative_path)
    mode = 0o755 if path.suffix.lower() == ".sh" else 0o644
    return ReleaseFile(relative_path, content, mode, _sha256(content))


def _walk_directory(
    directory: Path,
    root: Path,
    ignored_paths: set[Path],
) -> Iterable[ReleaseFile]:
    try:
        entries = sorted(os.scandir(directory), key=lambda item: item.name)
    except OSError as exc:
        relative = _relative_posix(directory, root)
        raise ReleaseBuildError(f"cannot scan {relative}: {exc}") from exc

    for entry in entries:
        path = Path(entry.path)
        relative_path = _relative_posix(path, root)
        resolved = path.resolve(strict=False)
        if resolved in ignored_paths:
            continue
        if entry.is_symlink():
            raise ReleaseBuildError(f"symlink found in release source: {relative_path}")
        if entry.is_dir(follow_symlinks=False):
            lowered = entry.name.casefold()
            if _is_excluded_directory_name(entry.name) or lowered in PRIVATE_DIRECTORY_NAMES:
                continue
            if SECRET_NAME_RE.search(entry.name):
                raise ReleaseBuildError(f"secret-looking directory found: {relative_path}")
            yield from _walk_directory(path, root, ignored_paths)
            continue
        if not entry.is_file(follow_symlinks=False):
            raise ReleaseBuildError(f"unsupported filesystem object: {relative_path}")
        release_file = _read_release_file(path, root)
        if release_file is not None:
            yield release_file


def _git_index_entries(root: Path) -> dict[str, tuple[str, int]] | None:
    """Return stage-zero Git index blobs, or ``None`` outside a worktree."""

    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return None
    if probe.returncode != 0:
        return None
    try:
        worktree_root = Path(
            probe.stdout.decode("utf-8", errors="strict").strip()
        ).resolve()
    except (OSError, UnicodeDecodeError):
        return None
    if os.path.normcase(str(worktree_root)) != os.path.normcase(str(root.resolve())):
        return None
    listed = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        detail = listed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseBuildError(f"cannot read Git index: {detail or 'git ls-files failed'}")

    entries: dict[str, tuple[str, int]] = {}
    for raw_entry in listed.stdout.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            raw_mode, raw_oid, raw_stage = metadata.split(b" ", 2)
            relative_path = raw_path.decode("utf-8")
            mode = int(raw_mode, 8)
            stage = int(raw_stage)
            oid = raw_oid.decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseBuildError("Git index contains an unsupported entry") from exc
        if stage != 0:
            raise ReleaseBuildError(
                f"Git index contains an unresolved merge entry: {relative_path}"
            )
        entries[relative_path] = (oid, mode)
    return entries


def _git_release_candidate_path(root: Path, relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ReleaseBuildError(f"unsafe Git index path: {relative_path!r}")
    lowered_parts = [part.casefold() for part in path.parts]
    if any(
        _is_excluded_directory_name(part) or part in PRIVATE_DIRECTORY_NAMES
        for part in lowered_parts[:-1]
    ):
        return False
    if len(path.parts) == 1:
        candidate = root / path.name
        if not _is_root_file_allowed(candidate):
            return False
    elif path.parts[0].casefold() not in {
        name.casefold() for name in PROJECT_DIRECTORIES
    }:
        return False
    return _classify_path(root / Path(*path.parts), relative_path) == "include"


def _git_blob_contents(
    root: Path,
    entries: list[tuple[str, str]],
) -> dict[str, bytes]:
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        process.stdin.write("".join(f"{oid}\n" for _, oid in entries).encode("ascii"))
        process.stdin.close()
        blobs: dict[str, bytes] = {}
        for relative_path, expected_oid in entries:
            header = process.stdout.readline().rstrip(b"\n")
            fields = header.split(b" ")
            if len(fields) != 3 or fields[1] != b"blob":
                rendered = header.decode("utf-8", errors="replace")
                raise ReleaseBuildError(
                    f"cannot read staged Git blob for {relative_path}: {rendered}"
                )
            oid = fields[0].decode("ascii")
            size = int(fields[2])
            if oid != expected_oid:
                raise ReleaseBuildError(f"Git returned the wrong blob for {relative_path}")
            content = process.stdout.read(size)
            separator = process.stdout.read(1)
            if len(content) != size or separator != b"\n":
                raise ReleaseBuildError(f"truncated staged Git blob for {relative_path}")
            blobs[relative_path] = content
        return_code = process.wait()
        if return_code != 0:
            detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            raise ReleaseBuildError(
                f"cannot read staged Git blobs: {detail or 'git cat-file failed'}"
            )
        return blobs
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def _replace_with_git_index_content(
    root: Path,
    files: list[ReleaseFile],
) -> list[ReleaseFile]:
    """Bind release bytes to the staged Git index when one is available.

    A Windows checkout can contain CRLF-expanded working-tree bytes even though
    the commit stores LF. Reading the index makes the archive identical on CI,
    Linux and Nvidia while also rejecting untracked or unstaged release input.
    """

    index = _git_index_entries(root)
    if index is None:
        return files

    filesystem_paths = {item.path for item in files}
    index_paths = {
        path for path in index if _git_release_candidate_path(root, path)
    }
    untracked = sorted(filesystem_paths - set(index))
    if untracked:
        raise ReleaseBuildError(
            "release source is not tracked in the staged Git index: "
            + ", ".join(untracked[:10])
        )
    missing = sorted(index_paths - filesystem_paths)
    if missing:
        raise ReleaseBuildError(
            "tracked release source is missing from the working tree: "
            + ", ".join(missing[:10])
        )

    changed = subprocess.run(
        ["git", "diff", "--name-only", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if changed.returncode != 0:
        detail = changed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseBuildError(
            f"cannot compare working tree with Git index: {detail or 'git diff failed'}"
        )
    unstaged_paths = {
        value.decode("utf-8")
        for value in changed.stdout.split(b"\0")
        if value
    }
    unstaged_release_paths = sorted(unstaged_paths & index_paths)
    if unstaged_release_paths:
        raise ReleaseBuildError(
            "release source has unstaged changes: "
            + ", ".join(unstaged_release_paths[:10])
        )

    blob_requests: list[tuple[str, str]] = []
    for path in sorted(filesystem_paths):
        oid, mode = index[path]
        if mode not in {0o100644, 0o100755}:
            raise ReleaseBuildError(f"unsupported Git object mode for {path}: {mode:o}")
        blob_requests.append((path, oid))
    blobs = _git_blob_contents(root, blob_requests)

    result: list[ReleaseFile] = []
    for item in files:
        content = blobs[item.path]
        if len(content) > MAX_FILE_BYTES:
            raise ReleaseBuildError(
                f"release source file exceeds size limit: {item.path}"
            )
        _validate_content(content, item.path)
        result.append(
            ReleaseFile(
                item.path,
                content,
                item.mode,
                _sha256(content),
            )
        )
    current_index = _git_index_entries(root)
    if current_index != index:
        raise ReleaseBuildError(
            "Git index changed while release source was being materialized"
        )
    final_changed = subprocess.run(
        ["git", "diff", "--name-only", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if final_changed.returncode != 0:
        detail = final_changed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseBuildError(
            f"cannot re-check working tree against Git index: {detail or 'git diff failed'}"
        )
    final_unstaged_paths = {
        value.decode("utf-8")
        for value in final_changed.stdout.split(b"\0")
        if value
    }
    final_unstaged_release_paths = sorted(final_unstaged_paths & index_paths)
    if final_unstaged_release_paths:
        raise ReleaseBuildError(
            "release source changed while being materialized: "
            + ", ".join(final_unstaged_release_paths[:10])
        )
    return result


def collect_release_files(
    root: Path,
    *,
    ignored_paths: Iterable[Path] = (),
) -> list[ReleaseFile]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ReleaseBuildError(f"release root is not a directory: {root}")
    ignored = {path.resolve(strict=False) for path in ignored_paths}
    files: list[ReleaseFile] = []

    try:
        root_entries = sorted(os.scandir(root), key=lambda item: item.name)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot scan release root: {exc}") from exc

    project_directories = {name.casefold() for name in PROJECT_DIRECTORIES}
    for entry in root_entries:
        path = Path(entry.path)
        resolved = path.resolve(strict=False)
        if resolved in ignored:
            continue
        if entry.is_symlink():
            if entry.name.casefold() in project_directories or _is_root_file_allowed(path):
                raise ReleaseBuildError(f"symlink found in release source: {entry.name}")
            continue
        if entry.is_dir(follow_symlinks=False):
            if entry.name.casefold() in project_directories:
                files.extend(_walk_directory(path, root, ignored))
            continue
        if not entry.is_file(follow_symlinks=False):
            continue

        relative_path = _relative_posix(path, root)
        # Root-level private material must fail closed even though it is outside
        # the normal project-file allowlist.
        classification = _classify_path(path, relative_path)
        if classification == "exclude" or not _is_root_file_allowed(path):
            continue
        release_file = _read_release_file(path, root)
        if release_file is not None:
            files.append(release_file)

    files.sort(key=lambda item: item.path)
    files = _replace_with_git_index_content(root, files)
    if not files:
        raise ReleaseBuildError("release source contains no eligible files")
    duplicate_paths = [
        files[index].path
        for index in range(1, len(files))
        if files[index - 1].path == files[index].path
    ]
    if duplicate_paths:
        raise ReleaseBuildError(f"duplicate release paths: {duplicate_paths}")
    total_bytes = sum(item.size for item in files)
    if total_bytes > MAX_RELEASE_BYTES:
        raise ReleaseBuildError("release source exceeds total size limit")
    return files


def _inventory_payload(
    files: Iterable[ReleaseFile],
    archive_root: str,
    source_date_epoch: int,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_format": "tar+gzip",
        "archive_root": archive_root,
        "source_date_epoch": source_date_epoch,
        "files": [
            {
                "path": item.path,
                "archive_path": f"{archive_root}/{item.path}",
                "sha256": item.sha256,
                "size": item.size,
                "mode": f"{item.mode:04o}",
            }
            for item in files
        ],
    }


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _tar_info(name: str, *, mode: int, size: int, mtime: int, is_directory: bool) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name + ("/" if is_directory and not name.endswith("/") else ""))
    info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
    info.mode = mode
    info.size = 0 if is_directory else size
    info.mtime = mtime
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _archive_directories(archive_root: str, file_paths: Iterable[str]) -> list[str]:
    directories = {archive_root}
    for file_path in file_paths:
        parent = PurePosixPath(file_path).parent
        while parent != PurePosixPath("."):
            directories.add(f"{archive_root}/{parent.as_posix()}")
            parent = parent.parent
    return sorted(directories, key=lambda value: (value.count("/"), value))


def _write_archive(
    destination: Path,
    files: list[ReleaseFile],
    embedded_inventory: bytes,
    archive_root: str,
    source_date_epoch: int,
) -> None:
    member_paths = [item.path for item in files] + ["RELEASE-INVENTORY.json"]
    with destination.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=raw_output,
            mtime=source_date_epoch,
        ) as compressed_output:
            with tarfile.open(
                mode="w",
                fileobj=cast(BinaryIO, compressed_output),
                format=tarfile.GNU_FORMAT,
            ) as archive:
                for directory in _archive_directories(archive_root, member_paths):
                    archive.addfile(
                        _tar_info(
                            directory,
                            mode=0o755,
                            size=0,
                            mtime=source_date_epoch,
                            is_directory=True,
                        )
                    )
                for item in files:
                    archive.addfile(
                        _tar_info(
                            f"{archive_root}/{item.path}",
                            mode=item.mode,
                            size=item.size,
                            mtime=source_date_epoch,
                            is_directory=False,
                        ),
                        io.BytesIO(item.content),
                    )
                archive.addfile(
                    _tar_info(
                        f"{archive_root}/RELEASE-INVENTORY.json",
                        mode=0o644,
                        size=len(embedded_inventory),
                        mtime=source_date_epoch,
                        is_directory=False,
                    ),
                    io.BytesIO(embedded_inventory),
                )


def _validate_archive_root(value: str) -> str:
    candidate = value.strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or len(path.parts) != 1
        or path.name in {".", ".."}
        or "\\" in candidate
        or _has_control_characters(candidate)
        or SAFE_ARCHIVE_ROOT_RE.fullmatch(candidate) is None
    ):
        raise ReleaseBuildError(f"invalid archive root: {value!r}")
    return candidate


def build_release(
    root: Path,
    output: Path,
    *,
    source_date_epoch: int = DEFAULT_SOURCE_DATE_EPOCH,
    archive_root: str = DEFAULT_ARCHIVE_ROOT,
) -> BuildResult:
    root = root.resolve(strict=True)
    if output.is_symlink():
        raise ReleaseBuildError(f"output path is a symlink: {output}")
    output = output.resolve(strict=False)
    archive_root = _validate_archive_root(archive_root)
    if source_date_epoch < 0 or source_date_epoch > 0xFFFFFFFF:
        raise ReleaseBuildError("source-date-epoch must be between 0 and 4294967295")
    sha256_sidecar = Path(f"{output}.sha256")
    inventory_path = Path(f"{output}.inventory.json")
    output_paths = (output, sha256_sidecar, inventory_path)
    existing_outputs = [path for path in output_paths if path.exists() or path.is_symlink()]
    if existing_outputs:
        rendered = ", ".join(str(path) for path in existing_outputs)
        raise ReleaseBuildError(f"release output already exists: {rendered}")
    ignored_paths = {output, sha256_sidecar, inventory_path}
    files = collect_release_files(root, ignored_paths=ignored_paths)
    embedded_payload = _inventory_payload(files, archive_root, source_date_epoch)
    embedded_inventory = _json_bytes(embedded_payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    published_paths: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".release-archive-", suffix=".tmp", dir=output.parent, delete=False
        ) as temporary_archive_file:
            temporary_archive = Path(temporary_archive_file.name)
        temporary_paths.append(temporary_archive)
        _write_archive(
            temporary_archive,
            files,
            embedded_inventory,
            archive_root,
            source_date_epoch,
        )
        archive_content = temporary_archive.read_bytes()
        archive_sha256 = _sha256(archive_content)

        external_payload = {
            **embedded_payload,
            "archive": {
                "name": output.name,
                "sha256": archive_sha256,
                "size": len(archive_content),
            },
        }
        sidecar_content = f"{archive_sha256}  {output.name}\n".encode("ascii")
        inventory_content = _json_bytes(external_payload)

        for label, content in (
            ("sha256", sidecar_content),
            ("inventory", inventory_content),
        ):
            with tempfile.NamedTemporaryFile(
                prefix=f".release-{label}-", suffix=".tmp", dir=output.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
            temporary_paths.append(temporary_path)

        os.replace(temporary_archive, output)
        published_paths.append(output)
        temporary_paths.remove(temporary_archive)
        os.replace(temporary_paths[0], sha256_sidecar)
        published_paths.append(sha256_sidecar)
        temporary_paths.pop(0)
        os.replace(temporary_paths[0], inventory_path)
        published_paths.append(inventory_path)
        temporary_paths.pop(0)
    except Exception:
        for published_path in reversed(published_paths):
            try:
                published_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        for temporary_path in temporary_paths:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return BuildResult(
        archive=output,
        sha256_sidecar=sha256_sidecar,
        inventory=inventory_path,
        archive_sha256=archive_sha256,
        archive_size=output.stat().st_size,
        file_count=len(files),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, credential-safe Nvidia deployment archive."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root (default: repository containing this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/wamocon-marketing-machine.tar.gz"),
        help="Archive destination; .sha256 and .inventory.json sidecars are added.",
    )
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", str(DEFAULT_SOURCE_DATE_EPOCH))),
        help="Normalized gzip/tar modification time (default: SOURCE_DATE_EPOCH or 0).",
    )
    parser.add_argument(
        "--archive-root",
        default=DEFAULT_ARCHIVE_ROOT,
        help=f"Single top-level archive directory (default: {DEFAULT_ARCHIVE_ROOT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_release(
            args.root,
            args.output,
            source_date_epoch=args.source_date_epoch,
            archive_root=args.archive_root,
        )
    except (OSError, ReleaseBuildError, ValueError) as exc:
        print(f"release archive rejected: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "archive": str(result.archive),
                "sha256": result.archive_sha256,
                "sha256_sidecar": str(result.sha256_sidecar),
                "inventory": str(result.inventory),
                "files": result.file_count,
                "bytes": result.archive_size,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
