from typing import List

from pydantic import BaseModel, EmailStr, Field, field_validator

from constants import ALLOWED_CATEGORIES


class SubscribeCreate(BaseModel):
    email: EmailStr
    category: List[str] = Field(..., min_length=1)

    @field_validator("category")
    @classmethod
    def validate_categories(cls, categories: List[str]) -> List[str]:
        cleaned = [c.strip() for c in categories if c and c.strip()]
        if not cleaned:
            raise ValueError("category는 최소 1개 이상의 값이 필요합니다.")

        invalid = [c for c in cleaned if c not in ALLOWED_CATEGORIES]
        if invalid:
            raise ValueError(
                f"허용되지 않은 카테고리입니다: {', '.join(invalid)}. "
                f"허용값: {', '.join(ALLOWED_CATEGORIES)}"
            )
        return cleaned


class SubscribeResponse(BaseModel):
    message: str
    email: str
    category: str


class InternalSubscriberOut(BaseModel):
    """mail-service 등 내부 연동용 구독자 스냅샷."""

    email: str
    interest_categories: List[str] = Field(default_factory=list)
