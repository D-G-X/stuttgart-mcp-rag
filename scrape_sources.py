"""Scrape target inventory (Phase 7.1).

Not a hard gate to the current 5 topics — add sources here as relevant pages
are found. Starting set is every `source`/`source2` URL already trusted in
data/docs/*.md frontmatter, so the first scrape run can be checked for parity
against known-good hand-picked content.

robots.txt checked manually against each domain below on 2026-08-07: none of
these disallow generic crawlers from the informational pages listed here (the
disallows that exist are for search/admin/tracking paths). Re-check if a new
domain is added.
"""

from dataclasses import dataclass


@dataclass
class Source:
    url: str
    topic: str


SOURCES: list[Source] = [
    # anmeldung
    Source(
        url="https://www.stuttgart.de/en/organigramm/leistungen/wohnsitz-anmelden-als-hauptwohnsitz",
        topic="anmeldung",
    ),
    # aufenthaltstitel
    Source(
        url="https://www.uni-stuttgart.de/en/study/international/visa/",
        topic="aufenthaltstitel",
    ),
    Source(
        url="https://www.stuttgart.de/en/organigramm/leistungen/aufenthaltserlaubnis-beantragen-zum-zweck-des-studiums-sprachkurs-schulbesuch",
        topic="aufenthaltstitel",
    ),
    # sperrkonto
    Source(
        url="https://www.study.eu/article/germany-blocked-bank-accounts-for-students-guide",
        topic="sperrkonto",
    ),
    # health_insurance
    Source(
        url="https://www.daad.de/en/studying-in-germany/living-in-germany/health-insurance/",
        topic="health_insurance",
    ),
    # germany-visa.org (blocked-account and health-insurance pages) dropped
    # 2026-08-07: both return 405 Method Not Allowed to every fetch attempt,
    # confirmed anti-bot, not transient. Each topic already has one working
    # source above; not worth a headless-browser workaround for a redundant
    # third-party page.
    # university_enrollment
    Source(
        url="https://www.student.uni-stuttgart.de/en/startingout/enrollment/",
        topic="university_enrollment",
    ),
    Source(
        url="https://www.uni-stuttgart.de/en/university/international/service/",
        topic="university_enrollment",
    ),
    # offices: no separate Source entry needed -- scrape_extract.py's
    # split_office_listings() automatically emits a second
    # "*-offices.md" doc (topic="offices") from the anmeldung page above as
    # a side effect. An explicit duplicate Source here would just get
    # dropped by unique_sources()'s dedup anyway (it did, silently, before
    # this was noticed -- see split_office_listings' docstring).

    # oeffnungszeitenbuch.de dropped 2026-08-07: its real content (address,
    # phone, hours) isn't present in the static HTML at all -- only SEO nav
    # chrome is -- and every office it covers is already listed on the
    # stuttgart.de page above. Not worth a headless-browser dependency for
    # one redundant, low-authority third-party page.

    # hft_offices -- HFT Stuttgart (Hochschule für Technik), a separate
    # institution from the University of Stuttgart. Added 2026-08-07.
    # robots.txt checked: only disallows /typo3*/ admin paths.
    Source(
        url="https://www.hft-stuttgart.com/studies/international",
        topic="hft_offices",
    ),
    Source(
        url="https://www.hft-stuttgart.com/hft/news-and-information/contact-information",
        topic="hft_offices",
    ),
    # hft_software_technology -- M.Sc. Software Technology program page.
    # Page is served in English (lang="en") despite the German-looking path.
    Source(
        url="https://www.hft-stuttgart.com/studium/studienbereiche/computer-science/master-software-technology",
        topic="hft_software_technology",
    ),
]


def unique_sources() -> list[Source]:
    """SOURCES deduped by URL (first topic wins) -- some pages are cited by
    more than one topic, but should only be fetched/extracted once."""
    seen: set[str] = set()
    result = []
    for source in SOURCES:
        if source.url not in seen:
            seen.add(source.url)
            result.append(source)
    return result
