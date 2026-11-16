"""Portable path validation for dataset manifests and COCO image references.

Dataset paths are serialized and may be consumed on hosts with different path
semantics. Accept only relative POSIX-style paths so Windows drive, UNC,
alternate-stream and backslash traversal forms cannot change meaning later.
"""
from pathlib import PurePosixPath, PureWindowsPath


def is_safe_dataset_relative_path(value: object) -> bool:
    """Return whether value is a portable, non-traversing relative dataset path."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\x00" in value or "\\\\" in value or ":" in value:
        return False

    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    return True
