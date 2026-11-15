from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "Acacia Tours & Travel Platform"
    TIMEZONE: str = "Africa/Nairobi"
    BASE_REPORTING_CURRENCY: str = "USD"

    API_V1_STR: str = "/api/v1"
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)

    POSTGRES_USER: str = "acacia"
    POSTGRES_PASSWORD: str = "acacia"
    POSTGRES_DB: str = "acacia"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str | None = None

    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change_me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    PORTAL_BASE_URL: str = "http://localhost:3001"
    PORTAL_ACCESS_DAYS_AFTER_TRAVEL: int = 90

    MPESA_ENVIRONMENT: str = "sandbox"
    MPESA_CONSUMER_KEY: str | None = None
    MPESA_CONSUMER_SECRET: str | None = None
    MPESA_SHORTCODE: str | None = None
    MPESA_SHORTCODE_TYPE: str = "paybill"
    MPESA_PASSKEY: str | None = None
    MPESA_CALLBACK_BASE_URL: str | None = None
    MPESA_TOKEN_CACHE_SECONDS: int = 3500
    MPESA_CALLBACK_ALLOWED_IPS: str = ""

    PUBLIC_READ_PER_MINUTE: int = 120
    PUBLIC_ENQUIRIES_PER_HOUR: int = 5
    PUBLIC_ESTIMATES_PER_HOUR: int = 60

    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"
    FIRST_SUPERUSER_NAME: str = "Platform Admin"

    UPLOAD_ROOT: str = "var/uploads"
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024

    PDF_BROWSER_PATH: str | None = None
    PDF_BROWSER_NO_SANDBOX: bool = False
    PDF_RENDER_SETTLE_MS: int = 3000
    PDF_RENDER_TIMEOUT_SECONDS: int = 60
    PDF_TESTS_KNOWN_TO_HANG: bool = False

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    _LIBPQ_ONLY_QUERY_KEYS = frozenset(
        {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "options"}
    )

    def _raw_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def _url_with_driver(self, driver: str, *, strip_libpq: bool) -> str:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(self._raw_database_url())
        scheme = f"postgresql+{driver}"
        query = parts.query
        if strip_libpq and query:
            kept = [
                (k, v)
                for k, v in parse_qsl(query, keep_blank_values=True)
                if k not in self._LIBPQ_ONLY_QUERY_KEYS
            ]
            query = urlencode(kept)
        return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))

    @property
    def sqlalchemy_database_uri(self) -> str:
        return self._url_with_driver("asyncpg", strip_libpq=True)

    @property
    def sqlalchemy_sync_uri(self) -> str:
        return self._url_with_driver("psycopg2", strip_libpq=False)

    def _db_sslmode(self) -> str | None:
        from urllib.parse import parse_qsl, urlsplit

        query = urlsplit(self._raw_database_url()).query
        for key, value in parse_qsl(query, keep_blank_values=True):
            if key == "sslmode":
                return value.lower()
        return None

    @property
    def async_connect_args(self) -> dict[str, object]:
        args: dict[str, object] = {}
        sslmode = self._db_sslmode()
        if sslmode in {"require", "verify-ca", "verify-full", "prefer", "allow"}:
            args["ssl"] = sslmode
        elif sslmode == "disable":
            args["ssl"] = False

        host = self._raw_database_url()
        if "neon.tech" in host or "pooler" in host:
            args["statement_cache_size"] = 0
        return args

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
