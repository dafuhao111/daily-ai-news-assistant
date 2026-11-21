from pydantic import BaseModel, ConfigDict, Field


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
