"""Safe aggregate LLM usage responses."""

from pydantic import BaseModel, Field


class LLMUsageAggregateItem(BaseModel):
    day: str
    scenario: str
    request_count: int
    item_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float = Field(ge=0, le=1)


class LLMUsageAggregateResponse(BaseModel):
    days: int
    items: list[LLMUsageAggregateItem]
