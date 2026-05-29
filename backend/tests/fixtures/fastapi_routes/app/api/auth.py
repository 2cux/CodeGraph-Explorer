from fastapi import APIRouter

router = APIRouter()


@router.post("/login")
def login(username: str, password: str) -> str:
    return "token"


@router.get("/me")
def current_user() -> dict:
    return {}
