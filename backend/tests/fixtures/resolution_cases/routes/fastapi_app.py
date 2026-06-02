"""FastAPI route decorator fixtures."""


# Mock FastAPI objects for AST parsing
class _Router:
    def get(self, path: str):
        return lambda fn: fn

    def post(self, path: str):
        return lambda fn: fn

    def put(self, path: str):
        return lambda fn: fn

    def delete(self, path: str):
        return lambda fn: fn


app = _Router()
router = _Router()


@app.get("/users")
def list_users() -> list:
    """List all users."""
    return []


@router.post("/login")
def login(username: str, password: str) -> str:
    """Login endpoint."""
    return "token"


@router.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
