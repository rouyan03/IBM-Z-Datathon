#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
legal_xml_search.py
- Keyword search (BM25) over a SINGLE XML file.
- Each XML element with an `id` attribute is a searchable unit.
- Outputs slide-style XML-like results.

No external dependencies. Windows/macOS/Linux compatible.
"""

import math, re, sys
from typing import Dict, List, Tuple
from xml.etree import ElementTree as ET

# ---------- tiny utils ----------
TOK = re.compile(r"[A-Za-z0-9_]+")

def tok(s: str) -> List[str]:
    return [t.lower() for t in TOK.findall(s or "")]

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def snippet(text: str, query: str, win: int = 160) -> str:
    q = [t for t in tok(query) if len(t) >= 2]
    if not q:
        s = text[:win].strip()
        return s + (" ..." if len(text) > win else "")
    low = text.lower()
    hits = [low.find(t) for t in q if low.find(t) != -1]
    pos = min(hits) if hits else 0
    start = max(0, pos - win // 3)
    end = min(len(text), start + win)
    s = text[start:end].strip()
    return s + (" ..." if end < len(text) else "")

# ---------- load single XML ----------
def load_id2text(xml_path: str) -> Dict[str, str]:
    id2text: Dict[str, str] = {}
    try:
        for _, elem in ET.iterparse(xml_path, events=("end",)):
            pid = elem.attrib.get("id")
            if pid:
                txt = norm("".join(elem.itertext()))
                if txt:
                    id2text[pid] = txt
            elem.clear()
    except Exception as e:
        print(f"[ERROR] Failed to parse XML: {e}", file=sys.stderr)
        sys.exit(1)
    if not id2text:
        print("[ERROR] No elements with id= found in the XML.", file=sys.stderr)
        sys.exit(2)
    return id2text

# ---------- BM25 ----------
class BM25:
    def __init__(self, id2text: Dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.id2text = id2text
        self.k1, self.b = k1, b
        self.id2toks: Dict[str, List[str]] = {}
        self.df: Dict[str, int] = {}
        total = 0
        for pid, txt in id2text.items():
            dt = tok(txt)
            self.id2toks[pid] = dt
            total += len(dt)
            for w in set(dt):
                self.df[w] = self.df.get(w, 0) + 1
        self.N = max(1, len(id2text))
        self.avgdl = total / self.N
        self.idf = {w: math.log((self.N - d + 0.5) / (d + 0.5) + 1e-12) for w, d in self.df.items()}

    def score(self, q: List[str], d: List[str]) -> float:
        if not q or not d:
            return 0.0
        tf: Dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        dl = len(d)
        s = 0.0
        for w in q:
            f = tf.get(w, 0)
            if f == 0:
                continue
            idf = self.idf.get(w, 0.0)
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl + 1e-12))
            s += idf * ((f * (self.k1 + 1)) / (denom + 1e-12))
        return float(s)

    def search(self, query: str, topk: int = 3) -> List[Tuple[str, float]]:
        q = tok(query)
        scored: List[Tuple[str, float]] = []
        for pid, dt in self.id2toks.items():
            s = self.score(q, dt)
            if s > 0:
                scored.append((pid, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:topk]

# ---------- Main search function ----------
def keyword_search(xml_file: str, keywords: str, n: int = 3) -> str:
    """
    Perform BM25 keyword search on an XML file.
    
    Args:
        xml_file: Path to XML file (e.g., "./normalized_enhanced.xml")
        keywords: Search query string (e.g., "assault")
        n: Number of top results to return (default: 3)
    
    Returns:
        XML-formatted results as a string
    """
    id2text = load_id2text(xml_file)
    bm25 = BM25(id2text)
    hits = bm25.search(keywords, topk=n)

    # slide-style XML output
    lines = [f'<results num="{len(hits)}">']
    for pid, score in hits:
        lines += [
            f'  <result id="{pid}" score="{score:.3f}">',
            f"    {xml_escape(snippet(id2text.get(pid, ''), keywords))}",
            "  </result>",
        ]
    lines.append("</results>")
    return "\n".join(lines)

if __name__ == "__main__":
    # Example usage:
    result = keyword_search("./normalized_enhanced.xml", "assault", 3)
    print(result)