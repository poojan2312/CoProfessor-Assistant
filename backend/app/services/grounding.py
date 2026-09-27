"""Enforcement of the citation contract.

The model may only cite by opaque tag - S1, S2, ... Sk - where Sn refers to the
nth chunk placed in its retrieval window. It never sees or writes a page number,
title, author or URL.

Everything here is a pure function over plain data: no LLM call, no database, no
network. That is deliberate. The guarantee the professor is being asked to trust
must be checkable by reading this file and running a unit test, not by trusting a
second model to audit the first one.

Enforcement is structural rather than a list of known fields:

    any dict carrying a "grounding" list is a citable item, wherever it appears

An earlier version walked a hard-coded tuple of field names, which meant a new
citable field in a response schema silently bypassed enforcement until someone
remembered to register it - a bug this codebase hit once already. Walking the
response instead makes that class of mistake impossible, and lets lecture plans,
chat replies and teaching-support content share one implementation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TAG_RE = re.compile(r"^S(\d+)$")

GROUNDING_KEY = "grounding"


@dataclass
class TagCheck:
    valid: list[int] = field(default_factory=list)  # 1-based indices into the window
    invalid: list[str] = field(default_factory=list)  # raw tags that failed


def check_tags(raw_tags: Any, window_size: int) -> TagCheck:
    """Split a model-supplied tag list into valid indices and rejects.

    A tag is valid only if it is literally "S<n>" with 1 <= n <= window_size.
    Anything else - a fabricated S99, a prose citation, a page number the model
    tried to sneak in - lands in `invalid` and is never rendered.
    """
    result = TagCheck()
    if not isinstance(raw_tags, list):
        return result

    seen: set[int] = set()
    for tag in raw_tags:
        match = TAG_RE.match(tag.strip()) if isinstance(tag, str) else None
        if match is None:
            result.invalid.append(str(tag))
            continue
        idx = int(match.group(1))
        if not 1 <= idx <= window_size:
            result.invalid.append(str(tag))
            continue
        if idx not in seen:
            seen.add(idx)
            result.valid.append(idx)
    return result


def _is_citable(node: Any) -> bool:
    return isinstance(node, dict) and isinstance(node.get(GROUNDING_KEY), list)


def audit(response: Any, window_size: int) -> list[str]:
    """Return every invalid tag anywhere in a model response.

    An empty list means every citation in the response points at a passage that
    was genuinely retrieved.
    """
    invalid: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_citable(node):
                invalid.extend(check_tags(node[GROUNDING_KEY], window_size).invalid)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(response)
    return invalid


def resolve(indices: list[int], window_chunk_ids: list[int]) -> list[int]:
    """Map 1-based S-tag indices to real chunk ids."""
    return [window_chunk_ids[i - 1] for i in indices if 1 <= i <= len(window_chunk_ids)]


def scrub(response: Any, window_chunk_ids: list[int]) -> Any:
    """Rewrite every S-tag into a chunk id, dropping invalid citations.

    Returns a copy; the input is not mutated. An item whose citations were all
    fabricated survives as content with empty grounding, which the UI shows as an
    unsourced model suggestion rather than silently passing it off as cited.
    """
    window_size = len(window_chunk_ids)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {key: walk(value) for key, value in node.items()}
            if _is_citable(node):
                check = check_tags(node[GROUNDING_KEY], window_size)
                out[GROUNDING_KEY] = resolve(check.valid, window_chunk_ids)
            return out
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node

    return walk(response)


def cited_chunk_ids(response: Any) -> list[int]:
    """Every chunk id referenced anywhere in an already-scrubbed response."""
    found: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_citable(node):
                found.update(i for i in node[GROUNDING_KEY] if isinstance(i, int))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(response)
    return sorted(found)
