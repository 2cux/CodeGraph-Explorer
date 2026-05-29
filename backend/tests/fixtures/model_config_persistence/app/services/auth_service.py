from app.models.user import User
from app.store.token_store import TokenStore
from app.config import Settings


class AuthService:
    def __init__(self):
        self.token_store = TokenStore()
        self.settings = Settings()

    def login_user(self, user: User, password: str) -> str:
        token = "token"
        self.token_store.save_token(token)
        return token
