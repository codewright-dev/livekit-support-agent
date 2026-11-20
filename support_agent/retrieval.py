"""Small, dependency-free retrieval over a Markdown manual.

Sections are split on Markdown headings and ranked with BM25. For a single product manual this is fast
(< 1 ms per query), needs no embedding API, and is easy to test. Swap in a vector store when the
knowledge base grows to thousands of documents.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_STOP = set(
    "a an the and or of to in on for with is are be it its my me i you your do does did can how what why "
    "when where which this that there was were not no at by from as if into up out".split()
)
_SYNONYMS = {
    "wifi": "wi-fi",
    "internet": "wi-fi",
    "router": "wi-fi",
    "light": "status",
    "led": "status",
    "blinking": "status",
    "flashing": "status",
    "reboot": "restart",
    "refund": "returns",
    "guarantee": "warranty",
    "error": "code",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())
    out = []
    for w in words:
        w = _SYNONYMS.get(w, w)
        if w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us")):  # cheap plural folding
            w = w[:-1]
        out.append(w)
    return out


@dataclass
class Section:
    title: str
    text: str


def split_sections(markdown: str) -> list[Section]:
    sections: list[Section] = []
    title, lines = "Overview", []
    for line in markdown.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", line)
        if m:
            if any(l.strip() for l in lines):
                sections.append(Section(title, "\n".join(lines).strip()))
            title, lines = m.group(1).strip(), []
        else:
            lines.append(line)
    if any(l.strip() for l in lines):
        sections.append(Section(title, "\n".join(lines).strip()))
    return sections


class ManualIndex:
    def __init__(self, sections: list[Section], k1: float = 1.4, b: float = 0.75):
        self.sections = sections
        # Titles count twice: they are strong topic signals.
        self.docs = [tokenize(f"{s.title} {s.title} {s.text}") for s in sections]
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    @classmethod
    def from_file(cls, path: str | Path) -> "ManualIndex":
        return cls(split_sections(Path(path).read_text(encoding="utf-8")))

    def search(self, query: str, top_k: int = 2) -> list[tuple[Section, float]]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                weight = 3.0 if re.fullmatch(r"e\d", t) else 1.0  # an exact error code is the strongest signal
                s += weight * self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            scores.append((self.sections[i], s))
        ranked = sorted((x for x in scores if x[1] > 0), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
