from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr


class ProviderSettings(BaseModel):
    provider: str = "anthropic"
    endpoint: AnyHttpUrl | None = None
    model: str = "claude-opus-5"
    system_prompt: str = "You are IgorAgent. Follow policy decisions and never claim an action succeeded unless its tool result confirms it."
    max_output_tokens: int = Field(default=2048, ge=256, le=16384)
    monthly_token_budget: int = Field(default=2_000_000, ge=1_000)
    api_key: SecretStr | None = None

    def public_configuration(self) -> dict[str, object]:
        return self.model_dump(exclude={"api_key"}, mode="json")
