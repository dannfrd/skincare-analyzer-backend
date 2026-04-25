from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from database.db_connection import get_db_session
from sqlalchemy import text
from passlib.context import CryptContext
from jose import jwt
import base64
import json
import os
import logging
import time
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

load_dotenv()

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
_DEFAULT_CLOCK_SKEW_SECONDS = 60
_MAX_CLOCK_SKEW_SECONDS = 60

try:
    _raw_skew = int(os.getenv("FIREBASE_TOKEN_CLOCK_SKEW_SECONDS", str(_DEFAULT_CLOCK_SKEW_SECONDS)))
except ValueError:
    _raw_skew = _DEFAULT_CLOCK_SKEW_SECONDS

FIREBASE_CLOCK_SKEW_SECONDS = max(0, min(_raw_skew, _MAX_CLOCK_SKEW_SECONDS))

_SERVICE_ACCOUNT_FILENAME = "dermify-e69de-firebase-adminsdk-fbsvc-eb6e0455ca.json"
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Keep backward compatibility for existing bcrypt hashes while allowing long passwords.
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")

router = APIRouter(prefix="/auth", tags=["auth"])

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    provider: str = "manual"

class UserOut(BaseModel):
    id: int
    name: str | None = None
    email: EmailStr
    role: str | None = None
    provider: str | None = None
    firebase_uid: str | None = None

    class Config:
         from_attributes = True


class GoogleLoginPayload(BaseModel):
    id_token: str


def _ensure_firebase_initialized() -> None:
    try:
        firebase_admin.get_app()
        return
    except ValueError:
        pass

    credential_candidates = [
        os.getenv("FIREBASE_CREDENTIALS_PATH"),
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        os.path.join(_BACKEND_ROOT, _SERVICE_ACCOUNT_FILENAME),
    ]

    for candidate in credential_candidates:
        if candidate and os.path.exists(candidate):
            firebase_admin.initialize_app(credentials.Certificate(candidate))
            logger.info("Firebase Admin initialized using credential file: %s", candidate)
            return

    # Fall back to Application Default Credentials if available in environment.
    firebase_admin.initialize_app()
    logger.info("Firebase Admin initialized using Application Default Credentials")


def _decode_jwt_payload_without_verification(token: str) -> dict:
    """Best-effort decode payload JWT tanpa verifikasi signature untuk kebutuhan log diagnostik."""
    try:
        segments = token.split(".")
        if len(segments) != 3:
            return {}
        payload_segment = segments[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_segment + padding)
        decoded = json.loads(payload_bytes.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password minimal {MIN_PASSWORD_LENGTH} karakter.",
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password terlalu panjang (maksimal {MAX_PASSWORD_LENGTH} karakter).",
        )


def _get_users_table_columns(db: Session) -> set[str]:
    rows = db.execute(text("SHOW COLUMNS FROM users")).fetchall()
    columns: set[str] = set()
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else {}
        field_name = mapping.get("Field") if isinstance(mapping, dict) else None
        if not field_name:
            field_name = row[0]
        if field_name:
            columns.add(str(field_name))
    return columns


def _insert_user_with_available_columns(db: Session, payload: dict) -> int:
    available_columns = _get_users_table_columns(db)
    insert_payload = {key: value for key, value in payload.items() if key in available_columns}

    if "email" not in insert_payload or "password" not in insert_payload:
        raise HTTPException(status_code=500, detail="Skema tabel users tidak mendukung autentikasi saat ini.")

    column_sql = ", ".join(insert_payload.keys())
    value_sql = ", ".join(f":{key}" for key in insert_payload.keys())
    insert_sql = text(f"INSERT INTO users ({column_sql}) VALUES ({value_sql})")
    insert_result = db.execute(insert_sql, insert_payload)
    return insert_result.lastrowid


def _normalize_user_response(user_row) -> dict:
    user_dict = dict(user_row._mapping)
    user_dict.setdefault("provider", None)
    user_dict.setdefault("firebase_uid", None)
    user_dict.setdefault("role", None)
    return user_dict


def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db_session)):
    result = db.execute(
        text("SELECT * FROM users WHERE email = :email LIMIT 1"),
        {"email": payload.email}
    )
    user = result.fetchone()
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    # Konversi row ke dict agar bisa dipakai UserOut
    user_dict = _normalize_user_response(user)
    token = create_access_token({"sub": user_dict["email"], "id": user_dict["id"]})
    return {"token": token, "user": UserOut(**user_dict)}

@router.post("/register", status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db_session)):
    # Cek email sudah terdaftar
    result = db.execute(
        text("SELECT id FROM users WHERE email = :email LIMIT 1"),
        {"email": payload.email}
    )
    user_exist = result.scalar()
    if user_exist:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    _validate_password_policy(payload.password)
    hashed_pw = get_password_hash(payload.password)

    user_id = _insert_user_with_available_columns(
        db,
        {
            "name": payload.name,
            "email": payload.email,
            "password": hashed_pw,
            "role": "user",
            "provider": payload.provider,
        },
    )

    db.commit()
    user = db.execute(
        text("SELECT * FROM users WHERE id = :id"),
        {"id": user_id}
    ).fetchone()
    user_dict = _normalize_user_response(user)
    token = create_access_token({"sub": user_dict["email"], "id": user_dict["id"]})
    return {"token": token, "user": UserOut(**user_dict)}

@router.post("/google")
def google_login(
    payload: GoogleLoginPayload | None = None,
    id_token: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
):
    token_to_verify = payload.id_token if payload and payload.id_token else id_token
    if not token_to_verify:
        raise HTTPException(status_code=400, detail="id_token wajib dikirim")

    try:
        _ensure_firebase_initialized()
        decoded_token = firebase_auth.verify_id_token(
            token_to_verify,
            clock_skew_seconds=FIREBASE_CLOCK_SKEW_SECONDS,
        )
        email = decoded_token.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Token Google tidak mengandung email")
        name = decoded_token.get("name", "")
        firebase_uid = decoded_token.get("uid")
        if not firebase_uid:
            raise HTTPException(status_code=400, detail="Token Google tidak mengandung uid")
    except HTTPException:
        raise
    except Exception as exc:
        error_message = str(exc)
        raw_payload = _decode_jwt_payload_without_verification(token_to_verify)
        now_epoch = int(time.time())

        if "Token used too early" in error_message or "clock is set correctly" in error_message:
            issued_at = raw_payload.get("iat")
            not_before = raw_payload.get("nbf")
            token_start = issued_at if isinstance(issued_at, int) else not_before
            drift_seconds = token_start - now_epoch if isinstance(token_start, int) else None

            if isinstance(drift_seconds, int) and drift_seconds > 0:
                logger.warning(
                    "Google token rejected due to server clock drift. now=%s iat=%s nbf=%s drift_seconds=%s",
                    now_epoch,
                    issued_at,
                    not_before,
                    drift_seconds,
                )
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "Waktu server backend tertinggal dari waktu token Google. "
                        f"Perkiraan selisih: {drift_seconds} detik. "
                        "Sinkronkan tanggal/jam/timezone mesin backend, lalu coba login lagi."
                    ),
                )

            raise HTTPException(
                status_code=401,
                detail=(
                    "Waktu server backend tidak sinkron. "
                    "Silakan sinkronkan tanggal/jam/timezone pada mesin backend, lalu coba login lagi."
                ),
            )

        if "incorrect audience" in error_message or "incorrect \"iss\"" in error_message:
            logger.warning(
                "Google token project mismatch. aud=%s iss=%s", raw_payload.get("aud"), raw_payload.get("iss")
            )
            raise HTTPException(
                status_code=401,
                detail=(
                    "Token Google berasal dari project Firebase yang berbeda dengan backend. "
                    "Samakan konfigurasi Firebase app dan service account backend."
                ),
            )

        if "has expired" in error_message:
            raise HTTPException(
                status_code=401,
                detail="Token Google sudah kedaluwarsa. Silakan login ulang untuk mendapatkan token baru.",
            )

        logger.exception("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token Google tidak valid")

    result = db.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email}
    )
    user = result.fetchone()
    if not user:
        user_id = _insert_user_with_available_columns(
            db,
            {
                "name": name,
                "email": email,
                "password": "",
                "role": "user",
                "provider": "google",
                "firebase_uid": firebase_uid,
            },
        )
        db.commit()
        user = db.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_id}
        ).fetchone()
    user_dict = _normalize_user_response(user)
    token = create_access_token({"sub": user_dict["email"], "id": user_dict["id"]})
    return {"token": token, "user": UserOut(**user_dict)}
