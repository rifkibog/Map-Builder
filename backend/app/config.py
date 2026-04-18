"""Application configuration settings"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Settings
    API_KEY: str = os.getenv("API_KEY", "")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # Google Cloud Settings - Deploy project
    GCP_PROJECT: str = os.getenv("GCP_PROJECT", "telkomsel-homepass")
    
    # BigQuery Settings - Data project
    BQ_PROJECT: str = os.getenv("BQ_PROJECT", "telkomsel-homepass")
    BQ_DATASET: str = os.getenv("BQ_DATASET", "building_spatial")
    
    # Table names for different layer types
    BQ_TABLE_BUILDINGS: str = os.getenv("BQ_TABLE_BUILDINGS", "buildings_final_with_desa")
    BQ_TABLE_GOOGLE: str = os.getenv("BQ_TABLE_GOOGLE", "buildings_google_raw")
    BQ_TABLE_ONEGEO: str = os.getenv("BQ_TABLE_ONEGEO", "buildings_onegeo_raw")
    
    # Cache Settings
    CACHE_TTL: int = 300  # 5 minutes
    
    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
