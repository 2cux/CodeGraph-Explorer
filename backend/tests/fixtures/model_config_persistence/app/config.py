from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    token_ttl_seconds: int = 3600
    mfa_required: bool = False


MFA_REQUIRED = False
