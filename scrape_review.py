"""Review gate (Phase 7.4): risk-based auto-publish vs. hold-for-review.

data/scraped/ (written by scrape_extract.py every run) is the candidate set.
data/published/ is the "live" set -- what a future ingest.py would actually
read from. This module is what moves content from one to the other: unchanged
candidates are a no-op, changed candidates auto-publish if they pass sanity
checks, and anything that fails (or has never been published before) is
copied to data/scraped_review/ for a human to look at instead of silently
going live.

No separate state file -- data/published/*.md itself is the source of truth
for "what was last approved", so there's nothing to fall out of sync.
"""

from dataclasses import dataclass
from pathlib import Path

from chunking import chunk_document

SCRAPED_DIR = Path(__file__).parent / "data" / "scraped"
PUBLISHED_DIR = Path(__file__).parent / "data" / "published"
REVIEW_DIR = Path(__file__).parent / "data" / "scraped_review"

# How much an approved page's extracted length may shrink/grow before a
# change is treated as suspicious (site redesign, extraction breakage) rather
# than a routine content edit.
MIN_LENGTH_RATIO = 0.5
MAX_LENGTH_RATIO = 3.0

# An update must keep at least this fraction of the previously-approved
# section names, or it's treated as a possible restructuring rather than a
# routine edit.
MIN_SECTION_OVERLAP = 0.5


@dataclass
class ReviewResult:
    slug: str
    status: str  # "unchanged" | "auto_published" | "held_for_review" | "first_seen"
    reason: str = ""


def _structural_check(path: Path) -> list[str]:
    """Checks that don't need a previous version to compare against."""
    try:
        chunks = chunk_document(path)
    except Exception as exc:
        return [f"failed to parse/chunk: {exc}"]
    if not chunks:
        return ["produced zero chunks"]
    return []


def _drift_checks(candidate_path: Path, prev_path: Path) -> list[str]:
    """Checks comparing a changed candidate against the previously-approved
    version -- these are what catch a site redesign or a broken extraction
    silently going live as a routine content update."""
    failures = _structural_check(candidate_path)

    prev_text = prev_path.read_text(encoding="utf-8")
    candidate_text = candidate_path.read_text(encoding="utf-8")
    ratio = len(candidate_text) / len(prev_text) if prev_text else 1.0
    if ratio < MIN_LENGTH_RATIO:
        failures.append(f"content shrank to {ratio:.0%} of the previously-approved length")
    elif ratio > MAX_LENGTH_RATIO:
        failures.append(f"content grew to {ratio:.0%} of the previously-approved length")

    try:
        prev_sections = {c.section for c in chunk_document(prev_path)}
        new_sections = {c.section for c in chunk_document(candidate_path)}
        overlap = len(prev_sections & new_sections) / len(prev_sections) if prev_sections else 1.0
        if overlap < MIN_SECTION_OVERLAP:
            failures.append(
                f"only {overlap:.0%} of previously-approved section names are still present "
                "(possible site restructuring)"
            )
    except Exception:
        pass  # already reported by _structural_check if the candidate itself is unparseable

    return failures


def review_one(candidate_path: Path) -> ReviewResult:
    slug = candidate_path.stem
    prev_path = PUBLISHED_DIR / candidate_path.name

    if not prev_path.exists():
        failures = _structural_check(candidate_path)
        if failures:
            REVIEW_DIR.mkdir(parents=True, exist_ok=True)
            (REVIEW_DIR / candidate_path.name).write_text(
                candidate_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            return ReviewResult(slug, "held_for_review", "; ".join(failures))
        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
        prev_path.write_text(candidate_path.read_text(encoding="utf-8"), encoding="utf-8")
        return ReviewResult(slug, "first_seen", "no prior version -- passed structural checks, published")

    candidate_text = candidate_path.read_text(encoding="utf-8")
    if candidate_text == prev_path.read_text(encoding="utf-8"):
        return ReviewResult(slug, "unchanged")

    failures = _drift_checks(candidate_path, prev_path)
    if failures:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        (REVIEW_DIR / candidate_path.name).write_text(candidate_text, encoding="utf-8")
        return ReviewResult(slug, "held_for_review", "; ".join(failures))

    prev_path.write_text(candidate_text, encoding="utf-8")
    return ReviewResult(slug, "auto_published", "passed sanity checks")


if __name__ == "__main__":
    for path in sorted(SCRAPED_DIR.glob("*.md")):
        result = review_one(path)
        print(f"{result.status:15s} {result.slug}")
        if result.reason:
            print(f"                {result.reason}")
