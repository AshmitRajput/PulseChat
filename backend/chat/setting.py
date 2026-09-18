from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43800
    SECRET_KEY: str = "SeCretKey_CHaNgeMe"
    ALGORITHM: str = "HS256"
    VERSION: int = 1
    REDIS_URL: str = "redis://redis:6379/0"

    class Config:
        env_file = ".env"  # optional: override any field via env vars / a .env file


setting = Settings()
