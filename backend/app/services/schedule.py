"""Week 5: course schedule re-calibration.

Deterministic, no model call. Dates, slots and minutes are arithmetic, and
arithmetic is what language models get wrong - the same reasoning as timealloc.

Two steps, so the professor stays in control:
  propose()  works out the new schedule and changes nothing;
  apply()    writes a proposal to the database.
The REST endpoint previews by default; the professor accepts with apply=true.

Rules:
  - Delivered lectures never move.
  - A missed lecture is still owed: its date is recorded as a no-class date and
    the lecture goes back into the queue in its original order.
  - Remaining lectures keep their order and take the next available class dates.
  - If they no longer fit before the course end date, adjacent lectures holding
    the least material are merged (at most MAX_TOPICS_PER_CLASS per class). The
    merged plans are concatenated and re-apportioned to the class length.
  - Spare class dates are reported, never filled with invented topics.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_HORIZON_DAYS = 730  # when the course has no end date
MAX_TOPICS_PER_CLASS = 3


class ScheduleError(ValueError):
    """Re-calibration cannot proceed. The message is meant for the professor."""


@dataclass
class Group:
    """One class slot's worth of lectures. Usually one lecture; more after a merge."""

    lecture_ids: list[int]
    seq_nos: list[int]
    topics: list[str]
    content_min: int  # sum of the original durations: how much material it holds
    old_date: date | None
    old_duration: int
    new_date: date | None = None
    new_duration: int = 0

    @property
    def merged(self) -> bool:
        return len(self.lecture_ids) > 1

    @property
    def changed(self) -> bool:
        return (
            self.merged
            or self.old_date != self.new_date
            or self.old_duration != self.new_duration
        )


@dataclass
class Proposal:
    from_date: date
    new_blocked: list[dict]  # [{"date": "YYYY-MM-DD", "reason": str}] to add
    groups: list[Group]
    spare_dates: list[date]
    available_slots: int | None  # None when the course has no end date
    new_duration_min: int | None
    warnings: list[str] = field(default_factory=list)


# --- Pure helpers ----------------------------------------------------------------

def parse_blocked(raw) -> dict[date, str]:
    """Course.blocked_dates (JSON) -> {date: reason}. Malformed entries are skipped."""
    out: dict[date, str] = {}
    for item in raw or []:
        try:
            out[date.fromisoformat(str(item["date"]))] = str(item.get("reason", ""))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def class_dates(
    start: date,
    end: date | None,
    meeting_days: list[int],
    blocked: set[date] | dict,
    limit: int | None = None,
) -> list[date]:
    """Every date from start to end (inclusive) the course meets, minus blocked ones.

    With no end date, stops after `limit` dates (or the horizon).
    """
    days = set(meeting_days)
    if not days:
        return []
    stop = end or (start + timedelta(days=MAX_HORIZON_DAYS))
    out: list[date] = []
    current = start
    while current <= stop:
        if current.weekday() in days and current not in blocked:
            out.append(current)
            if end is None and limit is not None and len(out) >= limit:
                break
        current += timedelta(days=1)
    return out


def merge_to_fit(groups: list[Group], slots: int) -> list[Group]:
    """Merge adjacent groups until there are at most `slots` of them.

    Each step merges the adjacent pair holding the least material. Ties go to the
    later pair, so the lectures coming up soonest are disturbed last.
    """
    groups = list(groups)
    while len(groups) > max(slots, 0):
        best: tuple[int, int] | None = None
        for i in range(len(groups) - 1):
            a, b = groups[i], groups[i + 1]
            if len(a.lecture_ids) + len(b.lecture_ids) > MAX_TOPICS_PER_CLASS:
                continue
            cost = a.content_min + b.content_min
            if best is None or cost <= best[0]:
                best = (cost, i)
        if best is None:
            break  # nothing left that can be merged within the cap
        i = best[1]
        a, b = groups[i], groups[i + 1]
        groups[i : i + 2] = [
            Group(
                lecture_ids=a.lecture_ids + b.lecture_ids,
                seq_nos=a.seq_nos + b.seq_nos,
                topics=a.topics + b.topics,
                content_min=a.content_min + b.content_min,
                old_date=a.old_date,
                old_duration=a.old_duration,
            )
        ]
    return groups


def propose(course, lectures, request, today: date) -> Proposal:
    """Work out the re-calibrated schedule. Reads only; writes nothing.

    `request` needs: from_date, blocked_dates (items with .date and .reason),
    missed_seq_nos, new_duration_min.
    """
    meeting_days = sorted(set(course.meeting_days or []))
    if not meeting_days:
        raise ScheduleError(
            "I need to know which days of the week this course meets before I can "
            "schedule it. Set the class days in the course schedule."
        )
    if course.start_date is None:
        raise ScheduleError("Set the course start date before scheduling.")

    start = max(request.from_date or today, course.start_date)
    if course.end_date is not None and course.end_date < start:
        raise ScheduleError(
            f"The course ends on {course.end_date.isoformat()}, before "
            f"{start.isoformat()}, so there is nothing left to schedule."
        )

    warnings: list[str] = []
    blocked = parse_blocked(course.blocked_dates)
    new_blocked: list[dict] = []

    def block(day: date, reason: str) -> None:
        if day not in blocked:
            blocked[day] = reason
            new_blocked.append({"date": day.isoformat(), "reason": reason})

    for item in request.blocked_dates or []:
        block(item.date, item.reason or "no class")

    ordered = sorted(lectures, key=lambda l: l.seq_no)
    by_seq = {l.seq_no: l for l in ordered}
    missed = set(request.missed_seq_nos or [])
    for seq in sorted(missed):
        lec = by_seq.get(seq)
        if lec is None:
            raise ScheduleError(f"There is no lecture {seq} in this course.")
        if lec.status == "delivered":
            raise ScheduleError(
                f"Lecture {seq} is marked as delivered. Un-mark it first if it did "
                "not actually happen."
            )
        if lec.scheduled_date is None:
            warnings.append(
                f"Lecture {seq} had no date, so there was no class to mark as missed."
            )
            continue
        block(lec.scheduled_date, f"missed class (lecture {seq})")

    remaining: list[Group] = []
    for lec in ordered:
        if lec.status != "planned":
            continue
        if (
            lec.scheduled_date is not None
            and lec.scheduled_date < start
            and lec.seq_no not in missed
        ):
            warnings.append(
                f"Lecture {lec.seq_no} ({lec.topic}) was dated "
                f"{lec.scheduled_date.isoformat()} but is not marked delivered; "
                "I left it where it is. Mark it delivered or missed."
            )
            continue
        remaining.append(
            Group(
                lecture_ids=[lec.id],
                seq_nos=[lec.seq_no],
                topics=[lec.topic],
                content_min=lec.duration_min,
                old_date=lec.scheduled_date,
                old_duration=lec.duration_min,
            )
        )

    # Dates already used by lectures that are not moving (delivered, or left
    # in place) are not free for the ones that are.
    moving = {g.lecture_ids[0] for g in remaining}
    taken = {
        lec.scheduled_date
        for lec in ordered
        if lec.scheduled_date is not None
        and lec.id not in moving
        and lec.status in ("delivered", "planned")
    }
    slots = class_dates(
        start, course.end_date, meeting_days, set(blocked) | taken, limit=len(remaining)
    )
    groups = remaining
    if course.end_date is not None and len(remaining) > len(slots):
        groups = merge_to_fit(remaining, len(slots))
        if len(groups) > len(slots):
            left = [s for g in groups[len(slots):] for s in g.seq_nos]
            warnings.append(
                f"Even with up to {MAX_TOPICS_PER_CLASS} topics per class, lectures "
                f"{', '.join(map(str, left))} do not fit before "
                f"{course.end_date.isoformat()}. They are left without a date - "
                "extend the course, add class days, or drop topics."
            )

    for index, group in enumerate(groups):
        group.new_date = slots[index] if index < len(slots) else None
        group.new_duration = request.new_duration_min or group.old_duration
        if group.merged:
            warnings.append(
                f"Lectures {', '.join(map(str, group.seq_nos))} now share one class "
                f"({group.content_min} min of planned material in "
                f"{group.new_duration} min). Review the combined plan."
            )

    spare = slots[len(groups):] if course.end_date is not None else []
    if spare:
        warnings.append(
            f"{len(spare)} class date(s) at the end are free. I did not invent topics "
            "for them - use them for revision or add lectures."
        )

    return Proposal(
        from_date=start,
        new_blocked=new_blocked,
        groups=groups,
        spare_dates=spare,
        available_slots=len(slots) if course.end_date is not None else None,
        new_duration_min=request.new_duration_min,
        warnings=warnings,
    )


def summarize(proposal: Proposal, applied: bool) -> str:
    """Plain-language account of a proposal, for the chat."""
    head = "Re-calibrated the schedule." if applied else "Preview only - nothing changed yet."
    lines = [head]
    for b in proposal.new_blocked:
        lines.append(f"No class on {b['date']} ({b['reason']}).")
    moved = [g for g in proposal.groups if g.changed]
    for g in moved[:12]:
        old = g.old_date.isoformat() if g.old_date else "no date"
        new = g.new_date.isoformat() if g.new_date else "no date"
        what = " + ".join(g.topics)
        nums = "/".join(map(str, g.seq_nos))
        dur = (
            f", {g.old_duration}->{g.new_duration} min"
            if g.old_duration != g.new_duration
            else ""
        )
        lines.append(f"Lecture {nums} ({what}): {old} -> {new}{dur}.")
    if len(moved) > 12:
        lines.append(f"...and {len(moved) - 12} more.")
    if not moved and not proposal.new_blocked:
        lines.append("No lecture needed to move.")
    lines += proposal.warnings
    return " ".join(lines)


# --- Writing a proposal ---------------------------------------------------------

def apply(db, course, proposal: Proposal) -> None:
    """Write a proposal. Plans are re-apportioned so they fit the new class lengths."""
    from app.models import Lecture
    from app.services import plan_edits

    existing = list(course.blocked_dates or [])
    combined = existing + proposal.new_blocked
    course.blocked_dates = sorted(combined, key=lambda b: str(b.get("date", "")))
    if proposal.new_duration_min:
        course.lecture_duration_min = proposal.new_duration_min

    rebalance_later: list = []
    for group in proposal.groups:
        survivor = db.get(Lecture, group.lecture_ids[0])
        duration_changed = survivor.duration_min != group.new_duration
        survivor.scheduled_date = group.new_date
        survivor.duration_min = group.new_duration
        if group.merged:
            absorbed = [db.get(Lecture, i) for i in group.lecture_ids[1:]]
            _merge(db, survivor, absorbed)
        elif duration_changed:
            rebalance_later.append(survivor)
    db.commit()

    # apply_plan_edits with no edits = re-apportion to the lecture's duration,
    # stored as a new plan version.
    for lecture in rebalance_later:
        if plan_edits.latest_plan(db, lecture.id) is not None:
            plan_edits.apply_plan_edits(db, lecture, [], [])


def _merge(db, survivor, absorbed: list) -> None:
    """Fold `absorbed` lectures into `survivor`, combining their plans."""
    from app.models import LecturePlan, PlanItem
    from app.services.plan_edits import latest_plan, rebalance

    group = [survivor, *absorbed]
    plans = [latest_plan(db, lec.id) for lec in group]

    survivor.topic = " + ".join(lec.topic for lec in group)[:500]
    extra_notes = [lec.notes for lec in absorbed if lec.notes]
    if extra_notes:
        survivor.notes = "\n".join([survivor.notes, *extra_notes]).strip()
    for lec in absorbed:
        lec.status = "merged"
        lec.scheduled_date = None
        lec.notes = (
            f"{lec.notes}\nMerged into lecture {survivor.seq_no} when the schedule "
            "was re-calibrated."
        ).strip()

    segments: list[dict] = []
    chunk_ids: list[int] = []
    for plan in plans:
        if plan is None:
            continue
        segments += copy.deepcopy(plan.plan_json.get("segments") or [])
        for cid in plan.retrieved_chunk_ids or []:
            if cid not in chunk_ids:
                chunk_ids.append(cid)
    if not segments:
        return  # nothing planned yet; the professor generates a plan as usual

    for ordinal, segment in enumerate(segments, start=1):
        segment["ordinal"] = ordinal
    rebalance(segments, survivor.duration_min, pinned=set())

    current = plans[0]
    base = current or next(p for p in plans if p is not None)
    plan_json = copy.deepcopy(base.plan_json)
    plan_json.update(
        topic=survivor.topic,
        segments=segments,
        duration_min=survivor.duration_min,
        total_allocated_min=sum(s.get("minutes", 0) for s in segments),
    )

    new_plan = LecturePlan(
        lecture_id=survivor.id,
        version=(current.version + 1) if current else 1,
        plan_json=plan_json,
        model=f"{base.model} + schedule merge",
        retrieved_chunk_ids=chunk_ids,
    )
    db.add(new_plan)
    db.flush()
    for segment in segments:
        db.add(
            PlanItem(
                plan_id=new_plan.id,
                ordinal=segment["ordinal"],
                kind=segment.get("kind", "concept"),
                title=segment.get("title", ""),
                body=segment.get("body", ""),
                minutes=segment.get("minutes", 0),
                grounding=segment.get("grounding") or [],
                edited_by_professor=bool(segment.get("edited_by_professor")),
            )
        )


def lectures_of(db, course_id: int) -> list:
    """Fresh read of a course's lectures (the ORM collection can be stale)."""
    from sqlalchemy import select

    from app.models import Lecture

    return list(
        db.execute(select(Lecture).where(Lecture.course_id == course_id)).scalars()
    )