"""Token storage module."""

_tokens: dict[str, bool] = {}


def save_token(token: str) -> None:
    _tokens[token] = True


def revoke_token(token: str) -> None:
    _tokens.pop(token, None)


def is_valid(token: str) -> bool:
    return _tokens.get(token, False)
