from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}
    # bcrypt operates on max 72 bytes; cap input explicitly.
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth scheme name
    expires_in: int  # seconds


class CsrfResponse(BaseModel):
    csrf_token: str


class MessageResponse(BaseModel):
    message: str
