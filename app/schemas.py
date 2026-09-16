from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class JobInput(BaseModel):
    url: AnyHttpUrl
    company: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=20_000)

    @field_validator("company", "role", "location", "source", "description")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class JobPreviewInput(JobInput):
    pass


class JobSaveInput(JobInput):
    source: str = Field(default="Company Careers", max_length=100)


class FriendInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class BatchInput(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    job_ids: list[str] = Field(min_length=1)


class StatusInput(BaseModel):
    status: str = "APPLIED"

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"NOT_APPLIED", "APPLIED"}:
            raise ValueError("Invalid status")
        return value
