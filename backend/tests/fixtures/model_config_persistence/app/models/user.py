from pydantic import BaseModel


class User(BaseModel):
    id: str
    username: str
    password_hash: str
    mfa_enabled: bool = False
