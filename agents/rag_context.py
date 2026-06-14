"""
Lightweight RAG (Retrieval-Augmented Generation) over DOM snapshots.

Pipeline:
  1. Chunk  — split the raw HTML into overlapping text segments
  2. Embed  — represent each chunk with TF-IDF sparse vectors (sklearn)
  3. Retrieve — cosine-similarity search to find top-k chunks most relevant
               to the error query (selector + error message)
  4. Augment — return only those chunks for injection into the LLM prompt

This avoids sending the full 50 KB DOM to the LLM and demonstrates the
core RAG concepts (chunking, vectorisation, retrieval) without needing
an external vector database or embedding API.
"""
import re
import numpy as np
from typing import List


# ── 1. Chunking ───────────────────────────────────────────────────────────────

def _chunk_html(html: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """
    Strip HTML tags and split the visible text into overlapping windows.
    Generator that yields one chunk at a time.
    """
    # Strip tags, collapse whitespace
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    step = chunk_size - overlap
    for start in range(0, max(len(text), 1), step):
        chunk = text[start: start + chunk_size].strip()
        if chunk:
            yield chunk


# ── 2 & 3. Embed + Retrieve ───────────────────────────────────────────────────

def retrieve_relevant_dom(dom_html: str, query: str, top_k: int = 3) -> str:
    """
    Return the top_k most query-relevant DOM chunks joined as a string,
    ready to be injected into an LLM prompt.

    Falls back to a simple 50 k-char truncation if sklearn is unavailable.
    """
    chunks = list(_chunk_html(dom_html))

    if not chunks:
        return dom_html[:50000]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = chunks + [query]
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf_matrix = vectorizer.fit_transform(corpus)

        # Query vector is the last row; chunk vectors are all rows except the last
        query_vec = tfidf_matrix[-1]
        chunk_vecs = tfidf_matrix[:-1]

        # Cosine similarity of each chunk against the query
        scores = cosine_similarity(query_vec, chunk_vecs).flatten()

        top_indices = np.argsort(scores)[::-1][:top_k]
        selected = [chunks[i] for i in sorted(top_indices)]

        print(f"[rag_context] Retrieved {len(selected)} of {len(chunks)} DOM chunks for query: {query[:80]!r}")
        return "\n---\n".join(selected)

    except ImportError:
        print("[rag_context] scikit-learn not installed — using raw truncation fallback")
        return dom_html[:50000]
