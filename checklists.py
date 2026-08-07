"""Structured, hand-curated step-by-step checklists per bureaucratic topic.

Unlike search_bureaucracy_docs (fuzzy semantic retrieval over chunks), this is
a direct lookup: given a known topic, return the exact, ordered, complete list
of steps — guaranteed, not "most similar."
"""

# Same source docs the checklist steps were derived from, so this tool can
# cite honestly instead of the model inventing a citation when none is given.
TOPIC_SOURCES: dict[str, tuple[str, str]] = {
    "anmeldung": (
        "Registering Your Address (Anmeldung) in Stuttgart",
        "https://www.stuttgart.de/en/organigramm/leistungen/wohnsitz-anmelden-als-hauptwohnsitz",
    ),
    "aufenthaltstitel": (
        "Residence Permit (Aufenthaltstitel) and Visa Extension for Students",
        "https://www.uni-stuttgart.de/en/study/international/visa/",
    ),
    "sperrkonto": (
        "Blocked Account (Sperrkonto) for Student Visa Applications",
        "https://www.study.eu/article/germany-blocked-bank-accounts-for-students-guide",
    ),
    "health_insurance": (
        "Health Insurance (Krankenversicherung) for International Students",
        "https://www.daad.de/en/studying-in-germany/living-in-germany/health-insurance/",
    ),
    "university_enrollment": (
        "Enrollment (Immatriculation) at the University of Stuttgart",
        "https://www.student.uni-stuttgart.de/en/startingout/enrollment/",
    ),
}

TOPIC_CHECKLISTS: dict[str, list[str]] = {
    "anmeldung": [
        "Move into your new home in Stuttgart.",
        "Get a signed Wohnungsgeberbestätigung (landlord's confirmation of move-in) from your landlord.",
        "Book an appointment at your local Bürgerbüro online as early as possible, especially around semester start.",
        "Attend your appointment within 2 weeks of moving in, bringing your passport/ID and the Wohnungsgeberbestätigung.",
        "Receive your Meldebescheinigung (registration confirmation) and keep several copies — you'll need it repeatedly.",
    ],
    "aufenthaltstitel": [
        "Gather current proof of enrollment (Immatrikulationsbescheinigung).",
        "Gather current proof of funding (blocked account statement or equivalent).",
        "Make sure your passport, a biometric photo, and proof of health insurance are ready.",
        "Apply via Stuttgart's online portal 1–2 months before your current permit expires — select 'Residence permit for training', then the extension option.",
        "Wait for processing. Decisions often arrive close to the expiry date, so apply as early as the portal allows.",
    ],
    "sperrkonto": [
        "Choose a licensed blocked account provider (e.g. Fintiba, Expatrio, Coracle) and compare fees.",
        "Open the account and deposit the required amount (€11,904 as of 2026 — verify the current figure before applying).",
        "Get the account confirmation document to include with your visa application.",
        "After arriving in Germany, activate the account.",
        "Withdraw up to €992/month (1/12 of the total deposit) to cover living expenses.",
    ],
    "health_insurance": [
        "Determine which system applies to you: public (GKV) if you're under 30 in a regular degree program, private (PKV) otherwise.",
        "Choose a provider and obtain an insurance confirmation.",
        "Submit the confirmation for both university enrollment and your residence permit application.",
        "If you started with short-term/travel insurance, switch to public or long-term coverage promptly after arrival.",
    ],
    "university_enrollment": [
        "Receive your letter of admission.",
        "Arrange proof of health insurance.",
        "Register your address (Anmeldung) to get a Meldebescheinigung — this can sometimes follow shortly after enrollment if not yet available.",
        "Prepare a passport photo and valid ID/passport.",
        "If applicable, provide proof of German language proficiency (DSH/TestDaF).",
        "Complete enrollment online via the C@MPUS system.",
    ],
}
