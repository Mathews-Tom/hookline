"""Pure-Python TF-IDF text similarity search."""
from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must", "am",
    "and", "but", "or", "nor", "not", "no", "so", "if", "then",
    "than", "too", "very", "just", "about", "above", "after", "again",
    "all", "also", "any", "as", "at", "back", "because", "before",
    "between", "both", "by", "each", "for", "from", "get", "got",
    "he", "her", "here", "him", "his", "how", "in", "into", "it",
    "its", "let", "me", "more", "most", "my", "of", "on", "one",
    "only", "or", "other", "our", "out", "over", "own", "same",
    "she", "some", "still", "such", "that", "their", "them",
    "there", "these", "they", "this", "those", "through", "to",
    "under", "up", "us", "we", "what", "when", "where", "which",
    "while", "who", "whom", "why", "with", "you", "your",
})

_WORD_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, remove stopwords and short tokens."""
    words = _WORD_PATTERN.findall(text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


class TfIdfSearcher:
    """In-memory TF-IDF document index with cosine similarity search."""

    def __init__(self) -> None:
        self._docs: dict[int, Counter[str]] = {}
        self._doc_lengths: dict[int, int] = {}
        self._df: Counter[str] = Counter()

    def add_document(self, doc_id: int, text: str) -> None:
        """Tokenize and index a document."""
        tokens = tokenize(text)
        if not tokens:
            return
        tf = Counter(tokens)
        self._docs[doc_id] = tf
        self._doc_lengths[doc_id] = len(tokens)
        for term in tf:
            self._df[term] += 1

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Search for documents similar to query. Returns (doc_id, score) pairs."""
        tokens = tokenize(query)
        if not tokens or not self._docs:
            return []

        n = len(self._docs)
        query_tf = Counter(tokens)
        query_len = len(tokens)

        # Build query TF-IDF vector
        query_vec: dict[str, float] = {}
        for term, count in query_tf.items():
            df = self._df.get(term, 0)
            if df == 0:
                continue
            tf = count / query_len
            idf = math.log(n / (1 + df))
            query_vec[term] = tf * idf

        if not query_vec:
            return []

        # Score each document by cosine similarity
        query_mag = math.sqrt(sum(v * v for v in query_vec.values()))
        scores: list[tuple[int, float]] = []

        for doc_id, doc_tf in self._docs.items():
            doc_len = self._doc_lengths[doc_id]
            dot_product = 0.0
            doc_mag_sq = 0.0

            for term, count in doc_tf.items():
                df = self._df.get(term, 0)
                tf = count / doc_len
                idf = math.log(n / (1 + df))
                tfidf = tf * idf
                doc_mag_sq += tfidf * tfidf

                if term in query_vec:
                    dot_product += query_vec[term] * tfidf

            if dot_product <= 0 or doc_mag_sq <= 0:
                continue

            doc_mag = math.sqrt(doc_mag_sq)
            similarity = dot_product / (query_mag * doc_mag)
            scores.append((doc_id, similarity))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def clear(self) -> None:
        """Remove all indexed documents."""
        self._docs.clear()
        self._doc_lengths.clear()
        self._df.clear()
