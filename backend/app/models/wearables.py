from datetime import date
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint

class WearableDaily(SQLModel, table=True):
    __tablename__ = "wearable_daily"
    __table_args__ = (UniqueConstraint("day", "source", name="uq_day_source"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    source: str = Field(index=True, description="z.B. 'garmin', 'strava', 'apple'")

    steps: Optional[int] = Field(default=None, ge=0)
    active_minutes: Optional[int] = Field(default=None, ge=0)
    calories: Optional[float] = Field(default=None, ge=0)
    hr_avg: Optional[float] = Field(default=None, ge=0)
    hrv_ms: Optional[float] = Field(default=None, ge=0)
    sleep_minutes: Optional[int] = Field(default=None, ge=0)

class WearableDailyBase(SQLModel):
    day: date
    source: str
    steps: Optional[int] = Field(default=None, ge=0)
    active_minutes: Optional[int] = Field(default=None, ge=0)
    calories: Optional[float] = Field(default=None, ge=0)
    hr_avg: Optional[float] = Field(default=None, ge=0)
    hrv_ms: Optional[float] = Field(default=None, ge=0)
    sleep_minutes: Optional[int] = Field(default=None, ge=0)

class WearableDailyCreate(WearableDailyBase):
    pass

class WearableDailyRead(WearableDailyBase):
    id: int

class WearableDailyUpsert(WearableDailyBase):
    pass
