import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import desc, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .demo_data import (
    create_demo_command,
    demo_alerts,
    demo_device,
    demo_status,
    demo_telemetry,
    list_demo_commands,
)
from .email_delivery import deliver_account_email
from .logging_config import configure_logging
from .models import Alert, Device, DeviceCommand, FeedingExecution, FeedingSchedule, TelemetryRecord, User
from .rate_limit import rate_limiter
from .schemas import (
    AccountTokenRequest,
    AlertOut,
    CommandComplete,
    CommandCreate,
    CommandOut,
    DeviceCreate,
    DeviceOut,
    DevicePairingResult,
    DevicePairRequest,
    DeviceProvisioned,
    DeviceStatus,
    FeedingExecutionOut,
    HealthResponse,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegistrationRequest,
    ReliabilityScanOut,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
    TelemetryIn,
    TelemetryOut,
    Token,
    UserOut,
)
from .security import (
    create_access_token,
    create_account_action_token,
    decode_account_action_token,
    get_current_user,
    hash_device_key,
    hash_pairing_code,
    hash_password,
    require_account_user,
    require_customer,
    require_operator,
    verify_device_key,
    verify_password,
)
from .services import (
    create_alert,
    ensure_incident_alert,
    match_schedule_for_event,
    reconcile_scheduled_feed_completion,
    resolve_alert_categories,
    scan_reliability,
)

settings = get_settings()
configure_logging()
logger = logging.getLogger("fish_feeder")


def seed_bootstrap_records(db: Session) -> None:
    if settings.demo_enabled and settings.demo_username == settings.admin_username:
        raise RuntimeError("Demo and administrator usernames must be different")
    user = db.scalar(select(User).where(User.username == settings.admin_username))
    if user is None:
        db.add(
            User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="operator",
                email_verified=True,
            )
        )
    else:
        user.role = "operator"
        user.email_verified = True
    demo_users = list(db.scalars(select(User).where(User.role == "demo")))
    for existing_demo in demo_users:
        if not settings.demo_enabled or existing_demo.username != settings.demo_username:
            existing_demo.active = False
    if settings.demo_enabled:
        demo_user = db.scalar(select(User).where(User.username == settings.demo_username))
        if demo_user is None:
            db.add(
                User(
                    username=settings.demo_username,
                    password_hash=hash_password(settings.demo_password),
                    role="demo",
                    email_verified=True,
                )
            )
        else:
            demo_user.role = "demo"
            demo_user.active = True
            demo_user.email_verified = True
            if not verify_password(settings.demo_password, demo_user.password_hash):
                demo_user.password_hash = hash_password(settings.demo_password)
    device = db.scalar(select(Device).where(Device.device_uid == settings.bootstrap_device_uid))
    if device is None:
        db.add(
            Device(
                device_uid=settings.bootstrap_device_uid,
                name="Bootstrap Fish Feeder",
                api_key_hash=hash_device_key(settings.device_api_key),
            )
        )
    elif not device.api_key_hash:
        device.api_key_hash = hash_device_key(settings.device_api_key)
    db.commit()


async def reliability_worker(stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.reliability_scan_interval_seconds)
            return
        except TimeoutError:
            with SessionLocal() as db:
                try:
                    scan_reliability(db, datetime.now(UTC), settings.offline_after_seconds)
                except Exception:
                    logger.exception("reliability_scan_failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_bootstrap_records(db)
    stop = asyncio.Event()
    worker = asyncio.create_task(reliability_worker(stop))
    yield
    stop.set()
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


app = FastAPI(
    title="Smart Fish Feeder Digital Twin API",
    version="5.0.0",
    root_path=settings.root_path,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Device-ID", "X-Device-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
        },
    )
    return response


def rate_limit_or_429(key: str, limit: int) -> None:
    if not rate_limiter.allow(key, limit):
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"})


def get_device_or_401(db: Session, device_uid: str, api_key: str) -> Device:
    device = db.scalar(select(Device).where(Device.device_uid == device_uid, Device.active.is_(True)))
    if device is None or not verify_device_key(api_key, device.api_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device credentials")
    return device


def get_device_or_404(db: Session, device_uid: str) -> Device:
    device = db.scalar(select(Device).where(Device.device_uid == device_uid))
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def get_accessible_device_or_404(db: Session, device_uid: str, user: User) -> Device:
    query = select(Device).where(Device.device_uid == device_uid)
    if user.role == "customer":
        query = query.where(Device.owner_user_id == user.id)
    elif user.role != "operator":
        raise HTTPException(status_code=404, detail="Device not found")
    device = db.scalar(query)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def scope_device_records(query, user: User):  # type: ignore[no-untyped-def]
    if user.role == "customer":
        return query.join(Device).where(Device.owner_user_id == user.id)
    if user.role == "operator":
        return query
    raise HTTPException(status_code=403, detail="This account cannot access production resources")


def get_accessible_schedule_or_404(db: Session, schedule_id: int, user: User) -> FeedingSchedule:
    query = select(FeedingSchedule).join(Device).where(FeedingSchedule.id == schedule_id)
    if user.role == "customer":
        query = query.where(Device.owner_user_id == user.id)
    schedule = db.scalar(query)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


def get_accessible_alert_or_404(db: Session, alert_id: int, user: User) -> Alert:
    query = select(Alert).join(Device).where(Alert.id == alert_id)
    if user.role == "customer":
        query = query.where(Device.owner_user_id == user.id)
    alert = db.scalar(query)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


def new_pairing_code() -> str:
    return secrets.token_urlsafe(12).upper()


def pairing_url(device_uid: str, pairing_code: str) -> str:
    return (
        f"{settings.public_app_url.rstrip('/')}?device_uid={quote(device_uid)}"
        f"&pairing_code={quote(pairing_code)}#dashboard"
    )


def account_user_from_token(db: Session, token: str, purpose: str) -> User:
    try:
        payload = decode_account_action_token(token, purpose)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user_id = payload.get("uid")
    username = payload.get("sub")
    if not isinstance(user_id, int) or not isinstance(username, str):
        raise HTTPException(status_code=400, detail="This account link is invalid or has expired")
    user = db.get(User, user_id)
    if user is None or user.username != username or not user.active:
        raise HTTPException(status_code=400, detail="This account link is invalid or has expired")
    email_fingerprint = hashlib.sha256((user.email or "").encode()).hexdigest()
    if not secrets.compare_digest(str(payload.get("email", "")), email_fingerprint):
        raise HTTPException(status_code=400, detail="This account link is no longer valid")
    if purpose == "password-reset":
        password_fingerprint = hashlib.sha256(user.password_hash.encode()).hexdigest()
        if not secrets.compare_digest(str(payload.get("pwd", "")), password_fingerprint):
            raise HTTPException(status_code=400, detail="This password reset link has already been used")
    return user


def send_verification_email(user: User) -> None:
    if not user.email:
        return
    token = create_account_action_token(user, "verify-email", settings.email_verification_expire_minutes)
    link = f"{settings.public_app_url.rstrip('/')}?verify_token={quote(token)}#dashboard"
    deliver_account_email(
        user.email,
        "Verify your Smart Fish Feeder account",
        f"Welcome to Smart Fish Feeder. Verify your email to activate your account:\n\n{link}\n\n"
        "If you did not create this account, ignore this message.",
    )


def send_password_reset_email(user: User) -> None:
    if not user.email:
        return
    token = create_account_action_token(user, "password-reset", settings.password_reset_expire_minutes)
    link = f"{settings.public_app_url.rstrip('/')}?reset_token={quote(token)}#dashboard"
    deliver_account_email(
        user.email,
        "Reset your Smart Fish Feeder password",
        f"Use this link to choose a new password:\n\n{link}\n\n"
        f"The link expires in {settings.password_reset_expire_minutes} minutes. "
        "If you did not request it, ignore this message.",
    )


def device_is_online(device: Device, now: datetime | None = None) -> bool:
    last_seen = device.last_seen_at
    if last_seen is None:
        return False
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return (current - last_seen).total_seconds() <= settings.offline_after_seconds


def telemetry_payload_hash(payload: TelemetryIn) -> str:
    canonical = {
        "cooling_on": payload.cooling_on,
        "device_uid": payload.device_uid,
        "event_type": payload.event_type,
        "idempotency_key": payload.idempotency_key,
        "pump_state": payload.pump_state,
        "recorded_at": payload.recorded_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "schedule_id": payload.schedule_id,
        "sensor_status": payload.sensor_status,
        "sequence_number": payload.sequence_number,
        "temperature_c": payload.temperature_c,
    }
    encoded = json.dumps(canonical, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Smart Fish Feeder Digital Twin API",
        "version": "5.0.0",
        "docs": f"{settings.root_path}/docs",
    }


@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="healthy", database="connected")


@app.post("/auth/register", response_model=MessageResponse, status_code=202)
def register_customer(
    request: Request,
    payload: RegistrationRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    client = request.client.host if request.client else "unknown"
    rate_limit_or_429(f"register:{client}:{payload.email}", settings.registration_rate_limit_per_minute)
    existing = db.scalar(select(User).where(or_(User.email == payload.email, User.username == payload.email)))
    if existing is None:
        user = User(
            username=payload.email,
            email=payload.email,
            email_verified=False,
            password_hash=hash_password(payload.password),
            role="customer",
            active=True,
        )
        db.add(user)
        try:
            # Flush first so the signed verification token can include the user ID,
            # but keep the transaction reversible until SMTP accepts the message.
            db.flush()
            send_verification_email(user)
            db.commit()
        except IntegrityError:
            db.rollback()
            return MessageResponse(message="Check your email for an account verification link.")
        except Exception as exc:
            db.rollback()
            logger.exception("verification_email_delivery_failed", extra={"user_id": user.id})
            raise HTTPException(status_code=503, detail="Verification email could not be sent") from exc
    elif existing.role == "customer" and not existing.email_verified and existing.active:
        try:
            send_verification_email(existing)
        except Exception as exc:
            logger.exception("verification_email_delivery_failed", extra={"user_id": existing.id})
            raise HTTPException(status_code=503, detail="Verification email could not be sent") from exc
    return MessageResponse(message="Check your email for an account verification link.")


@app.post("/auth/verify-email", response_model=MessageResponse)
def verify_customer_email(payload: AccountTokenRequest, db: Session = Depends(get_db)) -> MessageResponse:
    user = account_user_from_token(db, payload.token, "verify-email")
    if user.role != "customer":
        raise HTTPException(status_code=400, detail="This verification link is not for a customer account")
    user.email_verified = True
    db.commit()
    return MessageResponse(message="Email verified. You can now sign in and pair your feeder.")


@app.post("/auth/verification/resend", response_model=MessageResponse, status_code=202)
def resend_customer_verification(
    request: Request,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    client = request.client.host if request.client else "unknown"
    rate_limit_or_429(f"verify-resend:{client}:{payload.email}", settings.registration_rate_limit_per_minute)
    user = db.scalar(
        select(User).where(
            User.email == payload.email,
            User.role == "customer",
            User.active.is_(True),
            User.email_verified.is_(False),
        )
    )
    if user is not None:
        try:
            send_verification_email(user)
        except Exception as exc:
            logger.exception("verification_email_delivery_failed", extra={"user_id": user.id})
            raise HTTPException(status_code=503, detail="Verification email could not be sent") from exc
    return MessageResponse(message="If the account needs verification, a new link has been sent.")


@app.post("/auth/password-reset/request", response_model=MessageResponse, status_code=202)
def request_customer_password_reset(
    request: Request,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    client = request.client.host if request.client else "unknown"
    rate_limit_or_429(f"password-reset:{client}:{payload.email}", settings.password_reset_rate_limit_per_minute)
    user = db.scalar(
        select(User).where(
            User.email == payload.email,
            User.role == "customer",
            User.active.is_(True),
            User.email_verified.is_(True),
        )
    )
    if user is not None:
        try:
            send_password_reset_email(user)
        except Exception as exc:
            logger.exception("password_reset_email_delivery_failed", extra={"user_id": user.id})
            raise HTTPException(status_code=503, detail="Password reset email could not be sent") from exc
    return MessageResponse(message="If that account exists, a password reset link has been sent.")


@app.post("/auth/password-reset/confirm", response_model=MessageResponse)
def confirm_customer_password_reset(
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db),
) -> MessageResponse:
    user = account_user_from_token(db, payload.token, "password-reset")
    if user.role != "customer" or not user.email_verified:
        raise HTTPException(status_code=400, detail="This password reset link is not valid")
    user.password_hash = hash_password(payload.password)
    user.auth_version += 1
    db.commit()
    return MessageResponse(message="Password updated. Sign in with your new password.")


@app.post("/auth/token", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    client = request.client.host if request.client else "unknown"
    identifier = form.username.strip().lower()
    is_demo_login = settings.demo_enabled and identifier == settings.demo_username.lower()
    login_limit = settings.demo_login_rate_limit_per_minute if is_demo_login else settings.login_rate_limit_per_minute
    rate_limit_or_429(f"login:{client}:{identifier}", login_limit)
    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == identifier, func.lower(User.email) == identifier),
            User.active.is_(True),
        )
    )
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role == "customer" and not user.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before signing in")
    return Token(access_token=create_access_token(user))


@app.get("/users/me", response_model=UserOut)
def current_user(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@app.post("/devices", response_model=DeviceProvisioned, status_code=201)
def provision_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
) -> DeviceProvisioned:
    if db.scalar(select(Device.id).where(Device.device_uid == payload.device_uid)) is not None:
        raise HTTPException(status_code=409, detail="Device UID already exists")
    api_key = secrets.token_urlsafe(32)
    pairing_code = new_pairing_code()
    device = Device(
        device_uid=payload.device_uid,
        name=payload.name,
        api_key_hash=hash_device_key(api_key),
        pairing_code_hash=hash_pairing_code(pairing_code),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return DeviceProvisioned(
        api_key=api_key,
        pairing_code=pairing_code,
        pairing_url=pairing_url(device.device_uid, pairing_code),
        **DeviceOut.model_validate(device).model_dump(),
    )


@app.get("/devices", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DeviceOut]:
    if user.role == "demo":
        return [demo_device(settings.demo_device_uid)]
    query = select(Device).order_by(Device.device_uid)
    if user.role == "customer":
        query = query.where(Device.owner_user_id == user.id)
    elif user.role != "operator":
        raise HTTPException(status_code=403, detail="This account cannot access production resources")
    return [DeviceOut.model_validate(device) for device in db.scalars(query)]


@app.post("/devices/pair", response_model=DevicePairingResult)
def pair_device(
    request: Request,
    payload: DevicePairRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_customer),
) -> DevicePairingResult:
    client = request.client.host if request.client else "unknown"
    rate_limit_or_429(f"pair:{client}:{user.id}", settings.pairing_rate_limit_per_minute)
    device = db.scalar(select(Device).where(Device.device_uid == payload.device_uid, Device.active.is_(True)))
    if (
        device is None
        or device.pairing_code_hash is None
        or not secrets.compare_digest(hash_pairing_code(payload.pairing_code), device.pairing_code_hash)
    ):
        raise HTTPException(status_code=404, detail="Device UID or pairing code is invalid")
    if device.owner_user_id is not None and device.owner_user_id != user.id:
        raise HTTPException(status_code=409, detail="This feeder is already paired to another account")
    device.owner_user_id = user.id
    device.pairing_code_hash = None
    db.commit()
    db.refresh(device)
    return DevicePairingResult.model_validate(device)


@app.post("/devices/{device_uid}/pairing-code", response_model=DevicePairingResult)
def rotate_pairing_code(
    device_uid: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
) -> DevicePairingResult:
    device = get_device_or_404(db, device_uid)
    pairing_code = new_pairing_code()
    device.pairing_code_hash = hash_pairing_code(pairing_code)
    db.commit()
    db.refresh(device)
    return DevicePairingResult(
        pairing_code=pairing_code,
        pairing_url=pairing_url(device.device_uid, pairing_code),
        **DeviceOut.model_validate(device).model_dump(),
    )


@app.delete("/devices/{device_uid}/pairing", response_model=DevicePairingResult)
def unpair_device(
    device_uid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DevicePairingResult:
    device = get_accessible_device_or_404(db, device_uid, user)
    pairing_code = new_pairing_code()
    device.owner_user_id = None
    device.pairing_code_hash = hash_pairing_code(pairing_code)
    db.commit()
    db.refresh(device)
    return DevicePairingResult(
        pairing_code=pairing_code,
        pairing_url=pairing_url(device.device_uid, pairing_code),
        **DeviceOut.model_validate(device).model_dump(),
    )


@app.post("/devices/{device_uid}/rotate-key", response_model=DeviceProvisioned)
def rotate_device_key(
    device_uid: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
) -> DeviceProvisioned:
    device = get_device_or_404(db, device_uid)
    api_key = secrets.token_urlsafe(32)
    device.api_key_hash = hash_device_key(api_key)
    db.commit()
    db.refresh(device)
    return DeviceProvisioned(api_key=api_key, **DeviceOut.model_validate(device).model_dump())


@app.post("/telemetry", response_model=TelemetryOut)
def ingest_telemetry(
    request: Request,
    payload: TelemetryIn,
    db: Session = Depends(get_db),
    x_device_id: str = Header(..., alias="X-Device-ID"),
    x_device_key: str = Header(..., alias="X-Device-Key"),
) -> TelemetryRecord:
    if payload.device_uid != x_device_id:
        raise HTTPException(status_code=400, detail="Header and payload device IDs do not match")
    client = request.client.host if request.client else "unknown"
    rate_limit_or_429(f"telemetry-attempt:{client}", settings.credential_attempt_rate_limit_per_minute)
    device = get_device_or_401(db, x_device_id, x_device_key)
    device_id = device.id
    device_uid = device.device_uid
    rate_limit_or_429(f"telemetry-device:{device_id}", settings.telemetry_rate_limit_per_minute)

    if device.last_sequence_number is not None and payload.sequence_number <= device.last_sequence_number:
        existing = db.scalar(
            select(TelemetryRecord).where(
                TelemetryRecord.device_id == device_id,
                TelemetryRecord.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Out-of-order telemetry sequence")

    if payload.recorded_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="recorded_at must include a timezone")
    recorded_at = payload.recorded_at.astimezone(UTC)
    now = datetime.now(UTC)
    age_seconds = (now - recorded_at).total_seconds()
    if age_seconds > settings.max_telemetry_age_seconds:
        raise HTTPException(status_code=422, detail="Telemetry is too old")
    if age_seconds < -settings.max_future_skew_seconds:
        raise HTTPException(status_code=422, detail="Telemetry timestamp is too far in the future")
    payload_hash = telemetry_payload_hash(payload)

    existing = db.scalar(
        select(TelemetryRecord).where(
            TelemetryRecord.device_id == device_id,
            TelemetryRecord.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.payload_hash is not None and secrets.compare_digest(existing.payload_hash, payload_hash):
            return existing
        raise HTTPException(status_code=409, detail="Idempotency key is already used by different telemetry")

    alert_level, alert_message, alert_category = create_alert(
        payload.temperature_c, payload.pump_state, payload.sensor_status
    )
    record = TelemetryRecord(
        device_id=device_id,
        idempotency_key=payload.idempotency_key,
        payload_hash=payload_hash,
        sequence_number=payload.sequence_number,
        recorded_at=recorded_at,
        temperature_c=payload.temperature_c,
        cooling_on=payload.cooling_on,
        pump_state=payload.pump_state,
        sensor_status=payload.sensor_status,
        event_type=payload.event_type,
        alert_level=alert_level,
        alert_message=alert_message,
    )
    try:
        db.add(record)
        db.flush()
        device.last_sequence_number = payload.sequence_number
        device.last_seen_at = now

        resolved_categories = {"DEVICE_OFFLINE"}
        if payload.sensor_status == "OK":
            resolved_categories.add("SENSOR_FAILURE")
        if payload.pump_state != "ERROR":
            resolved_categories.add("PUMP_FAILURE")
        if payload.temperature_c is not None and 2.5 <= payload.temperature_c <= 5.0:
            resolved_categories.add("TEMPERATURE")
        resolve_alert_categories(db, device_id, resolved_categories, now)

        if alert_category and alert_message:
            ensure_incident_alert(
                db,
                device_id=device_id,
                telemetry_id=record.id,
                category=alert_category,
                level=alert_level,
                message=alert_message,
            )
        if payload.event_type in {"scheduled_feeding", "manual_feeding"}:
            schedule_id = payload.schedule_id
            if schedule_id is not None:
                schedule = db.scalar(
                    select(FeedingSchedule).where(
                        FeedingSchedule.id == schedule_id, FeedingSchedule.device_id == device_id
                    )
                )
                if schedule is None:
                    raise HTTPException(status_code=422, detail="Schedule does not belong to this device")
            elif payload.event_type == "scheduled_feeding":
                matched = match_schedule_for_event(db, device_id, recorded_at)
                schedule_id = matched.id if matched is not None else None
            active_execution_id = db.scalar(
                select(FeedingExecution.id).where(
                    FeedingExecution.device_id == device_id,
                    FeedingExecution.status == "STARTED",
                )
            )
            if active_execution_id is None:
                db.add(
                    FeedingExecution(
                        device_id=device_id,
                        schedule_id=schedule_id,
                        telemetry_id=record.id,
                        execution_type="SCHEDULED" if payload.event_type == "scheduled_feeding" else "MANUAL",
                        status="STARTED",
                        started_at=recorded_at,
                    )
                )
        elif payload.event_type == "feeding_cycle_completed":
            active_execution = db.scalar(
                select(FeedingExecution)
                .where(
                    FeedingExecution.device_id == device_id,
                    FeedingExecution.status == "STARTED",
                )
                .order_by(desc(FeedingExecution.started_at))
            )
            if active_execution is not None:
                active_execution.status = "SUCCESS"
                active_execution.completed_at = recorded_at
        elif payload.sensor_status != "OK" or payload.pump_state == "ERROR":
            active_execution = db.scalar(
                select(FeedingExecution)
                .where(
                    FeedingExecution.device_id == device_id,
                    FeedingExecution.status == "STARTED",
                )
                .order_by(desc(FeedingExecution.started_at))
            )
            if active_execution is not None:
                active_execution.status = "FAILED"
                active_execution.completed_at = recorded_at
                active_execution.details = alert_message or "Device reported a feeding-cycle failure."
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(TelemetryRecord).where(
                TelemetryRecord.device_id == device_id,
                TelemetryRecord.idempotency_key == payload.idempotency_key,
            )
        )
        if duplicate is not None:
            if duplicate.payload_hash is not None and secrets.compare_digest(duplicate.payload_hash, payload_hash):
                return duplicate
            raise HTTPException(
                status_code=409, detail="Idempotency key is already used by different telemetry"
            ) from exc
        sequence_conflict = db.scalar(
            select(TelemetryRecord.id).where(
                TelemetryRecord.device_id == device_id,
                TelemetryRecord.sequence_number == payload.sequence_number,
            )
        )
        if sequence_conflict is not None:
            raise HTTPException(status_code=409, detail="Telemetry sequence number is already used") from exc
        raise HTTPException(status_code=409, detail="Duplicate or conflicting telemetry") from exc
    db.refresh(record)
    logger.info("telemetry_ingested", extra={"device_uid": device_uid})
    return record


@app.get("/telemetry", response_model=list[TelemetryOut])
def list_telemetry(
    limit: int = Query(50, ge=1, le=500),
    device_uid: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TelemetryOut]:
    if user.role == "demo":
        if device_uid not in {None, settings.demo_device_uid}:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return demo_telemetry()[-limit:]
    query = select(TelemetryRecord).order_by(desc(TelemetryRecord.created_at)).limit(limit)
    if device_uid:
        device = get_accessible_device_or_404(db, device_uid, user)
        query = query.where(TelemetryRecord.device_id == device.id)
    else:
        query = scope_device_records(query, user)
    records = list(db.scalars(query))
    return [TelemetryOut.model_validate(record) for record in reversed(records)]


@app.get("/device-status", response_model=DeviceStatus)
def get_device_status(
    device_uid: str = "feeder-001",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeviceStatus:
    if user.role == "demo":
        if device_uid != settings.demo_device_uid:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return demo_status(settings.demo_device_uid)
    device: Device | None
    if user.role == "customer":
        device = get_accessible_device_or_404(db, device_uid, user)
    elif user.role == "operator":
        device = db.scalar(select(Device).where(Device.device_uid == device_uid))
    else:
        raise HTTPException(status_code=403, detail="This account cannot access production resources")
    latest = (
        None
        if device is None
        else db.scalar(
            select(TelemetryRecord)
            .where(TelemetryRecord.device_id == device.id)
            .order_by(desc(TelemetryRecord.created_at))
        )
    )
    if device is None or latest is None:
        return DeviceStatus(
            device_uid=device_uid,
            online=False,
            temperature_c=None,
            cooling_on=None,
            pump_state=None,
            sensor_status=None,
            alert_level="unknown",
            alert_message="No telemetry has been received yet.",
            last_event_type=None,
            last_sequence_number=None,
            last_seen=None,
        )
    online = device_is_online(device)
    return DeviceStatus(
        device_uid=device_uid,
        online=online,
        temperature_c=latest.temperature_c,
        cooling_on=latest.cooling_on,
        pump_state=latest.pump_state,
        sensor_status=latest.sensor_status,
        alert_level=latest.alert_level if online else "warning",
        alert_message=latest.alert_message if online else "Device heartbeat is stale.",
        last_event_type=latest.event_type,
        last_sequence_number=device.last_sequence_number,
        last_seen=device.last_seen_at,
    )


@app.post("/devices/{device_uid}/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(
    device_uid: str,
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_account_user),
) -> FeedingSchedule:
    device = get_accessible_device_or_404(db, device_uid, user)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone") from exc
    schedule = FeedingSchedule(
        device_id=device.id,
        name=payload.name,
        hour=payload.hour,
        minute=payload.minute,
        days_of_week=",".join(str(day) for day in payload.days_of_week),
        timezone=payload.timezone,
        grace_minutes=payload.grace_minutes,
        enabled=payload.enabled,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@app.get("/devices/{device_uid}/schedules", response_model=list[ScheduleOut])
def list_schedules(
    device_uid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScheduleOut]:
    if user.role == "demo":
        if device_uid != settings.demo_device_uid:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return []
    device = get_accessible_device_or_404(db, device_uid, user)
    return [
        ScheduleOut.model_validate(schedule)
        for schedule in db.scalars(select(FeedingSchedule).where(FeedingSchedule.device_id == device.id))
    ]


@app.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_account_user),
) -> FeedingSchedule:
    schedule = get_accessible_schedule_or_404(db, schedule_id, user)
    updates = payload.model_dump(exclude_unset=True)
    if "days_of_week" in updates:
        days = updates.pop("days_of_week")
        if not days or any(day < 0 or day > 6 for day in days):
            raise HTTPException(status_code=422, detail="days_of_week values must be between 0 and 6")
        schedule.days_of_week = ",".join(str(day) for day in sorted(set(days)))
    if "timezone" in updates:
        timezone_name = updates["timezone"]
        if not isinstance(timezone_name, str):
            raise HTTPException(status_code=422, detail="timezone cannot be null")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone") from exc
    for field, value in updates.items():
        if value is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        setattr(schedule, field, value)
    db.commit()
    db.refresh(schedule)
    return schedule


@app.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_account_user),
) -> Response:
    schedule = get_accessible_schedule_or_404(db, schedule_id, user)
    if db.scalar(select(FeedingExecution.id).where(FeedingExecution.schedule_id == schedule_id)) is not None:
        raise HTTPException(
            status_code=409, detail="Schedule with execution history cannot be deleted; disable it instead"
        )
    db.delete(schedule)
    db.commit()
    return Response(status_code=204)


@app.get("/feeding-executions", response_model=list[FeedingExecutionOut])
def list_feeding_executions(
    limit: int = Query(50, ge=1, le=500),
    device_uid: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FeedingExecutionOut]:
    if user.role == "demo":
        if device_uid not in {None, settings.demo_device_uid}:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return []
    query = select(FeedingExecution).order_by(desc(FeedingExecution.created_at)).limit(limit)
    if device_uid:
        device = get_accessible_device_or_404(db, device_uid, user)
        query = query.where(FeedingExecution.device_id == device.id)
    else:
        query = scope_device_records(query, user)
    return [FeedingExecutionOut.model_validate(execution) for execution in db.scalars(query)]


@app.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    limit: int = Query(20, ge=1, le=100),
    unacknowledged_only: bool = False,
    device_uid: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AlertOut]:
    if user.role == "demo":
        if device_uid not in {None, settings.demo_device_uid}:
            raise HTTPException(status_code=404, detail="Demo device not found")
        alerts = demo_alerts()
        return [alert for alert in alerts if not unacknowledged_only or alert.acknowledged_at is None][:limit]
    query = select(Alert).order_by(desc(Alert.created_at)).limit(limit)
    if unacknowledged_only:
        query = query.where(Alert.acknowledged_at.is_(None))
    if device_uid:
        device = get_accessible_device_or_404(db, device_uid, user)
        query = query.where(Alert.device_id == device.id)
    else:
        query = scope_device_records(query, user)
    return [AlertOut.model_validate(alert) for alert in db.scalars(query)]


@app.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_account_user),
) -> Alert:
    alert = get_accessible_alert_or_404(db, alert_id, user)
    if alert.acknowledged_at is None:
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by_user_id = user.id
        db.commit()
        db.refresh(alert)
    return alert


@app.post("/devices/{device_uid}/commands", response_model=CommandOut, status_code=201)
def create_command(
    device_uid: str,
    payload: CommandCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeviceCommand | CommandOut:
    if user.role == "demo":
        if device_uid != settings.demo_device_uid:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return create_demo_command(payload, settings.manual_command_ttl_seconds)
    device = get_accessible_device_or_404(db, device_uid, user)
    now = datetime.now(UTC)
    actuation_commands = {"FEED_NOW", "CLEAN_PUMP", "SET_COOLING"}
    if (
        settings.require_online_for_actuation
        and payload.command_type in actuation_commands
        and not device_is_online(device, now)
    ):
        raise HTTPException(status_code=409, detail="Device is offline; refusing an actuation command")
    payload_json = json.dumps(payload.payload, separators=(",", ":"), sort_keys=True)
    existing = db.scalar(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.command_type != payload.command_type or existing.payload_json != payload_json:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for another command")
        return existing
    command = DeviceCommand(
        device_id=device.id,
        idempotency_key=payload.idempotency_key,
        command_type=payload.command_type,
        payload_json=payload_json,
        requested_by_user_id=user.id,
        expires_at=now + timedelta(seconds=settings.manual_command_ttl_seconds),
    )
    db.add(command)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = db.scalar(
            select(DeviceCommand).where(
                DeviceCommand.device_id == device.id,
                DeviceCommand.idempotency_key == payload.idempotency_key,
            )
        )
        if concurrent is None:
            raise HTTPException(status_code=409, detail="Command conflicts with an existing record") from exc
        if concurrent.command_type != payload.command_type or concurrent.payload_json != payload_json:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for another command") from exc
        return concurrent
    db.refresh(command)
    return command


@app.get("/devices/{device_uid}/commands", response_model=list[CommandOut])
def list_commands(
    device_uid: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommandOut]:
    if user.role == "demo":
        if device_uid != settings.demo_device_uid:
            raise HTTPException(status_code=404, detail="Demo device not found")
        return list_demo_commands(limit)
    device = get_accessible_device_or_404(db, device_uid, user)
    return [
        CommandOut.model_validate(command)
        for command in db.scalars(
            select(DeviceCommand)
            .where(DeviceCommand.device_id == device.id)
            .order_by(desc(DeviceCommand.created_at))
            .limit(limit)
        )
    ]


@app.post("/device-commands/claim", response_model=list[CommandOut])
def claim_commands(
    db: Session = Depends(get_db),
    x_device_id: str = Header(..., alias="X-Device-ID"),
    x_device_key: str = Header(..., alias="X-Device-Key"),
) -> list[DeviceCommand]:
    device = get_device_or_401(db, x_device_id, x_device_key)
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(seconds=settings.command_lease_seconds)
    db.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.expires_at.is_(None),
            DeviceCommand.status.in_(("PENDING", "CLAIMED")),
        )
        .values(status="EXPIRED", completed_at=now, result="missing_delivery_deadline")
    )
    db.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.expires_at.is_not(None),
            DeviceCommand.expires_at <= now,
            DeviceCommand.status == "PENDING",
        )
        .values(status="EXPIRED", completed_at=now, result="expired_before_delivery")
    )
    db.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.expires_at.is_not(None),
            DeviceCommand.expires_at <= now - timedelta(seconds=settings.command_result_grace_seconds),
            DeviceCommand.status == "CLAIMED",
        )
        .values(status="EXPIRED", completed_at=now, result="terminal_result_timeout_after_claim")
    )
    eligible_ids = list(
        db.scalars(
            select(DeviceCommand.id)
            .where(
                DeviceCommand.device_id == device.id,
                DeviceCommand.expires_at > now,
                or_(
                    DeviceCommand.status == "PENDING",
                    (DeviceCommand.status == "CLAIMED") & (DeviceCommand.lease_expires_at < now),
                ),
            )
            .order_by(DeviceCommand.created_at)
            .limit(10)
        )
    )
    commands: list[DeviceCommand] = []
    for command_id in eligible_ids:
        claimed = db.execute(
            update(DeviceCommand)
            .where(
                DeviceCommand.id == command_id,
                DeviceCommand.expires_at.is_not(None),
                DeviceCommand.expires_at > now,
                or_(
                    DeviceCommand.status == "PENDING",
                    (DeviceCommand.status == "CLAIMED") & (DeviceCommand.lease_expires_at < now),
                ),
            )
            .values(status="CLAIMED", claimed_at=now, lease_expires_at=lease_expires_at)
        )
        if claimed.rowcount == 1:
            command = db.get(DeviceCommand, command_id)
            if command is not None:
                commands.append(command)
    db.commit()
    return commands


@app.post("/device-commands/{command_id}/complete", response_model=CommandOut)
def complete_command(
    command_id: int,
    payload: CommandComplete,
    db: Session = Depends(get_db),
    x_device_id: str = Header(..., alias="X-Device-ID"),
    x_device_key: str = Header(..., alias="X-Device-Key"),
) -> DeviceCommand:
    device = get_device_or_401(db, x_device_id, x_device_key)
    command = db.scalar(
        select(DeviceCommand).where(DeviceCommand.id == command_id, DeviceCommand.device_id == device.id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status in {"COMPLETED", "FAILED"}:
        if command.status == payload.status and command.result == payload.result:
            if (
                payload.status == "COMPLETED"
                and command.completed_at is not None
                and reconcile_scheduled_feed_completion(db, command, command.completed_at)
            ):
                db.commit()
            return command
        raise HTTPException(status_code=409, detail="Command already has a terminal result")
    if command.status == "EXPIRED" and command.claimed_at is None:
        raise HTTPException(status_code=409, detail="Command expired before delivery")
    if command.status not in {"CLAIMED", "EXPIRED"}:
        raise HTTPException(status_code=409, detail="Command is not in CLAIMED state")
    completed_at = datetime.now(UTC)
    command.status = payload.status
    command.result = payload.result
    command.completed_at = completed_at
    if payload.status == "COMPLETED":
        reconcile_scheduled_feed_completion(db, command, completed_at)
    db.commit()
    db.refresh(command)
    return command


@app.post("/reliability/scan", response_model=ReliabilityScanOut)
def run_reliability_scan(
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
) -> ReliabilityScanOut:
    missed, offline, commands = scan_reliability(db, datetime.now(UTC), settings.offline_after_seconds)
    return ReliabilityScanOut(
        missed_feedings_created=missed,
        offline_alerts_created=offline,
        scheduled_commands_created=commands,
    )
