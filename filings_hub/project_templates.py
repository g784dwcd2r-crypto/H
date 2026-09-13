"""Locally maintained research prompts; no generated company facts or source claims."""

from copy import deepcopy
from typing import Any

from filings_hub.tenancy import SecurityError

TEMPLATES = (
    {
        "id": "company-overview",
        "version": 1,
        "name": "Company overview",
        "description": "Map the business, its financial drivers and the questions to investigate.",
        "notes": [
            {
                "title": "Business and competitive position",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What does the company sell, to whom, and in which markets?\n"
                "Which segments drive revenue and profit?\n"
                "What supports or challenges its competitive position?\n"
                "Which source documents support each conclusion?",
            },
            {
                "title": "Financial drivers and source checks",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "Which periods, currencies and reporting units are you comparing?\n"
                "What drives revenue, margins, cash conversion and capital needs?\n"
                "Which figures need reconciliation or have changed reporting basis?\n"
                "Attach source references and distinguish facts from your interpretation.",
            },
            {
                "title": "Risks, catalysts and open questions",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What could materially change the business outlook?\n"
                "Which events or disclosures should you monitor?\n"
                "What evidence would change your current view?\n"
                "Which questions remain unanswered?",
            },
        ],
    },
    {
        "id": "earnings-review",
        "version": 1,
        "name": "Earnings review",
        "description": "Prepare for a release, record the evidence and track follow-up questions.",
        "notes": [
            {
                "title": "Pre-release questions",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "Which company and fiscal period are you reviewing?\n"
                "What are your expectations, and where did they come from?\n"
                "Which metrics, guidance items and risks will you check?\n"
                "What would constitute a meaningful surprise?",
            },
            {
                "title": "Results and reporting changes",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What was reported, in which units and on which accounting basis?\n"
                "How does it compare with prior periods and your recorded expectations?\n"
                "Were figures restated or definitions changed?\n"
                "Attach the release and filing references; identify missing evidence.",
            },
            {
                "title": "Interpretation and follow-up",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What changed in your assessment, and why?\n"
                "Which management statements require verification?\n"
                "What follow-up research or model changes are needed?\n"
                "Which unanswered questions should you revisit next period?",
            },
        ],
    },
    {
        "id": "investment-thesis-diligence",
        "version": 1,
        "name": "Investment thesis and diligence",
        "description": "Develop a testable view with scenarios, contrary evidence and a diligence log.",
        "notes": [
            {
                "title": "Investment thesis",
                "kind": "thesis",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What is your hypothesis and research horizon?\n"
                "Which assumptions does it depend on?\n"
                "What evidence supports it, and what evidence contradicts it?\n"
                "What would invalidate the thesis?",
            },
            {
                "title": "Scenarios and valuation assumptions",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "What are your downside, base and upside assumptions?\n"
                "Which operating drivers and valuation inputs matter most?\n"
                "Which inputs are sourced facts versus your own estimates?\n"
                "How sensitive is your conclusion to those assumptions?",
            },
            {
                "title": "Diligence and contrary evidence",
                "kind": "note",
                "body": "Research prompts — replace these with your own work.\n\n"
                "Which questions must be answered before you reach a conclusion?\n"
                "Which sources have you checked, and what remains unavailable?\n"
                "What is the strongest opposing interpretation?\n"
                "Record follow-up actions and the evidence needed to close each question.",
            },
        ],
    },
)


def templates() -> list[dict[str, Any]]:
    """Return independent values so a caller cannot mutate future starter projects."""
    return deepcopy(list(TEMPLATES))


def find_template(template_id: Any) -> dict[str, Any] | None:
    if template_id is None:
        return None
    if isinstance(template_id, str):
        for template in TEMPLATES:
            if template["id"] == template_id:
                return deepcopy(template)
    raise SecurityError(422, "template_id must identify an available starter template or be null")
