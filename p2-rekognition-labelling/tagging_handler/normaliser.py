"""
Tag Normaliser — P2 Tagging Handler

Converts raw Rekognition label strings (or label dicts) into a canonical list
of clean, unique, lowercase tag strings conforming to the Tag_Schema.

Requirements: 2.3, 2.7
"""

import re
from typing import Union


def normalise_tags(
    labels: list[Union[str, dict]],
) -> list[str]:
    """
    Normalise a list of raw Rekognition labels into canonical tag strings.

    Accepts either plain strings or Rekognition label dicts (with a ``Name``
    key) and applies the following four steps in order:

    1. Lowercase  — ``label.lower()``
    2. Deduplicate — case-insensitive set, preserving first-seen insertion order
    3. Strip non-alphanumeric characters except hyphens and spaces —
       ``re.sub(r'[^a-z0-9\\- ]', '', label)``
    4. Strip leading/trailing whitespace — ``label.strip()``

    Empty strings produced after normalisation are discarded.

    This function is pure: it has no side effects and makes no AWS calls.

    Args:
        labels: A list of raw label values.  Each element may be either:
                - a plain ``str`` (the label text), or
                - a ``dict`` with at least a ``"Name"`` key whose value is
                  the label text (the shape returned by Rekognition
                  ``DetectLabels``).

    Returns:
        A list of clean, unique, lowercase tag strings conforming to the
        Tag_Schema.  The order of the returned tags matches the first
        occurrence of each unique (case-insensitive) label in the input.

    Examples:
        >>> normalise_tags(["Bridge", "bridge", "Concrete Crack"])
        ['bridge', 'concrete crack']

        >>> normalise_tags([{"Name": "Steel Beam"}, {"Name": "steel beam"}])
        ['steel beam']

        >>> normalise_tags(["Hello, World!", "  spaces  "])
        ['hello world', 'spaces']
    """
    seen: set[str] = set()
    result: list[str] = []

    for raw in labels:
        # --- Accept both plain strings and Rekognition label dicts ----------
        if isinstance(raw, dict):
            text: str = raw.get("Name", "")
        else:
            text = str(raw)

        # Step 1: lowercase
        text = text.lower()

        # Step 2: deduplicate (case-insensitive — already lowercased above)
        if text in seen:
            continue
        seen.add(text)

        # Step 3: strip non-alphanumeric characters except hyphens and spaces
        text = re.sub(r"[^a-z0-9\- ]", "", text)

        # Step 4: strip leading/trailing whitespace
        text = text.strip()

        # Discard empty strings produced by normalisation
        if text:
            result.append(text)

    return result
