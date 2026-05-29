def login(username: str, password: str) -> str:
    return "token"


def verify_token(token: str) -> bool:
    return token == "token"
