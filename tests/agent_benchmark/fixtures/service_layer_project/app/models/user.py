"""Pydantic models for the service layer project."""

from dataclasses import dataclass


@dataclass
class UserCreateRequest:
    """Payload for user creation/update."""
    username: str
    email: str
    password: str


@dataclass
class UserResponse:
    """User data returned to API clients."""
    id: int
    username: str
    email: str

    @classmethod
    def from_dict(cls, data: dict) -> "UserResponse":
        return cls(
            id=data["id"],
            username=data["username"],
            email=data.get("email", ""),
        )
