"""Application configuration settings."""
import sys
from functools import lru_cache

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings

_KNOWN_WEAK_KEYS: frozenset[str] = frozenset({
    "your-secret-key-change-in-production",
    "changeme",
    "change-me",
    "CHANGE_ME_USE_LONG_RANDOM_STRING",
    "secret",
    "insecure",
    "development",
    "test",
    "",
})
_MIN_SECRET_KEY_LENGTH: int = 32
_KEY_GEN_HINT: str = (
    "Generate a strong key with:\n"
    "  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
    "or:\n"
    "  openssl rand -hex 32"
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow",
    )

    APP_NAME: str = "CheryGT: Sensor Fusion Annotation Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/calipergt"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    # Dev/test convenience: emit CREATE TABLE on boot. Production sets this to
    # false and provisions the schema exclusively via `alembic upgrade head`.
    AUTO_CREATE_TABLES: bool = True

    REDIS_URL: str = "redis://localhost:6379/0"

    S3_ENDPOINT: str | None = None
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_BUCKET_NAME: str = "calipergt-data"

    GCS_ENABLED: bool = False
    GCS_PROJECT_ID: str | None = None
    GCS_CREDENTIALS_JSON: str | None = None
    GCS_DEFAULT_BUCKET: str | None = None

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    OBJECT_STORAGE_ENDPOINT: str = "http://minio:9000"
    OBJECT_STORAGE_ACCESS_KEY: str = "minioadmin"
    OBJECT_STORAGE_SECRET_KEY: str = "minioadmin"
    OBJECT_STORAGE_BUCKET: str = "annotation-data"
    OBJECT_STORAGE_PRESIGN_TTL: int = 900

    GCS_BUCKET: str = ""
    GCS_UPLOAD_PREFIX: str = ""
    GCS_SERVICE_ACCOUNT_JSON: str | None = None

    CORS_ORIGINS: list[str] | str = ["http://localhost:3000", "http://localhost:5173"]

    LLM_PROVIDER: str = "ollama"
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "mistral:7b-instruct"

    CHAT_MAX_HISTORY_MESSAGES: int = 20
    CHAT_MAX_TOKENS: int = 2048
    CHAT_TEMPERATURE: float = 0.7
    CHAT_RATE_LIMIT: int = 20

    RAG_ENABLED: bool = True
    RAG_EMBEDDING_MODEL: str = "nomic-embed-text"
    RAG_EMBEDDING_DIMENSIONS: int = 768
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 50
    RAG_CACHE_TTL: int = 3600
    RAG_KNOWLEDGE_BASE_PATH: str = "knowledge_base"
    CLIP_API_URL: str = "http://clip:8002"
    CLIP_MODEL_NAME: str = "ViT-B-16"
    CLIP_EMBEDDING_DIMENSIONS: int = 512
    CLIP_SCENE_TOP_K_FRAMES: int = 200
    CLIP_SCENE_MIN_SIMILARITY: float = 0.18
    RAG_REINDEX_ON_STARTUP: bool = True


    SSO_GOOGLE_CLIENT_ID: str | None = None
    SSO_GOOGLE_CLIENT_SECRET: str | None = None

    SSO_AZURE_CLIENT_ID: str | None = None
    SSO_AZURE_CLIENT_SECRET: str | None = None
    SSO_AZURE_TENANT_ID: str | None = "common"

    SSO_OKTA_CLIENT_ID: str | None = None
    SSO_OKTA_CLIENT_SECRET: str | None = None
    SSO_OKTA_DOMAIN: str | None = None

    SSO_KEYCLOAK_CLIENT_ID: str | None = None
    SSO_KEYCLOAK_CLIENT_SECRET: str | None = None
    SSO_KEYCLOAK_BASE_URL: str | None = None
    SSO_KEYCLOAK_REALM: str | None = None

    SSO_REDIRECT_BASE_URL: str = "http://localhost:8000"
    SSO_DEFAULT_ROLE: str = "annotator"
    SSO_EMAIL_DOMAIN_ORG_MAP: str = ""
    SSO_FRONTEND_URL: str = "http://localhost:5173"

    ALLOWED_BROWSE_ROOTS: list[str] = ["/uploads", "/data"]

    @field_validator('SECRET_KEY')
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Refuse to start when SECRET_KEY is weak or a known placeholder."""
        if v in _KNOWN_WEAK_KEYS:
            sys.exit(
                f"\nFATAL: SECRET_KEY is set to a known weak/default value.\n"
                f"{_KEY_GEN_HINT}\n"
            )
        if len(v) < _MIN_SECRET_KEY_LENGTH:
            sys.exit(
                f"\nFATAL: SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} "
                f"characters long (got {len(v)}).\n"
                f"{_KEY_GEN_HINT}\n"
            )
        return v

    @field_validator('ALLOWED_BROWSE_ROOTS', mode='before')
    @classmethod
    def parse_allowed_browse_roots(cls, v):
        """Parse ALLOWED_BROWSE_ROOTS from comma-separated string or list."""
        if isinstance(v, str):
            if not v:
                return ["/uploads", "/data"]
            return [r.strip() for r in v.split(',') if r.strip()]
        if isinstance(v, list):
            return v
        return ["/uploads", "/data"]

    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from comma-separated string or list."""
        if isinstance(v, str):
            if not v:
                return ["http://localhost:3000", "http://localhost:5173"]
            return [origin.strip() for origin in v.split(',')]
        if isinstance(v, list):
            return v
        return ["http://localhost:3000", "http://localhost:5173"]




@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Raises SystemExit if SECRET_KEY is missing, weak, or too short so that the
    application refuses to start rather than running insecurely.
    """
    try:
        return Settings()
    except Exception as exc:
        sys.exit(
            f"\nFATAL: Application configuration is invalid: {exc}\n"
            f"Ensure SECRET_KEY is set in the environment or .env file.\n"
            f"{_KEY_GEN_HINT}\n"
        )

settings = get_settings()
