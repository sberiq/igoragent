import bootstrap  # noqa: F401

from datetime import datetime
from hmac import compare_digest
import os
from threading import Lock

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auth import AuthService
from igoragent_core.configuration_store import ConfigurationStore
from igoragent_core.llm import ProviderSettings
from igoragent_core.memory import MemoryScope, MemoryService, MemorySettings
from igoragent_core.policy_engine import AgentPolicy
from igoragent_core.scheduler.heartbeat import HeartbeatSettings, plan_hourly_heartbeat
from igoragent_core.telegram import TelegramAuthError, TelegramLoginService

SESSION_COOKIE = "igoragent_session"
COOKIE_SECURE = os.getenv("IGORAGENT_COOKIE_SECURE", "true").casefold() != "false"
LOCAL_MODE = os.getenv("IGORAGENT_LOCAL_MODE", "false").casefold() == "true"
SETUP_TOKEN = os.getenv("IGORAGENT_SETUP_TOKEN")

app = FastAPI(title="IgorAgent Control Plane", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("IGORAGENT_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Setup-Token"],
)

policy = AgentPolicy()
heartbeat = HeartbeatSettings()
provider = ProviderSettings()
memory_settings = MemorySettings()
memory_service = MemoryService(memory_settings)
configuration_store = ConfigurationStore()
auth_service = AuthService()
configuration_lock = Lock()
telegram_login = TelegramLoginService()
onboarding_completed = False


class AgentConfiguration(BaseModel):
    policy: AgentPolicy
    heartbeat: HeartbeatSettings
    provider: ProviderSettings
    memory: MemorySettings


class PublicAgentConfiguration(BaseModel):
    policy: AgentPolicy
    heartbeat: HeartbeatSettings
    provider: dict[str, object]
    memory: MemorySettings


class OnboardingStatus(BaseModel):
    completed: bool


class OnboardingConfiguration(AgentConfiguration):
    owner_telegram_id: int = Field(gt=0)


class PasswordSetup(BaseModel):
    password: str = Field(min_length=14, max_length=256)
    confirmation: str = Field(min_length=14, max_length=256)


class PasswordLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    configured: bool
    authenticated: bool
    onboarding_completed: bool


class TelegramLoginRequest(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=32, max_length=64)
    phone_number: str = Field(min_length=6, max_length=32)


class TelegramLoginConfirmation(BaseModel):
    code: str = Field(min_length=3, max_length=16)
    password: str | None = Field(default=None, max_length=256)


def persist_configuration() -> None:
    configuration_store.save({
        "policy": policy.model_dump(mode="json"),
        "heartbeat": heartbeat.model_dump(mode="json"),
        "provider": provider.public_configuration(),
        "memory": memory_settings.model_dump(mode="json"),
        "auth_password_hash": auth_service.exported_password_hash(),
        "onboarding_completed": onboarding_completed,
    })


def load_configuration() -> None:
    global policy, heartbeat, provider, memory_settings, memory_service, onboarding_completed
    saved = configuration_store.load()
    if saved is None:
        return
    policy = AgentPolicy.model_validate(saved["policy"])
    heartbeat = HeartbeatSettings.model_validate(saved["heartbeat"])
    provider = ProviderSettings.model_validate(saved["provider"])
    memory_settings = MemorySettings.model_validate(saved.get("memory", {}))
    memory_service = MemoryService(memory_settings)
    auth_service.restore_password_hash(saved.get("auth_password_hash"))
    onboarding_completed = bool(saved.get("onboarding_completed", False))


def request_is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in {"127.0.0.1", "::1", "localhost"}


def require_authenticated(
    request: Request,
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    state_change = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    if not auth_service.authenticate(session_id, csrf_token, state_change):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


load_configuration()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/status", response_model=AuthStatus)
def get_auth_status(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> AuthStatus:
    return AuthStatus(
        configured=auth_service.configured,
        authenticated=auth_service.authenticate(session_id, None, False),
        onboarding_completed=onboarding_completed,
    )


@app.post("/api/auth/setup")
def setup_password(payload: PasswordSetup, request: Request, response: Response, setup_token: str | None = Header(default=None, alias="X-Setup-Token")) -> dict[str, str]:
    if auth_service.configured:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Password already configured")
    if not LOCAL_MODE and not request_is_local(request) and not (SETUP_TOKEN and setup_token and compare_digest(SETUP_TOKEN, setup_token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initial setup requires local access or a valid setup token")
    try:
        auth_service.set_initial_password(payload.password, payload.confirmation)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    persist_configuration()
    session = auth_service.login(payload.password, request.client.host if request.client else "unknown")
    assert session is not None
    set_session_cookie(response, session.session_id)
    return {"csrf_token": session.csrf_token}


@app.post("/api/auth/login")
def login(payload: PasswordLogin, request: Request, response: Response) -> dict[str, str]:
    session = auth_service.login(payload.password, request.client.host if request.client else "unknown")
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    set_session_cookie(response, session.session_id)
    return {"csrf_token": session.csrf_token}


@app.post("/api/auth/logout", dependencies=[Depends(require_authenticated)], status_code=204)
def logout(response: Response, session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> None:
    auth_service.logout(session_id)
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.get("/api/onboarding/status", response_model=OnboardingStatus, dependencies=[Depends(require_authenticated)])
def get_onboarding_status() -> OnboardingStatus:
    return OnboardingStatus(completed=onboarding_completed)


@app.post("/api/onboarding/complete", response_model=PublicAgentConfiguration, dependencies=[Depends(require_authenticated)])
def complete_onboarding(configuration: OnboardingConfiguration) -> PublicAgentConfiguration:
    global policy, heartbeat, provider, memory_settings, memory_service, onboarding_completed
    with configuration_lock:
        policy = configuration.policy.model_copy(update={"admin_telegram_ids": {configuration.owner_telegram_id}})
        heartbeat = configuration.heartbeat
        provider = configuration.provider
        memory_settings = configuration.memory
        memory_service = MemoryService(memory_settings)
        onboarding_completed = True
        persist_configuration()
    return public_configuration()


@app.post("/api/onboarding/telegram/start", dependencies=[Depends(require_authenticated)], status_code=204)
async def start_telegram_login(request: TelegramLoginRequest) -> None:
    try:
        await telegram_login.begin(request.api_id, request.api_hash, request.phone_number)
    except TelegramAuthError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram login is unavailable") from error


@app.post("/api/onboarding/telegram/confirm", dependencies=[Depends(require_authenticated)])
async def confirm_telegram_login(confirmation: TelegramLoginConfirmation) -> dict[str, int]:
    try:
        telegram_id = await telegram_login.complete(confirmation.code, confirmation.password)
    except TelegramAuthError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Telegram did not accept the credentials") from error
    return {"telegram_id": telegram_id}


@app.post("/api/onboarding/telegram/cancel", dependencies=[Depends(require_authenticated)], status_code=204)
async def cancel_telegram_login() -> None:
    await telegram_login.cancel()


@app.get("/api/configuration", response_model=PublicAgentConfiguration, dependencies=[Depends(require_authenticated)])
def get_configuration() -> PublicAgentConfiguration:
    return public_configuration()


@app.put("/api/configuration", response_model=PublicAgentConfiguration, dependencies=[Depends(require_authenticated)])
def set_configuration(configuration: AgentConfiguration) -> PublicAgentConfiguration:
    global policy, heartbeat, provider, memory_settings, memory_service
    with configuration_lock:
        policy = configuration.policy
        heartbeat = configuration.heartbeat
        provider = configuration.provider
        memory_settings = configuration.memory
        memory_service = MemoryService(memory_settings)
        persist_configuration()
    return public_configuration()


@app.get("/api/memory/stats", dependencies=[Depends(require_authenticated)])
def memory_stats(owner_id: int, user_id: int | None = None, chat_id: int | None = None) -> dict[str, int]:
    scope = MemoryScope(owner_id=owner_id, user_id=user_id, chat_id=chat_id)
    return memory_service.stats(scope).model_dump()


@app.delete("/api/memory", dependencies=[Depends(require_authenticated)])
def forget_memory(owner_id: int, user_id: int | None = None, chat_id: int | None = None) -> dict[str, int]:
    scope = MemoryScope(owner_id=owner_id, user_id=user_id, chat_id=chat_id)
    return {"deleted": memory_service.forget_scope(scope)}


@app.get("/api/heartbeat/plan", dependencies=[Depends(require_authenticated)])
def heartbeat_plan(hour: str, agent_id: str = "default") -> dict[str, object]:
    try:
        schedule = plan_hourly_heartbeat(heartbeat, datetime.fromisoformat(hour), agent_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return schedule.model_dump(mode="json")


def public_configuration() -> PublicAgentConfiguration:
    return PublicAgentConfiguration(
        policy=policy,
        heartbeat=heartbeat,
        provider=provider.public_configuration(),
        memory=memory_settings,
    )
