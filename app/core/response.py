from typing import Generic, Optional, TypeVar
from pydantic import BaseModel
from pydantic.generics import GenericModel

T = TypeVar("T")


class ApiResponse(GenericModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_next: bool
    has_prev: bool


class PagedApiResponse(GenericModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None
    meta: PaginationMeta


class ErrorResponse(GenericModel):
    success: bool = False
    message: str
    detail: Optional[str] = None
