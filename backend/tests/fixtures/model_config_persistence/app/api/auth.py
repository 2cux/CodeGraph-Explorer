from app.services.auth_service import AuthService
from app.models.user import User

auth_service = AuthService()


def login(username: str, password: str) -> str:
    user = User(id="1", username=username, password_hash="hash")
    return auth_service.login_user(user, password)
