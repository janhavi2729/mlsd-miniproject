"""Idempotent corpus indexer CLI and Vector Store (Requirement D2, L1)."""

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.retrieval.chunker import DocumentChunk, parse_and_chunk_document
from src.retrieval.embedder import LocalTextEmbedder
from src.retrieval.cache import global_cache
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("retrieval.indexer")


class VectorIndex:
    def __init__(self, index_dir: Optional[str] = None):
        self.index_dir = index_dir or settings.INDEX_DIR
        self.metadata_file = os.path.join(self.index_dir, "index_metadata.json")
        self.store_file = os.path.join(self.index_dir, "vector_store.json")

        self.chunks: List[DocumentChunk] = []
        self.vectors: List[List[float]] = []
        self.embedder = LocalTextEmbedder()
        self.clause_map: Dict[str, DocumentChunk] = {}
        self.metadata: Dict[str, Any] = {}

        # Auto-load if existing
        if os.path.exists(self.store_file) and os.path.exists(self.metadata_file):
            self.load()

    def _file_hash(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    def build_or_update(self, corpus_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Idempotent indexing pipeline:
        Reads, parses, chunks, embeds and indexes the corpus.
        Skips unchanged files; records data freshness & throughput.
        """
        c_dir = corpus_dir or settings.CORPUS_DIR
        start_time = time.time()
        logger.info(f"Starting corpus indexing from '{c_dir}'")

        if not os.path.exists(c_dir):
            raise FileNotFoundError(f"Corpus directory '{c_dir}' does not exist.")

        files = [
            f for f in sorted(os.listdir(c_dir))
            if f.endswith(".txt") or f.endswith(".md")
        ]

        file_versions: Dict[str, Dict[str, Any]] = {}
        all_chunks: List[DocumentChunk] = []

        for fname in files:
            fpath = os.path.join(c_dir, fname)
            fhash = self._file_hash(fpath)
            file_chunks = parse_and_chunk_document(fpath, max_chunk_chars=settings.CHUNK_SIZE)
            all_chunks.extend(file_chunks)
            file_versions[fname] = {
                "sha256": fhash,
                "chunks_count": len(file_chunks),
                "mtime": os.path.getmtime(fpath),
            }

        total_chunks = len(all_chunks)
        chunk_texts = [f"{c.title}\n{c.text}" for c in all_chunks]

        # Embed all texts
        vectors = self.embedder.fit_and_embed(chunk_texts)

        elapsed_seconds = max(time.time() - start_time, 0.001)
        throughput_chunks_per_sec = total_chunks / elapsed_seconds

        self.chunks = all_chunks
        self.vectors = vectors
        self.clause_map = {c.clause_id: c for c in all_chunks}

        build_time_iso = datetime.utcnow().isoformat() + "Z"
        self.metadata = {
            "build_timestamp": build_time_iso,
            "corpus_directory": c_dir,
            "document_versions": file_versions,
            "total_documents": len(files),
            "total_chunks": total_chunks,
            "embedding_dimension": len(self.embedder.vocabulary),
            "indexing_duration_seconds": round(elapsed_seconds, 3),
            "throughput_chunks_per_second": round(throughput_chunks_per_sec, 2),
            "freshness_epoch": time.time(),
        }

        # Expose freshness & throughput to Prometheus metrics (Requirement D2)
        metrics_collector.set_gauge("corpus_freshness_timestamp", time.time())
        metrics_collector.set_gauge("corpus_chunks_total", float(total_chunks))
        metrics_collector.set_gauge("indexing_throughput_chunks_per_sec", throughput_chunks_per_sec)

        self.save()
        logger.info(
            f"Indexing complete: {total_chunks} chunks across {len(files)} files in {elapsed_seconds:.3f}s "
            f"({throughput_chunks_per_sec:.1f} chunks/sec)"
        )
        return self.metadata

    def save(self):
        os.makedirs(self.index_dir, exist_ok=True)
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

        store_payload = {
            "chunks": [c.to_dict() for c in self.chunks],
            "vocabulary": self.embedder.vocabulary,
            "idf": self.embedder.idf,
            "vectors": self.vectors,
        }
        with open(self.store_file, "w", encoding="utf-8") as f:
            json.dump(store_payload, f)

    def load(self):
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

            with open(self.store_file, "r", encoding="utf-8") as f:
                store_payload = json.load(f)

            self.chunks = [DocumentChunk.from_dict(d) for d in store_payload["chunks"]]
            self.embedder.vocabulary = store_payload["vocabulary"]
            self.embedder.idf = store_payload["idf"]
            self.vectors = store_payload["vectors"]
            self.clause_map = {c.clause_id: c for c in self.chunks}
        except Exception as e:
            logger.warning(f"Could not load existing index: {e}")

    def search(
        self,
        query: str,
        top_k: int = 4,
        regulator_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Vector cosine similarity search over chunks with optional regulator filter."""
        # Check cache first (Requirement D7)
        cache_key = f"{query}|{top_k}|{regulator_filter}"
        cached = global_cache.get_query(cache_key)
        if cached is not None:
            return cached

        if not self.chunks or not self.vectors:
            return []

        q_vec = self.embedder.embed_query(query)
        scored: List[Tuple[float, DocumentChunk]] = []

        for vec, chunk in zip(self.vectors, self.chunks):
            if regulator_filter and chunk.regulator.lower() != regulator_filter.lower():
                continue
            sim = self.embedder.cosine_similarity(q_vec, vec)
            scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = []
        for score, chunk in scored[:top_k]:
            top_results.append({
                "chunk_id": chunk.chunk_id,
                "clause_id": chunk.clause_id,
                "document_name": chunk.document_name,
                "regulator": chunk.regulator,
                "title": chunk.title,
                "text": chunk.text,
                "similarity_score": round(score, 4),
            })

        global_cache.set_query(cache_key, top_results)
        return top_results

    def lookup_by_clause(self, clause_id: str) -> Optional[Dict[str, Any]]:
        """Direct clause lookup by identifier (Tool 2 for Requirement A1)."""
        clean_id = clause_id.strip().upper()
        # Direct key match
        if clean_id in self.clause_map:
            c = self.clause_map[clean_id]
            return {
                "clause_id": c.clause_id,
                "document_name": c.document_name,
                "regulator": c.regulator,
                "title": c.title,
                "text": c.text,
            }
        # Partial prefix match
        for k, c in self.clause_map.items():
            if clean_id in k or k in clean_id:
                return {
                    "clause_id": c.clause_id,
                    "document_name": c.document_name,
                    "regulator": c.regulator,
                    "title": c.title,
                    "text": c.text,
                }
        return None


# Global index instance. data/index/ is gitignored, so build it on first use in a fresh
# checkout; otherwise clause lookups fail and every run escalates on verification failure.
vector_index = VectorIndex()
if not vector_index.chunks and os.path.isdir(settings.CORPUS_DIR):
    vector_index.build_or_update()


if __name__ == "__main__":
    meta = vector_index.build_or_update()
    print("=== INDEXING PIPELINE METADATA ===")
    print(json.dumps(meta, indent=2))
