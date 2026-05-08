from typing import List

from pydantic import BaseModel, EmailStr, Field


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    token: str


class NewsCardItem(BaseModel):
    source: str
    time: str
    title: str
    summary: str


class NewsSummaryEmailRequest(BaseModel):
    email: EmailStr
    categories: List[str] = Field(default_factory=list)
    title: str = "좋은 아침이에요,\n큐레이션 뉴스가 도착했어요"
    subtitle: str = "오늘의 뉴스"
    news_cards: List[NewsCardItem] = Field(..., min_length=1)
