from __future__ import annotations

import errno
import os
from importlib import resources
from pathlib import Path
from typing import Any


STARTER_TEMPLATES = ("todo",)
_TODO_PACKAGE = "intentir.templates.todo"
_TODO_FILES = (
    "todo.intent",
    "add_task_priority.patch.json",
    "README_JA.md",
)


def create_starter(template: str, directory: Path) -> dict[str, Any]:
    if template != "todo":
        raise ValueError(f"unknown starter template {template!r}")

    payloads = _load_todo_resources()
    if os.path.lexists(directory):
        raise FileExistsError(
            errno.EEXIST,
            "destination already exists",
            str(directory),
        )

    parent = directory.parent
    if not parent.is_dir():
        if os.path.lexists(parent):
            raise NotADirectoryError(
                errno.ENOTDIR,
                "destination parent is not a directory",
                str(parent),
            )
        raise FileNotFoundError(
            errno.ENOENT,
            "destination parent does not exist",
            str(parent),
        )

    directory.mkdir(mode=0o755, exist_ok=False)
    for filename in _TODO_FILES:
        with (directory / filename).open("xb") as output:
            output.write(payloads[filename])

    return {
        "ok": True,
        "template": template,
        "directory": str(directory),
        "files": list(_TODO_FILES),
    }


def _load_todo_resources() -> dict[str, bytes]:
    root = resources.files(_TODO_PACKAGE)
    return {filename: root.joinpath(filename).read_bytes() for filename in _TODO_FILES}
