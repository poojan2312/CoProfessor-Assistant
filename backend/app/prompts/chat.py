"""The professor's chat turn.

One structured call per turn returns everything at once: what to say, what it is
grounded in, and what to do. The backend then executes the action deterministically
through the same validation the REST API uses.

Not an agentic tool loop, deliberately. The free tier allows five generate requests
per minute, and a loop would spend that budget on a single exchange. One call per
turn also keeps the thing auditable: for every reply there is exactly one model
response on record.
"""
from __future__ import annotations

ACTIONS = [
    "none",
    "update_lecture",
    "create_lecture",
    "generate_plan",
    "edit_segments",
    "drop_segments",
    "update_course",
    "generate_teaching_support",
    "recommend_resources",
]

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "What to say to the professor. Plain prose, no markdown headings.",
        },
        "grounding": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Source tags supporting the reply, e.g. S1. Empty if none do.",
        },
        "action": {"type": "string", "enum": ACTIONS},
        "args": {
            "type": "object",
            "description": "Arguments for the action. Omit every field you are not setting.",
            "properties": {
                "topic": {"type": "string"},
                "duration_min": {"type": "integer"},
                "notes": {"type": "string"},
                "student_level_override": {"type": "string"},
                "title": {"type": "string"},
                "code": {"type": "string"},
                "objectives": {"type": "string"},
                "student_level": {"type": "string"},
                "lecture_duration_min": {"type": "integer"},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ordinal": {"type": "integer"},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "kind": {"type": "string"},
                            "minutes": {"type": "integer"},
                        },
                        "required": ["ordinal"],
                    },
                },
                "drop_ordinals": {"type": "array", "items": {"type": "integer"}},
                "resources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["book", "paper", "video", "web"]},
                            "identifier": {"type": "string", "description": "ISBN for books, DOI for papers, URL for web, YouTube URL/ID for videos"},
                            "title": {"type": "string"},
                            "authors": {"type": "string"}
                        },
                        "required": ["kind", "identifier", "title"]
                    }
                }
            },
        },
        "clarification": {
            "type": "string",
            "description": "A question to ask instead of guessing. Empty when nothing is missing.",
        },
    },
    "required": ["reply", "grounding", "action", "args", "clarification"],
}


SYSTEM_INSTRUCTION = """You are a co-professor assisting a university teacher through chat.
You are talking to an expert in their own subject. Be direct and brief - two or
three sentences unless they asked for something longer. No preamble, no flattery.

CITATION RULES - these are absolute.

1. Excerpts from the professor's own uploaded material are labelled [S1], [S2] and
   so on. These are the ONLY sources you may cite.
2. Cite by putting tags in "grounding", for example ["S2"].
3. NEVER write a page number, section number, book title, author name, URL or video
   title. You do not know them. The system adds the real reference from its records.
4. NEVER invent a tag. If the excerpts do not answer the question, say so plainly
   and leave grounding empty. Saying "your uploaded material does not cover this,
   but generally..." is a good answer. A fabricated citation is a serious error.
5. Do not mention "the excerpts" or "[S1]" in your prose.

DOING THINGS.

6. When the professor asks you to change something, set "action" and fill "args"
   with ONLY the fields that change. Do it rather than describing how they could.
     - update_lecture: topic, duration_min, notes, student_level_override
     - create_lecture: topic, and duration_min if they said one
     - generate_plan: no args - use when they want a plan made or remade
     - edit_segments: segments [{ordinal, title?, body?, kind?, minutes?}]
     - drop_segments: drop_ordinals [n]
     - update_course: title, code, objectives, student_level, lecture_duration_min
     - generate_teaching_support: no args - examples, activities, explanations
     - recommend_resources: resources [{kind, identifier, title, authors?}] - suggest external resources. Never use for local uploads.
7. Use "none" for questions, discussion and drafting. Most turns are "none".
8. Segment numbers are the ordinals shown in the plan you were given. Never guess
   an ordinal that is not in it.
9. Never set minutes so they no longer fit the class; the system re-balances the
   remaining time, so change only what they asked about.
10. In "reply", state what you changed in the past tense, briefly: "Set the lecture
    to 90 minutes." Do not promise to do it - it is already done by the time they
    read this.

ASKING BACK.

11. If an instruction is genuinely ambiguous - which lecture, which segment, a
    topic too broad for the time given - put a single question in "clarification",
    set action to "none", and do not guess. Only ask when the answer would change
    what you do. Leave it empty otherwise.
"""


def build_prompt(
    *,
    course_title: str,
    course_code: str,
    objectives: str,
    student_level: str,
    lectures: list[str],
    focus_lecture: str | None,
    plan_outline: list[str],
    has_support: bool,
    history: list[tuple[str, str]],
    message: str,
    excerpts: list[str],
) -> str:
    """Assemble the user turn. `history` is [(role, content)] oldest first."""
    lines = ["## Course", f"Title: {course_title}"]
    if course_code:
        lines.append(f"Code: {course_code}")
    if objectives:
        lines.append(f"Objectives: {objectives}")
    lines.append(f"Student level: {student_level or 'NOT SPECIFIED'}")

    lines += ["", "## Lectures in this course"]
    lines += [f"  {line}" for line in lectures] if lectures else ["  none yet"]

    lines += ["", "## Lecture currently open"]
    if focus_lecture:
        lines.append(focus_lecture)
        if plan_outline:
            lines.append("Its plan:")
            lines += [f"  {line}" for line in plan_outline]
        else:
            lines.append("No plan generated for it yet.")
        lines.append(
            f"Teaching support: {'already generated' if has_support else 'not generated yet'}"
        )
    else:
        lines.append(
            "None. If the professor refers to 'this lecture', ask which one."
        )

    if history:
        lines += ["", "## Conversation so far"]
        for role, content in history:
            who = "Professor" if role == "professor" else "You"
            lines.append(f"{who}: {content}")

    lines += ["", "## Source excerpts you may cite"]
    lines += excerpts or [
        "NONE relevant to this message. Leave grounding empty.",
    ]

    lines += ["", "## The professor's message", message]
    return "\n".join(lines)
