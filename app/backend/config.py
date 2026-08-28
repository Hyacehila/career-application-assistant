"""Repository layout and fixed data-layer paths for the board service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def find_repository_root(start: Path | None = None) -> Path:
    """Resolve the public repository root from the app directory upward."""

    current = start or Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "AGENTS.md").is_file() and (candidate / "app").is_dir():
            return candidate
    raise RuntimeError("Unable to locate the public repository root.")


@dataclass(frozen=True)
class Paths:
    repository_root: Path
    private_root: Path

    @property
    def database_path(self) -> Path:
        return self.private_root / "applications.sqlite"

    @property
    def frontend_dist(self) -> Path:
        return self.repository_root / "app" / "frontend" / "dist"


def default_paths() -> Paths:
    root = find_repository_root()
    return Paths(repository_root=root, private_root=root / 'private')
