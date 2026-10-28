"""Local vector embedding and cosine similarity computation (Requirement L1)."""

import math
import re
from typing import Dict, List, Tuple


TOKEN_PATTERN = re.compile(r"[a-z0-9_\-]+")


class LocalTextEmbedder:
    """
    Self-contained, offline vector embedder.
    Computes normalized sub-word / TF-IDF semantic embeddings with zero external API dependencies.
    """

    def __init__(self):
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}

    def fit_and_embed(self, texts: List[str]) -> List[List[float]]:
        # 1. Build document frequency
        doc_freq: Dict[str, int] = {}
        total_docs = len(texts)

        tokenized_docs = []
        for text in texts:
            tokens = set(TOKEN_PATTERN.findall(text.lower()))
            tokenized_docs.append(tokens)
            for t in tokens:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        # 2. Select top vocabulary
        sorted_vocab = sorted(doc_freq.keys())
        self.vocabulary = {term: idx for idx, term in enumerate(sorted_vocab)}

        # 3. Compute IDF
        for term, df in doc_freq.items():
            self.idf[term] = math.log((total_docs + 1.0) / (df + 1.0)) + 1.0

        # 4. Compute normalized vectors
        vectors = []
        for text in texts:
            vec = self.embed_query(text)
            vectors.append(vec)

        return vectors

    def embed_query(self, query: str) -> List[float]:
        dim = len(self.vocabulary)
        if dim == 0:
            return []

        tokens = TOKEN_PATTERN.findall(query.lower())
        if not tokens:
            return [0.0] * dim

        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0.0) + 1.0

        vec = [0.0] * dim
        norm_sq = 0.0

        for t, count in tf.items():
            if t in self.vocabulary:
                idx = self.vocabulary[t]
                weight = (1.0 + math.log(count)) * self.idf.get(t, 1.0)
                vec[idx] = weight
                norm_sq += weight * weight

        # Normalize to unit length
        if norm_sq > 0:
            inv_norm = 1.0 / math.sqrt(norm_sq)
            vec = [v * inv_norm for v in vec]

        return vec

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        return sum(a * b for a, b in zip(vec_a, vec_b))
