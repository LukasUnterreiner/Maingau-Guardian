"""Derive the Du/Sie tonality from the customer's own words.

The README states tonality is not labelled and must be derived. We only look at
text written or spoken by the customer (ticket messages and the "Kunde:" lines
of call transcripts). If there is no signal we fall back to the formal "Sie",
which is the safe default for an unsolicited German business communication.
The fallback is reported explicitly as ``source = "default_formal"``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_INFORMAL = [
    r"\bdu\b", r"\bdir\b", r"\bdich\b", r"\bdein\w*", r"\beuch\b", r"\beuer\b", r"\beure\w*",
    r"\bihr\b", r"\bHey\b", r"\bHi\b", r"\btschüss\b", r"\bdanke dir\b", r"\bLG\b", r"\bnervig\b",
]
_FORMAL = [
    r"\bSie\b", r"\bIhnen\b", r"\bIhre[nmrs]?\b", r"Sehr geehrte", r"[Mm]it freundlichen Grüßen",
    r"Freundliche Grüße", r"auf Wiederhören", r"Guten Tag",
]
_INFORMAL_RE = [re.compile(p) for p in _INFORMAL]
_FORMAL_RE = [re.compile(p) for p in _FORMAL]


@dataclass(frozen=True)
class Tonality:
    value: str  # "du" | "sie"
    source: str  # "derived_from_customer_text" | "default_formal"
    informal_signals: int
    formal_signals: int
    texts_analysed: int


def customer_lines_from_transcript(transcript: str) -> str:
    return "\n".join(line.split(":", 1)[1] for line in transcript.splitlines()
                     if line.strip().lower().startswith("kunde:") and ":" in line)


def derive_tonality(texts: list[str]) -> Tonality:
    texts = [t for t in texts if t and t.strip()]
    inf = sum(len(r.findall(t)) for t in texts for r in _INFORMAL_RE)
    form = sum(len(r.findall(t)) for t in texts for r in _FORMAL_RE)
    if not texts or inf == form:
        return Tonality("sie", "default_formal", inf, form, len(texts))
    return Tonality("du" if inf > form else "sie", "derived_from_customer_text", inf, form, len(texts))
