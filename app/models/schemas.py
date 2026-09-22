from typing import Any
from pydantic import BaseModel, Field

class ToolError(BaseModel):
    code: str
    message: str

class ToolResult(BaseModel):
    success: bool
    data: Any = None
    error: ToolError | None = None

def ok(data: Any) -> dict:
    return ToolResult(success=True, data=data).model_dump()

def fail(code: str, message: str) -> dict:
    return ToolResult(success=False, error=ToolError(code=code, message=message)).model_dump()
