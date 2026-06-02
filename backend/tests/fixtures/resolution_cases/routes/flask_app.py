"""Flask route decorator fixtures."""


# Mock Flask app for AST parsing
class _FlaskApp:
    def route(self, path: str, methods=None):
        return lambda fn: fn


app = _FlaskApp()
blueprint = _FlaskApp()


@app.route("/login", methods=["POST"])
def flask_login(username: str, password: str) -> str:
    """Flask login endpoint."""
    return "token"


@app.route("/health")
def flask_health() -> dict:
    """Flask health check endpoint."""
    return {"status": "ok"}


@blueprint.route("/users", methods=["GET"])
def flask_list_users() -> list:
    """Flask list users endpoint."""
    return []
