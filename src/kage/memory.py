"""Agent Memory システム。

topic 単位で1ファイル = 1 memory、frontmatter description/updated_at、上書き式。
agentskills 形式の XML で heading 一覧を system prompt に注入。
location パスは AI 向けには隠蔽し、name/description/updated_at のみ公開。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import tomlkit

from .agent import agent_memory_dir


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
INVALID_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def normalize_slug(slug: str) -> str:
    slug = slug.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = INVALID_SLUG_RE.sub("-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError("slug must not be empty")
    return slug


@dataclass
class MemoryMeta:
    slug: str
    description: str
    updated_at: str
    path: Path


def _memory_dir(agent_name: str) -> Path:
    d = agent_memory_dir(agent_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _memory_path(agent_name: str, slug: str) -> Path:
    slug = normalize_slug(slug)
    return _memory_dir(agent_name) / f"{slug}.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Markdown frontmatter を解析。frontmatter がなければ ({}, 全文)。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    try:
        doc = tomlkit.parse(fm_text)
        data = doc.unwrap() if hasattr(doc, "unwrap") else dict(doc)
        if isinstance(data, dict):
            return data, body
    except Exception:
        pass
    return {}, text


def _build_frontmatter(description: str, updated_at: str) -> str:
    doc = tomlkit.document()
    doc.add("description", description)
    doc.add("updated_at", updated_at)
    return tomlkit.dumps(doc).strip()


def list_memories(agent_name: str) -> list[MemoryMeta]:
    """agent 配下の memory 一覧。slug/description/updated_at 付き。"""
    d = agent_memory_dir(agent_name)
    if not d.exists():
        return []
    metas: list[MemoryMeta] = []
    for path in sorted(d.glob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _ = _parse_frontmatter(text)
        metas.append(
            MemoryMeta(
                slug=path.stem,
                description=str(fm.get("description", "")),
                updated_at=str(fm.get("updated_at", "")),
                path=path,
            )
        )
    return metas


def read_memory(agent_name: str, slug: str) -> Optional[str]:
    """memory 本文を返す。存在しなければ None。"""
    path = _memory_path(agent_name, slug)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(text)
    return body


def write_memory(
    agent_name: str,
    slug: str,
    description: str,
    content: str,
) -> Path:
    """memory を上書き。最新 state のみ保持（追記非対応）。updated_at 更新。"""
    slug = normalize_slug(slug)
    description = (description or "").strip()
    if not description:
        raise ValueError("description must not be empty")
    path = _memory_path(agent_name, slug)
    updated_at = _now_iso()
    fm = _build_frontmatter(description, updated_at)
    body = content.strip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return path


def delete_memory(agent_name: str, slug: str) -> bool:
    """memory を削除。存在すれば True。"""
    path = _memory_path(agent_name, slug)
    if not path.exists():
        return False
    path.unlink()
    return True


def search_memories(agent_name: str, query: str) -> list[tuple[str, int, str]]:
    """memory 本文の全文検索。[(slug, line_number, line_text)] を返す。"""
    d = agent_memory_dir(agent_name)
    if not d.exists():
        return []
    q = query.lower()
    hits: list[tuple[str, int, str]] = []
    for path in sorted(d.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        _, body = _parse_frontmatter(text)
        for i, line in enumerate(body.splitlines(), start=1):
            if q in line.lower():
                hits.append((path.stem, i, line))
    return hits


def build_memory_headings_xml(agent_name: str) -> str:
    """agentskills 形式の <available_memories> を構築。
    location パスは隠蔽し name/description/updated_at のみ公開。
    """
    metas = list_memories(agent_name)
    if not metas:
        return ""
    lines = ["<available_memories>"]
    for meta in metas:
        desc = _xml_escape(meta.description)
        name = _xml_escape(meta.slug)
        updated = _xml_escape(meta.updated_at)
        lines.append("  <memory>")
        lines.append(f"    <name>{name}</name>")
        lines.append(f"    <description>{desc}</description>")
        lines.append(f"    <updated_at>{updated}</updated_at>")
        lines.append("  </memory>")
    lines.append("</available_memories>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
