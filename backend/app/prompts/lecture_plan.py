"""Prompt and response schema for lecture plan generation.

Two things are deliberately absent from the schema: minutes and page numbers.

Minutes are absent because the model is bad at arithmetic and a plan that
overruns the class hour is the most visible failure mode there is - it emits a
relative `weight` and the backend apportions real minutes.

Page numbers, titles and authors are absent because they are exactly what the
model gets wrong. It cites by opaque tag; the backend resolves the tag to a
chunk and renders the reference from the database.
"""
from __future__ import annotations

SEGMENT_KINDS = ["recap", "concept", "example", "activity", "check", "summary"]

_GROUNDING_ARRAY = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Source tags such as S1, S3. Empty if not supported by the excerpts.",
}

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "summary": {
            "type": "string",
            "description": "Two or three sentences on the shape of the lecture.",
        },
        "learning_objectives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "grounding": _GROUNDING_ARRAY},
                "required": ["text", "grounding"],
            },
        },
        "prerequisites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "grounding": _GROUNDING_ARRAY},
                "required": ["text", "grounding"],
            },
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": SEGMENT_KINDS},
                    "title": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": "What the professor actually does in this segment.",
                    },
                    "weight": {
                        "type": "integer",
                        "description": "Relative share of class time, 1 to 10. Not minutes.",
                    },
                    "grounding": _GROUNDING_ARRAY,
                },
                "required": ["kind", "title", "body", "weight", "grounding"],
            },
        },
        "misconceptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "grounding": _GROUNDING_ARRAY},
                "required": ["text", "grounding"],
            },
            "description": "Points students commonly get wrong on this topic.",
        },
        "clarifications_needed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["field", "question"],
            },
            "description": "Questions to ask the professor instead of assuming an answer.",
        },
    },
    "required": [
        "topic",
        "summary",
        "learning_objectives",
        "prerequisites",
        "segments",
        "misconceptions",
        "clarifications_needed",
    ],
}


SYSTEM_INSTRUCTION = """You are a co-professor helping a university teacher plan a lecture.
You assist an expert; be concrete and practical, never generic filler.

CITATION RULES - these are absolute.

1. You are given numbered excerpts from material the professor selected, labelled
   [S1], [S2], and so on. These are the ONLY sources you may cite.
2. To cite, put the tag in the "grounding" array, for example ["S2","S5"].
   Cite an excerpt only if that excerpt genuinely supports the statement.
3. NEVER write a page number, section number, chapter number, book title, author
   name, URL or video title anywhere in your output. You do not know them and any
   you produce would be wrong. The system fills these in from its own records.
4. NEVER invent a tag. If the excerpts do not support a statement, use an empty
   grounding array []. An honest [] is correct and expected; a fabricated tag is
   a serious error.
5. Do not refer to "the excerpts", "the source" or "[S1]" in your prose. The prose
   should read as ordinary teaching notes; citations live only in grounding arrays.

PLANNING RULES.

6. "weight" is a relative share of class time from 1 to 10, NOT minutes. Never
   mention a number of minutes in your prose. The system converts weights to
   minutes that fit the class exactly.
7. Order segments in the sequence they should be taught. Build up: recap and
   prerequisites first, then concepts, with examples and checks placed where they
   reinforce what was just covered.
8. Match the depth to the stated student level and the available class time. A
   shorter class means fewer segments, not the same segments rushed.
9. If something important is genuinely missing or ambiguous - you cannot tell what
   students already know, the topic is too broad for the time given, the material
   does not cover part of the topic - raise it in clarifications_needed rather than
   assuming. Ask only about things that would change the plan. If nothing is
   missing, return an empty array.
"""


def build_prompt(
    *,
    course_title: str,
    course_code: str,
    course_description: str,
    objectives: str,
    student_level: str,
    topic: str,
    duration_min: int,
    seq_no: int,
    notes: str,
    previous_topics: list[str],
    excerpts: list[str],
) -> str:
    """Assemble the user-turn prompt. `excerpts` are pre-numbered [S1]..[Sk]."""
    lines: list[str] = ["## Course", f"Title: {course_title}"]
    if course_code:
        lines.append(f"Code: {course_code}")
    if course_description:
        lines.append(f"Description: {course_description}")
    if objectives:
        lines.append(f"Course objectives: {objectives}")
    lines.append(f"Student level: {student_level or 'NOT SPECIFIED'}")

    lines += [
        "",
        "## This lecture",
        f"Lecture number: {seq_no}",
        f"Topic: {topic}",
        f"Available class time: {duration_min} minutes",
    ]
    if notes:
        lines.append(f"Professor's notes for this lecture: {notes}")
    if previous_topics:
        lines.append("Topics already covered: " + "; ".join(previous_topics))
    else:
        lines.append("Topics already covered: none recorded")

    lines += ["", "## Source excerpts you may cite"]
    if excerpts:
        lines += excerpts
    else:
        lines.append(
            "NONE. The professor has not uploaded material covering this topic, so every "
            "grounding array must be empty, and clarifications_needed should say which "
            "material would help."
        )

    lines += [
        "",
        "## Task",
        f"Produce a lecture plan for the {duration_min}-minute class above. Return JSON "
        "matching the required schema. Remember: cite only by tag, never write a page "
        "number or title, and use weights rather than minutes.",
    ]
    return "\n".join(lines)
