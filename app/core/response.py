from typing import Generic, Optional, TypeVar
from pydantic.generics import GenericModel

T = TypeVar("T")


class ApiResponse(GenericModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None


class ErrorResponse(GenericModel):
    success: bool = False
    message: str
    detail: Optional[str] = None
