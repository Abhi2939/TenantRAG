from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://tenantrag:tenantrag@db:5432/tenantrag"

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 5

    llm_provider: str = "groq"
    llm_model: str = ""
    groq_api_key: str = ""

settings = Settings()