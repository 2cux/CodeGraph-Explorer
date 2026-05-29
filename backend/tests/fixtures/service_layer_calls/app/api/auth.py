from app.services.auth_service import AuthService

auth_service = AuthService()


def login(username: str, password: str) -> str:
    return auth_service.login_user(username, password)


def login_with_local_service(username: str, password: str) -> str:
    service = AuthService()
    return service.login_user(username, password)


def login_with_constructor(username: str, password: str) -> str:
    return AuthService().login_user(username, password)


def login_with_param(auth_service: AuthService, username: str, password: str) -> str:
    return auth_service.login_user(username, password)
