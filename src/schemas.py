from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(BaseModel):
    name: str
    url: HttpUrl  # every record MUST trace back to a real URL


class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


# ---------- STARTUP ----------
class StartupData(BaseModel):
    employeeCount: Optional[int] = None  # None if not in source


class StartupContent(BaseModel):
    entityName: str
    data: StartupData = StartupData()


class StartupRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["STARTUP"] = "STARTUP"
    source: Source
    content: StartupContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- PRODUCT ----------
class ProductContent(BaseModel):
    productName: Optional[str] = None
    startupName: str
    pricingModel: Optional[PricingModel] = None  # None if unknown


class ProductRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["PRODUCT"] = "PRODUCT"
    source: Source
    content: ProductContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- RESEARCH PAPER ----------
class ResearchPaperContent(BaseModel):
    title: str
    authors: List[str] = []
    paper_url: HttpUrl
    github_url: Optional[str] = None
    github_stars: Optional[int] = None
    published_date: Optional[datetime] = None
    github_stars_fetched_at: Optional[datetime] = None  # freshness of the metric


class ResearchPaperRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    source: Source
    content: ResearchPaperContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- JOB ----------
class JobContent(BaseModel):
    title: Optional[str] = None
    company: str
    date: datetime
    is_remote: Optional[bool] = None
    role_family: Optional[str] = None


class JobRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["JOB"] = "JOB"
    source: Source
    content: JobContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- NEWS ----------
class NewsContent(BaseModel):
    title: str
    published_date: datetime
    full_text: Optional[str] = None


class NewsRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["NEWS"] = "NEWS"
    source: Source
    content: NewsContent
    collectedAt: datetime = Field(default_factory=utcnow)