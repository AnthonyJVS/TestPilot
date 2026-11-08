from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128  # bounds Argon2 work per request


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("display_name", mode="after")
    @classmethod
    def _display_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Display name must not be blank.")
        return value

    @field_validator("password", mode="after")
    @classmethod
    def _password(cls, value: str) -> str:
        if value.strip() != value or not value.strip():
            raise ValueError("Password must not start or end with whitespace.")
        if len(set(value)) < 4:
            raise ValueError("Password is too repetitive.")
        return value

    @model_validator(mode="after")
    def _password_not_email(self) -> RegisterRequest:
        if self.password.lower() in {self.email, self.email.split("@", 1)[0]}:
            raise ValueError("Password must not match the email address.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalize_email(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int = Field(description="Access token lifetime in seconds.")
    expires_at: datetime
    user: UserOut
