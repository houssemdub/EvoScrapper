from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8009
    DEBUG: bool = False
    API_KEY: Optional[str] = None
    ALLOWED_ORIGINS: list[str] = ["*"]

    # Proxy settings
    HTTP_PROXY: Optional[str] = None

    # Timeouts & Circuit Breaker
    DEFAULT_TIMEOUT: float = 5.0
    CIRCUIT_BREAKER_FAIL_THRESHOLD: int = 3
    CIRCUIT_BREAKER_RECOVERY_TIME: float = 90.0

    # Subtitle API Keys (Optional - fallbacks available for keyless usage)
    SUBDL_API_KEY: Optional[str] = None
    SUBSOURCE_API_KEY: Optional[str] = None
    OPENSUBTITLES_API_KEY: Optional[str] = None
    WYZIE_API_KEY: Optional[str] = None
    JIMAKU_API_KEY: Optional[str] = None

    # Debrid Provider API Keys (Optional - Enables instant high-speed cloud playback)
    REALDEBRID_API_KEY: Optional[str] = None
    ALLDEBRID_API_KEY: Optional[str] = None
    DEBRIDLINK_API_KEY: Optional[str] = None
    PREMIUMIZE_API_KEY: Optional[str] = None
    TORBOX_API_KEY: Optional[str] = None
    PIKPAK_API_KEY: Optional[str] = None
    PIKPAK_USER: Optional[str] = None
    PIKPAK_PASSWORD: Optional[str] = None

    # Caching
    CACHE_TTL_SEARCH: int = 900  # 15 minutes
    CACHE_TTL_TRENDING: int = 3600  # 1 hour

    # Streaming & Transmuxing Settings
    STREAM_CACHE_DIR: str = ".stream_cache"
    MAX_DISK_CACHE_GB: float = 15.0
    MAX_CONCURRENT_FFMPEG: int = 4
    STREAM_PORT: int = 8889
    TORRENT_PORT: int = 50000
    DHT_PORT: int = 50001

    # Debrid Multi-IP Stream Proxy
    DEBRID_PROXY_ENABLED: bool = True
    DEBRID_PROXY_SECRET: str = "evoscrapper-debrid-proxy-secret-key"

    # CometNet P2P Metadata Gossip
    COMETNET_ENABLED: bool = True
    COMETNET_PORT: int = 8010
    COMETNET_RELAYS: list[str] = ["wss://relay.comet.cache", "wss://cometnet.peer.evo"]


settings = Settings()
