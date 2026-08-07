"""Split hand-authored markdown docs into heading-based chunks with metadata."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    text: str
    title: str
    section: str
    topic: str
    source: str
    last_checked: str


def parse_doc(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path} is missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    return metadata, body


def split_by_heading(body: str) -> list[tuple[str, str]]:
    """Return [(heading, section_text), ...].

    Any text between the H1 title and the first ## heading is captured as an
    "Overview" section instead of being dropped — intro paragraphs often carry
    the most important framing fact (e.g. a deadline) and must not be lost.
    """
    body = re.sub(r"^#\s+.+\n+", "", body, count=1)  # drop "# Title"
    positions = [(m.start(), m.group(1).strip()) for m in HEADING_RE.finditer(body)]

    if not positions:
        return [("Overview", body.strip())] if body.strip() else []

    sections = []

    intro = body[: positions[0][0]].strip()
    if intro:
        sections.append(("Overview", intro))

    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        content = body[start:end]
        content = re.sub(r"^##\s+.+\n", "", content, count=1).strip()
        if content:
            sections.append((heading, content))
    return sections


def chunk_document(path: Path) -> list[Chunk]:
    metadata, body = parse_doc(path)
    chunks = []
    for heading, content in split_by_heading(body):
        # Prefix with doc title + section so the chunk is meaningful in isolation.
        prefixed_text = f"[{metadata['title']} — {heading}]\n{content}"
        chunks.append(
            Chunk(
                text=prefixed_text,
                title=metadata["title"],
                section=heading,
                topic=metadata.get("topic", ""),
                source=metadata.get("source", ""),
                last_checked=str(metadata.get("last_checked", "")),
            )
        )
    return chunks


def chunk_corpus(docs_dir: Path) -> list[Chunk]:
    all_chunks = []
    for path in sorted(docs_dir.glob("*.md")):
        all_chunks.extend(chunk_document(path))
    return all_chunks


if __name__ == "__main__":
    docs_dir = Path(__file__).parent / "data" / "docs"
    chunks = chunk_corpus(docs_dir)
    print(f"Produced {len(chunks)} chunks from {len(list(docs_dir.glob('*.md')))} docs\n")
    for c in chunks:
        print(f"--- [{c.topic}] {c.title} / {c.section} ---")
        print(c.text[:200].replace("\n", " ") + ("..." if len(c.text) > 200 else ""))
        print()
