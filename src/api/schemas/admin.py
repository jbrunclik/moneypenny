"""Admin page and spend status schemas (S12)."""

from pydantic import BaseModel, Field


class Money(BaseModel):
    """An amount in USD and formatted in the display currency."""

    usd: float
    formatted: str


class UserSpend(BaseModel):
    name: str
    today: Money
    month: Money
    month_chats: int = Field(..., description="Conversations with a billed turn this month")
    month_turns: int = Field(..., description="Billed turns (answers) this month")
    over_threshold: bool = Field(..., description="Today's spend is past the warning threshold")


class DailySpend(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    amount: Money


class SpendShare(BaseModel):
    name: str
    amount: Money


class SpendSection(BaseModel):
    today: Money
    month: Money
    threshold: Money
    users: list[UserSpend]
    daily: list[DailySpend] = Field(..., description="The last 30 days, oldest first")
    by_feature: list[SpendShare] = Field(..., description="This month, largest first")
    by_model: list[SpendShare] = Field(..., description="This month, largest first")


class AgentFailure(BaseModel):
    agent_name: str
    user_name: str
    started_at: str
    error: str = Field(..., description="The first line of the error, cut to 120 characters")


class AgentsSection(BaseModel):
    runs_7d: int
    failed_7d: int
    pending_approvals: int
    recent_failures: list[AgentFailure]


class SearchProviderStatus(BaseModel):
    provider: str
    configured: bool
    used: int
    quota: int | None = Field(None, description="Monthly quota; null = unmetered")
    available: bool = Field(..., description="Search would try this provider right now")


class SearchSection(BaseModel):
    degraded_today: bool = Field(..., description="Search fell back to the free provider today")
    providers: list[SearchProviderStatus] = Field(..., description="In priority order")


class QualitySection(BaseModel):
    turns_7d: int
    median_ms: int | None = None
    p95_ms: int | None = None
    tool_error_rate: float = Field(..., description="Share of turns with a tool error, 0-1")


class SystemSection(BaseModel):
    version: str | None = None
    database_bytes: int
    files_bytes: int
    last_backup_at: str | None = None
    latest_migration: str | None = None
    users: int


class BrowserError(BaseModel):
    kind: str = Field(..., description="error, unhandled_rejection or logged")
    message: str = Field(..., description="Cut to 300 characters")
    stack: str | None = Field(None, description="The first frames")
    path: str | None = Field(None, description="Route path of the latest occurrence")
    app_version: str | None = None
    count: int = Field(..., description="Occurrences across users")
    users: int
    last_seen: str


class AdminOverviewResponse(BaseModel):
    """Everything the admin page shows - names and numbers, no conversation content."""

    generated_at: str
    currency: str
    spend: SpendSection
    agents: AgentsSection
    search: SearchSection
    quality: QualitySection
    system: SystemSection
    browser_errors: list[BrowserError] = Field(
        ..., description="Seen in the last 7 days, most frequent first"
    )


class SpendStatusResponse(BaseModel):
    """The signed-in user's spend today against the warning threshold."""

    today: Money
    threshold_usd: float
    over_threshold: bool
