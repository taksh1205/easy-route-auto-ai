from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://easy:easy@localhost:5432/easy"
    ai_mode: Literal["deterministic", "openai", "anthropic"] = "deterministic"
    openai_api_key: str = ""
    openai_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    staff_token: str = ""
    retention_days: int = 30
    rag_path: str = "./rag_index"
    rag_backend: Literal["faiss", "pinecone"] = "faiss"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    rag_rerank: bool = False
    rag_min_similarity: float = 0.35
    pinecone_host: str = ""
    pinecone_api_key: str = ""
    semantic_ranking: bool = False
    weight_features: float = 0.3
    weight_mileage: float = 0.3
    weight_mpg: float = 0.3
    weight_semantic: float = 0.1
    request_limit_per_minute: int = 90
    provider_deadline_seconds: float = 25
    cors_origin: str = "http://localhost:3000"


settings = Settings()
