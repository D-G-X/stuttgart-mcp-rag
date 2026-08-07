"""Extraction (Phase 7.3): raw HTML -> chunking.py-compatible markdown.

Normalizes to the same contract data/docs/*.md hand-picked corpus follows --
YAML frontmatter (title, source, topic, last_checked) + a single "# Title"
line + "##"-level section headings -- so chunking.py's parse_doc()/HEADING_RE
work unmodified on scraped output. Output goes to data/scraped/, kept
separate from data/docs/ until retrieval quality is verified (Phase 7.8).
"""

import re
from datetime import date
from pathlib import Path

import trafilatura
import yaml

from scrape_fetch import RAW_DIR, _slugify
from scrape_sources import Source, unique_sources

SCRAPED_DIR = Path(__file__).parent / "data" / "scraped"
HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class ExtractError(Exception):
    pass


def flatten_headings(markdown_body: str) -> str:
    """Flatten nested markdown headings to the single '##' level chunking.py's
    HEADING_RE expects, joining ancestor headings into a breadcrumb instead of
    just dropping the hierarchy.

    Naively collapsing every level to '##' loses information on pages with
    real nesting -- e.g. a page listing many offices, each with its own
    "Address"/"Fax"/"Opening hours" sub-headings, would turn 22 distinct
    "Address" sections into 22 identically-named ones. Breadcrumbing keeps
    them distinguishable: "Citizens office east — Address & contact
    information — Address".
    """
    ancestors: dict[int, str] = {}

    def replace(match: re.Match) -> str:
        level, text = len(match.group(1)), match.group(2).strip()
        ancestors[level] = text
        for deeper in [lvl for lvl in ancestors if lvl > level]:
            del ancestors[deeper]
        if level == 1:
            return f"# {text}"  # doc title line, left alone
        breadcrumb = " — ".join(ancestors[lvl] for lvl in sorted(ancestors) if lvl >= 2)
        return f"## {breadcrumb}"

    flattened = HEADING_LINE_RE.sub(replace, markdown_body)
    # Consecutive identical headings with nothing between them (a trafilatura
    # quirk on some sites) collapse to one.
    return re.sub(r"(^##[^\n]*\n)\n+\1", r"\1", flattened, flags=re.MULTILINE)


SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Matches the six spellings stuttgart.de uses for the same institution across
# its office-directory listing: "Citizen office X", "Citizen's Office X",
# "Citizens office X", "Citizens' Advice Bureau X", "Citizens' Office X".
_OFFICE_PREFIX_RE = re.compile(r"^Citizen.{0,3}\s+(?:Office|Advice Bureau)\s+(.+)$", re.IGNORECASE)
# The one outlier where the district name comes first: "Wangen Citizens' Office".
_OFFICE_SUFFIX_RE = re.compile(r"^(.+?)\s+Citizen.{0,3}\s+Office$", re.IGNORECASE)

_HOURS_LINE_RE = re.compile(
    r"\d{1,2}:\d{2}|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|appointment|Closed",
    re.IGNORECASE,
)


def _normalize_office_name(root_heading: str) -> str | None:
    match = _OFFICE_PREFIX_RE.match(root_heading) or _OFFICE_SUFFIX_RE.match(root_heading)
    return match.group(1).strip().title() if match else None


def _clean_hours(text: str) -> str:
    """Keep schedule lines (table rows, day names, time patterns), drop the
    generic prose that stuttgart.de attaches inconsistently per office
    (accessibility notes, vehicle-registration blurbs, wait-time notices) --
    it isn't office-specific and just adds noise to every office's chunk."""
    kept = [
        line for line in text.split("\n")
        if line.strip().startswith("|") or _HOURS_LINE_RE.search(line)
    ]
    return "\n".join(kept).strip()


def _split_sections(body: str) -> list[tuple[str, str]]:
    positions = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(body)]
    sections = []
    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        sections.append((heading, body[start:end]))
    return sections


def split_office_listings(body: str) -> tuple[str, str | None]:
    """Merge stuttgart.de's per-office fragments (Address & contact
    information > Address, > Fax[es]; How to find us > Address; Opening
    hours -- up to 7 headings per office) into one clean '## Bürgerbüro X'
    section per office, then split those out of the page body entirely.

    Returns (procedural_body, office_directory_body_or_None).

    Two separate fixes bundled here, found via retrieval testing rather than
    assumed up front:

    1. Fragmentation: a single office-directory page fragments into ~7 chunks
       per office (96 of 114 chunks in this corpus came from one page), each
       too short and disconnected to embed well.

    2. Even after merging those into one chunk per office (the first fix),
       office chunks still outranked the real Anmeldung procedure content in
       every retrieval test -- because every chunk on the page, procedural or
       not, was prefixed with the same page title ("Register residence - as
       main residence") AND every office chunk repeats a literal "Address:"
       field, so office chunks lexically collide hard with queries like
       "register my address" despite being semantically unrelated (an
       office's mailing address vs. the concept of registering your own).
       Splitting the office directory into its own document with its own
       title and topic -- the same separation the hand-picked corpus already
       had by construction (01_anmeldung.md vs. 06_offices.md) -- removes
       that false association instead of trying to out-rank it.

    A no-op (office_directory_body is None) on pages with no office-directory
    structure -- office_groups stays empty and procedural_body round-trips
    the original content unchanged (aside from whitespace).
    """
    sections = _split_sections(body)
    if not sections:
        return body, None
    first_heading_pos = body.find(f"## {sections[0][0]}")
    preamble = body[:first_heading_pos]

    kept_parts: list[str] = []
    office_groups: dict[str, list[tuple[list[str], str]]] = {}

    for heading, raw_section in sections:
        parts = [p.strip() for p in heading.split(" — ")]
        office_name = _normalize_office_name(parts[0])
        content = re.sub(r"^##[^\n]*\n", "", raw_section, count=1).strip()
        if office_name:
            office_groups.setdefault(office_name, []).append((parts, content))
        else:
            kept_parts.append(raw_section.rstrip("\n") + "\n\n")

    office_blocks: list[str] = []
    for name in sorted(office_groups):
        primary_address = directions_address = hours_raw = None
        fax_entries: list[tuple[str, str]] = []

        for parts, content in office_groups[name]:
            if not content:
                continue
            if len(parts) == 3 and parts[1] == "Address & contact information" and parts[2] == "Address":
                primary_address = content
            elif len(parts) == 3 and parts[1] == "Address & contact information" and parts[2].startswith("Fax"):
                fax_entries.append((parts[2], content))
            elif len(parts) == 3 and parts[1] == "How to find us" and parts[2] == "Address":
                directions_address = content
            elif len(parts) == 2 and parts[1] == "Opening hours":
                hours_raw = content

        lines = []
        address = primary_address or directions_address
        if address:
            address = ", ".join(l.strip() for l in address.splitlines() if l.strip())
            lines.append(f"Address: {address}")
        for label, value in fax_entries:
            value = " ".join(l.strip() for l in value.splitlines() if l.strip())
            lines.append(f"{label}: {value}")
        if hours_raw:
            cleaned_hours = _clean_hours(hours_raw)
            if cleaned_hours:
                lines.append("Opening hours:")
                lines.append(cleaned_hours)

        if lines:
            office_blocks.append(f"## Bürgerbüro {name}\n" + "\n".join(lines) + "\n\n")

    procedural_body = preamble + "".join(kept_parts)
    office_directory_body = "".join(office_blocks) if office_blocks else None
    return procedural_body, office_directory_body


def latest_raw_snapshot(url: str) -> Path:
    snapshots = sorted((RAW_DIR / _slugify(url)).glob("*.html"))
    if not snapshots:
        raise ExtractError(f"no raw snapshot for {url} -- run scrape_fetch.py first")
    return snapshots[-1]


def extract_one(source: Source) -> Path:
    raw_path = latest_raw_snapshot(source.url)
    html = raw_path.read_text(encoding="utf-8")

    body_md = trafilatura.extract(
        html,
        output_format="markdown",
        favor_precision=True,
        deduplicate=True,
        include_comments=False,
    )
    if not body_md or not body_md.strip():
        raise ExtractError(f"trafilatura extracted nothing from {source.url}")

    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else source.url).strip()

    frontmatter = yaml.safe_dump(
        {
            "title": title,
            "source": source.url,
            "topic": source.topic,
            "last_checked": date.today().isoformat(),
        },
        sort_keys=False,
        allow_unicode=True,  # otherwise umlauts etc. come out as \uXXXX escapes
    ).strip()

    flattened = flatten_headings(f"# {title}\n\n{body_md}")
    procedural_body, office_directory_body = split_office_listings(flattened)
    doc = f"---\n{frontmatter}\n---\n\n{procedural_body}\n"

    SCRAPED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCRAPED_DIR / f"{_slugify(source.url)}.md"
    out_path.write_text(doc, encoding="utf-8")

    if office_directory_body:
        # Deliberately its own title/topic, not derived from the parent
        # page's title -- see split_office_listings' docstring for why
        # sharing a title with the procedural content caused office chunks
        # to false-match "register my address"-style queries.
        office_title = "Bürgerbüro (Citizens' Office) Locations in Stuttgart"
        office_frontmatter = yaml.safe_dump(
            {
                "title": office_title,
                "source": source.url,
                "topic": "offices",
                "last_checked": date.today().isoformat(),
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        office_doc = f"---\n{office_frontmatter}\n---\n\n# {office_title}\n\n{office_directory_body}\n"
        office_path = SCRAPED_DIR / f"{_slugify(source.url)}-offices.md"
        office_path.write_text(office_doc, encoding="utf-8")

    return out_path


if __name__ == "__main__":
    for source in unique_sources():
        try:
            path = extract_one(source)
            print(f"OK   [{source.topic}] {source.url} -> {path}")
        except ExtractError as exc:
            print(f"FAIL [{source.topic}] {source.url}: {exc}")
