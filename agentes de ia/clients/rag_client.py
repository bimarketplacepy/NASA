"""Cliente mock de RAG sobre PDFs con TF-IDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


CATALOGOS_DIR = Path(__file__).resolve().parent.parent / "data" / "catalogos_proveedor"


@dataclass
class Chunk:
    """Fragmento de documento indexado."""

    chunk_id: str
    proveedor_id: str
    source_file: str
    content: str
    score: float = 0.0


class RAGClient:
    """Mock de cliente RAG, manteniendo API estable de busqueda."""

    def __init__(self, chunk_size: int = 800, overlap: int = 100) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._chunks: list[Chunk] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._is_indexed = False

    def buscar(self, query: str, k: int = 5, filtro_proveedor: str | None = None) -> list[Chunk]:
        """Busca chunks por similitud semantica aproximada."""
        self._ensure_index()
        if not self._chunks or self._vectorizer is None or self._matrix is None:
            return []

        query_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self._matrix).flatten()

        candidates: list[Chunk] = []
        for idx, score in enumerate(sims):
            chunk = self._chunks[idx]
            if filtro_proveedor and chunk.proveedor_id != filtro_proveedor:
                continue
            candidates.append(
                Chunk(
                    chunk_id=chunk.chunk_id,
                    proveedor_id=chunk.proveedor_id,
                    source_file=chunk.source_file,
                    content=chunk.content,
                    score=float(score),
                )
            )
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k]

    def _ensure_index(self) -> None:
        if self._is_indexed:
            return
        docs = self._load_pdf_documents()
        self._chunks = self._chunk_documents(docs)
        if not self._chunks:
            self._is_indexed = True
            return
        self._vectorizer = TfidfVectorizer(stop_words=None, ngram_range=(1, 2))
        self._matrix = self._vectorizer.fit_transform([c.content for c in self._chunks])
        self._is_indexed = True

    def _load_pdf_documents(self) -> list[tuple[str, str]]:
        docs: list[tuple[str, str]] = []
        CATALOGOS_DIR.mkdir(parents=True, exist_ok=True)
        for path in CATALOGOS_DIR.glob("*.pdf"):
            text = self._read_pdf_text(path)
            if text.strip():
                docs.append((path.name, text))
        return docs

    def _read_pdf_text(self, path: Path) -> str:
        try:
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception:
            return ""

    def _chunk_documents(self, docs: list[tuple[str, str]]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for filename, text in docs:
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized:
                continue
            proveedor_id = self._extract_provider_id(filename)
            start = 0
            idx = 0
            while start < len(normalized):
                end = start + self.chunk_size
                content = normalized[start:end]
                chunks.append(
                    Chunk(
                        chunk_id=f"{filename}:{idx}",
                        proveedor_id=proveedor_id,
                        source_file=filename,
                        content=content,
                    )
                )
                idx += 1
                if end >= len(normalized):
                    break
                start = max(end - self.overlap, 0)
        return chunks

    def _extract_provider_id(self, filename: str) -> str:
        base = filename.replace(".pdf", "").upper()
        match = re.search(r"PROV_[A-Z]+_\d{2}", base)
        if match:
            return match.group(0)
        return "UNKNOWN"
