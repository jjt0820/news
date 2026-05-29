from typing import List

from pydantic import BaseModel, EmailStr, Field, field_validator

from category_slugs import normalize_category_slugs


class SubscribeCreate(BaseModel):
    email: EmailStr
    category: List[str] = Field(..., min_length=1)

    @field_validator("category")
    @classmethod
    def validate_categories(cls, categories: List[str]) -> List[str]:
        return normalize_category_slugs(categories)


class SubscribeResponse(BaseModel):
    message: str
    email: str
    category: str


class InternalSubscriberOut(BaseModel):
    """mail-service 등 내부 연동용 구독자 스냅샷."""

    email: str
    interest_categories: List[str] = Field(default_factory=list)
