from uuid import UUID

from pydantic import BaseModel


class TenantItem(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str


class TenantListResponse(BaseModel):
    items: list[TenantItem]
