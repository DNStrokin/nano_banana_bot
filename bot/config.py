from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    GEMINI_API_KEY: SecretStr
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    
    # Comma separated list of admin IDs (e.g. "12345,67890")
    ADMIN_IDS: str = "220567" 

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

config = Settings()
