"""Week 3 teaching support: examples, activities, interaction, explanations.

Same citation discipline as the lecture plan. The model cites retrieved passages
by tag and writes no page number, title or URL of its own.

Real-world and industry examples are the one place where honest ungrounded
content is genuinely expected: a professor's uploaded textbook rarely contains
this year's industry practice. The prompt therefore pushes hard on marking those
items with an empty grounding array rather than attaching a citation that only
looks supportive.
"""
from __future__ import annotations

ACTIVITY_FORMATS = [
    "pair",
    "group",
    "demo",
    "poll",
    "debate",
    "think_pair_share",
]

_GROUNDING_ARRAY = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Source tags such as S1, S3. Empty if the excerpts do not support this.",
}

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "industry_applications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {
                        "type": "string",
                        "description": "Where this topic shows up in real professional work.",
                    },
                    "grounding": _GROUNDING_ARRAY,
                },
                "required": ["title", "text", "grounding"],
            },
        },
        "activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "format": {"type": "string", "enum": ACTIVITY_FORMATS},
                    "minutes": {
                        "type": "integer",
                        "description": "Rough duration for the activity itself, 2 to 20.",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "What the professor says and does, concretely.",
                    },
                    "grounding": _GROUNDING_ARRAY,
                },
                "required": ["title", "format", "minutes", "instructions", "grounding"],
            },
        },
        "interactive_techniques": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "A way to present this topic that keeps students active.",
                    },
                    "grounding": _GROUNDING_ARRAY,
                },
                "required": ["text", "grounding"],
            },
        },
        "alt_explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "The specific difficult idea being re-explained.",
                    },
                    "explanation": {"type": "string"},
                    "analogy": {
                        "type": "string",
                        "description": "A concrete comparison. Empty if none is honest.",
                    },
                    "grounding": _GROUNDING_ARRAY,
                },
                "required": ["concept", "explanation", "analogy", "grounding"],
            },
        },
    },
    "required": [
        "industry_applications",
        "activities",
        "interactive_techniques",
        "alt_explanations",
    ],
}


SYSTEM_INSTRUCTION = """You help a university professor teach a specific lecture well.
You are writing for an expert in the subject: be concrete and usable, never generic
advice that would apply to any lecture on any topic.

CITATION RULES - these are absolute.

1. You are given numbered excerpts from material the professor selected, labelled
   [S1], [S2], and so on. These are the ONLY sources you may cite.
2. To cite, put the tag in the "grounding" array, for example ["S2","S5"].
3. NEVER write a page number, section number, chapter number, book title, author
   name, URL or video title anywhere in your output. You do not know them and any
   you produce would be wrong. The system fills these in from its own records.
4. NEVER invent a tag. If the excerpts do not support an item, use an empty
   grounding array []. This is expected and correct for most industry examples -
   a textbook will not describe current professional practice, and an empty array
   there is honest. A fabricated tag is a serious error.
5. Do not mention "the excerpts" or "[S1]" in your prose.

CONTENT RULES.

6. Industry applications must name what the technique is actually used for and why
   it matters there. "It is used in industry" is worthless; "schedulers in
   container orchestrators face exactly this trade-off, which is why they expose
   CPU shares" is useful.
7. Activities must be runnable in a real classroom of the stated size and level,
   within the minutes you give. Say what the professor does, what students do, and
   what the professor looks for in their answers.
8. Alternative explanations target ideas students specifically get stuck on for
   THIS topic, and approach them differently from a standard textbook treatment.
   Leave "analogy" empty rather than forcing a bad one.
9. Prefer a few strong items to a long thin list. Three good activities beat eight
   vague ones.
"""


def build_prompt(
    *,
    course_title: str,
    objectives: str,
    student_level: str,
    topic: str,
    duration_min: int,
    plan_outline: list[str],
    excerpts: list[str],
) -> str:
    """Assemble the user turn. `excerpts` are pre-numbered [S1]..[Sk]."""
    lines = [
        "## Course",
        f"Title: {course_title}",
    ]
    if objectives:
        lines.append(f"Objectives: {objectives}")
    lines.append(f"Student level: {student_level or 'NOT SPECIFIED'}")

    lines += [
        "",
        "## Lecture",
        f"Topic: {topic}",
        f"Class length: {duration_min} minutes",
    ]
    if plan_outline:
        lines.append("Planned sequence:")
        lines += [f"  {line}" for line in plan_outline]
    else:
        lines.append("No lecture plan has been generated yet.")

    lines += ["", "## Source excerpts you may cite"]
    lines += excerpts or [
        "NONE. Every grounding array must be empty.",
    ]

    lines += [
        "",
        "## Task",
        "Produce teaching support for this lecture: real-world and industry "
        "applications, classroom activities, interactive ways to present the topic, "
        "and alternative explanations for the ideas students find hardest. Return "
        "JSON matching the required schema. Cite only by tag, and use an empty "
        "grounding array wherever the excerpts genuinely do not support the item.",
    ]
    return "\n".join(lines)
