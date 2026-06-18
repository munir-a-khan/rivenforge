"""
Pure-Python TF-IDF embedding — zero DLL dependencies, zero downloads.

Replaces sentence-transformers and ONNX entirely.
Works perfectly for short riven stat text (weapon names, stat names).

Since all riven knowledge is structured text (weapon → stats),
TF-IDF cosine similarity is as good as a neural embedder for this use case.
"""

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, remove blanks."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


class TFIDFEmbedder:
    """
    Build a TF-IDF vocabulary from a corpus then embed new strings.
    Call fit(corpus) first, then embed(texts).
    """

    def __init__(self):
        self._idf: dict[str, float] = {}
        self._vocab: list[str] = []
        self._fitted = False

    def fit(self, corpus: list[str]):
        """Build IDF weights from corpus."""
        N = len(corpus)
        df: Counter = Counter()
        for doc in corpus:
            tokens = set(_tokenize(doc))
            df.update(tokens)
        self._idf = {t: math.log((N + 1) / (n + 1)) + 1 for t, n in df.items()}
        self._vocab = sorted(self._idf)
        self._fitted = True

    def _vec(self, text: str) -> list[float]:
        tokens = _tokenize(text)
        tf = Counter(tokens)
        total = max(sum(tf.values()), 1)
        vec = []
        for term in self._vocab:
            tfidf = (tf[term] / total) * self._idf.get(term, 0)
            vec.append(tfidf)
        # L2-normalise
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._fitted:
            raise RuntimeError("Call fit() before embed()")
        return [self._vec(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def cosine(self, a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))  # already normalised


# Module-level singleton built lazily when ingest runs
_global_embedder: TFIDFEmbedder | None = None


def get_embedder() -> TFIDFEmbedder:
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = TFIDFEmbedder()
    return _global_embedder


def reset_embedder():
    global _global_embedder
    _global_embedder = None
