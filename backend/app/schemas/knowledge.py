"""Knowledge-base (RAG) administration and search API schemas."""

from pydantic import BaseModel, Field


class KnowledgeStatsResponse(BaseModel):
    """Knowledge base statistics."""
    total_chunks: int
    total_files: int
    avg_chunk_size: int
    last_indexed: str | None = None
    embedding_model: str
    embedding_dimensions: int
    rag_enabled: bool = Field(default=True)


class SearchResult(BaseModel):
    """Search result item."""
    id: int
    content: str
    source_file: str
    chunk_index: int
    score: float
    match_type: str
    metadata: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    """Search request."""
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    search_type: str = Field(default="hybrid", pattern="^(semantic|keyword|hybrid)$")


class SearchResponse(BaseModel):
    """Search response."""
    query: str
    results: list[SearchResult]
    total: int


class ReindexResponse(BaseModel):
    """Reindex response."""
    success: bool
    chunks_indexed: int
    message: str
