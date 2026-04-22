from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from database.db_connection import get_db_session
from sqlalchemy import text
from passlib.context import CryptContext
from jose import jwt
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

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
def google_login(id_token: str, db: Session = Depends(get_db_session)):
    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        email = decoded_token["email"]
        name = decoded_token.get("name", "")
        firebase_uid = decoded_token["uid"]
    except Exception:
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
