from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ListDirArguments(ToolArguments):
    path: str = Field(default="", max_length=300, description="Workspace-relative directory.")


class ReadFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=300, description="Allowed workspace-relative file.")


class SearchContentArguments(ToolArguments):
    keyword: str = Field(min_length=1, max_length=200)
    dir: str = Field(
        min_length=1, max_length=300, description="Allowed workspace-relative directory."
    )


class WriteFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=300, description="A path inside drafts/.")
    content: str = Field(max_length=65_536)


class BashArguments(ToolArguments):
    command: str = Field(min_length=1, max_length=500)


class FetchRSSArguments(ToolArguments):
    source_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique_and_bounded(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 64 for value in values):
            raise ValueError("invalid_source_id")
        if len(set(values)) != len(values):
            raise ValueError("duplicate_source_id")
        return values


class SearchNewsArguments(ToolArguments):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


class FetchArticleArguments(ToolArguments):
    article_id: str = Field(min_length=16, max_length=64)
