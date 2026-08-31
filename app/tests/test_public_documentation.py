"""Public documentation, screenshot allowlist, and relative-link contracts."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

DOCS_FILES = {
    "README.md",
    "README.zh-CN.md",
    "getting-started.md",
    "getting-started.zh-CN.md",
    "application-workflow.md",
    "application-workflow.zh-CN.md",
    "mail-ingestion.md",
    "mail-ingestion.zh-CN.md",
    "security-and-privacy.md",
    "security-and-privacy.zh-CN.md",
    "development.md",
    "development.zh-CN.md",
}

PUBLIC_DOCUMENTS = [
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "README.zh-CN.md",
    REPOSITORY_ROOT / "CONTRIBUTING.md",
    REPOSITORY_ROOT / "SECURITY.md",
    REPOSITORY_ROOT / "ROADMAP.md",
    REPOSITORY_ROOT / "CHANGELOG.md",
    REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md",
    REPOSITORY_ROOT / "app" / "README.md",
] + [REPOSITORY_ROOT / "docs" / name for name in sorted(DOCS_FILES)]

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]\r\n]*\]\s*\(([^)\r\n]+)\)")
PUBLIC_SCREENSHOT_PATHS = (
    "docs/assets/screenshots/career-application-assistant-hero.png",
    "docs/assets/screenshots/demo-board.png",
    "docs/assets/screenshots/demo-assessment-detail.png",
)
PUBLIC_SCREENSHOTS = {
    path: REPOSITORY_ROOT / Path(path) for path in PUBLIC_SCREENSHOT_PATHS
}
ROOT_READMES = (REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "README.zh-CN.md")
FORBIDDEN_MEDIA_PATTERNS = (
    re.compile(r"!\[[^\]]*\]\s*(?:\([^)]*\)|\[[^\]]*\])", re.IGNORECASE),
    re.compile(r"<\s*(?:img|picture|video|audio|source)\b", re.IGNORECASE),
    re.compile(r"shields\.io", re.IGNORECASE),
    re.compile(r"^\s*(?:```|~~~)\s*mermaid\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bclass\s*=\s*['\"]mermaid['\"]", re.IGNORECASE),
    re.compile(
        r"\]\([^\)\r\n]*\."
        r"(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|"
        r"ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)"
        r"(?:[?#][^\)\r\n]*)?\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"<(?:https?://|\.\.?/)[^>\r\n]+\."
        r"(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|"
        r"ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)"
        r"(?:[?#][^>\r\n]*)?>",
        re.IGNORECASE,
    ),
    re.compile(
        r"https?://[^\s<>\)]+\."
        r"(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|"
        r"ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)"
        r"(?:[?#][^\s<>\)]*)?",
        re.IGNORECASE,
    ),
)


def test_documentation_file_set_is_exact() -> None:
    actual = {path.name for path in (REPOSITORY_ROOT / "docs").iterdir() if path.is_file()}
    assert actual == DOCS_FILES


def test_public_screenshot_file_set_and_readme_references_are_exact() -> None:
    screenshot_root = REPOSITORY_ROOT / "docs" / "assets" / "screenshots"
    actual = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in screenshot_root.rglob("*")
        if path.is_file()
    }
    assert actual == set(PUBLIC_SCREENSHOT_PATHS)

    for document in ROOT_READMES:
        text = document.read_text(encoding="utf-8")
        targets = [match.group(1).strip() for match in MARKDOWN_IMAGE_RE.finditer(text)]
        assert len(targets) == len(PUBLIC_SCREENSHOT_PATHS)
        assert set(targets) == set(PUBLIC_SCREENSHOT_PATHS)
        for target in targets:
            assert PUBLIC_SCREENSHOTS[target].is_file(), (
                f"missing public screenshot referenced by {document.name}: {target}"
            )


def test_public_documentation_media_is_strictly_allowlisted() -> None:
    for document in PUBLIC_DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        sanitized = text
        if document in ROOT_READMES:
            matches = list(MARKDOWN_IMAGE_RE.finditer(text))
            for match in reversed(matches):
                if match.group(1).strip() in PUBLIC_SCREENSHOT_PATHS:
                    sanitized = sanitized[: match.start()] + sanitized[match.end() :]
        for pattern in FORBIDDEN_MEDIA_PATTERNS:
            assert pattern.search(sanitized) is None, (
                f"forbidden media syntax in {document.name}"
            )


def test_public_documentation_relative_links_resolve_inside_repository() -> None:
    for document in PUBLIC_DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip()
            if target.startswith("<") and ">" in target:
                target = target[1 : target.index(">")]
            else:
                target = target.split(maxsplit=1)[0]

            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue

            candidate = (document.parent / unquote(parsed.path)).resolve()
            candidate.relative_to(REPOSITORY_ROOT.resolve())
            assert candidate.is_file(), f"broken relative link in {document.name}: {target}"
