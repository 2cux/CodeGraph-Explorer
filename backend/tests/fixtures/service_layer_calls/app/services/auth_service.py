class AuthService:
    def login_user(self, username: str, password: str) -> str:
        self.validate_password(username, password)
        return self.issue_token(username)

    def validate_password(self, username: str, password: str) -> None:
        pass

    def issue_token(self, username: str) -> str:
        return "token"
