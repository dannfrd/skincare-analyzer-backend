from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from database.db_connection import get_db_session
from sqlalchemy import select
from passlib.context import CryptContext
from jose import jwt
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
    name: str | None
    email: EmailStr
    role: str | None
    provider: str | None
    firebase_uid: str | None

    class Config:
         from_attributes = True

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    # Batas maksimal bcrypt adalah 72 karakter
    password = password[:72]
    return pwd_context.hash(password)

def create_access_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db_session)):
    from sqlalchemy import text
    result = db.execute(
        text("SELECT * FROM users WHERE email = :email LIMIT 1"),
        {"email": payload.email}
    )
    user = result.fetchone()
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    # Konversi row ke dict agar bisa dipakai UserOut
    user_dict = dict(user._mapping)
    token = create_access_token({"sub": user_dict["email"], "id": user_dict["id"]})
    return {"token": token, "user": UserOut(**user_dict)}

@router.post("/register", status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db_session)):
    from sqlalchemy import text
    # Cek email sudah terdaftar
    result = db.execute(
        text("SELECT id FROM users WHERE email = :email LIMIT 1"),
        {"email": payload.email}
    )
    user_exist = result.scalar()
    if user_exist:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    print(f"[DEBUG] Password: {repr(payload.password)}, Length: {len(payload.password)}")
    if len(payload.password) > 72:
        raise HTTPException(status_code=400, detail="Password terlalu panjang (maksimal 72 karakter)")
    hashed_pw = get_password_hash(payload.password)
    insert_result = db.execute(
        text("""
            INSERT INTO users (name, email, password, role, provider, created_at)
            VALUES (:name, :email, :password, :role, :provider, NOW())
        """),
        {
            "name": payload.name,
            "email": payload.email,
            "password": hashed_pw,
            "role": "user",
            "provider": payload.provider
        }
    )
    db.commit()
    user_id = insert_result.lastrowid
    user = db.execute(
        text("SELECT * FROM users WHERE id = :id"),
        {"id": user_id}
    ).fetchone()
    user_dict = dict(user._mapping)
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

    from sqlalchemy import text
    result = db.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email}
    )
    user = result.fetchone()
    if not user:
        insert_result = db.execute(
            text("""
                INSERT INTO users (name, email, password, role, provider, firebase_uid, created_at)
                VALUES (:name, :email, '', 'user', 'google', :firebase_uid, NOW())
            """),
            {
                "name": name,
                "email": email,
                "firebase_uid": firebase_uid
            }
        )
        db.commit()
        user_id = insert_result.lastrowid
        user = db.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_id}
        ).fetchone()
    user_dict = dict(user._mapping)
    token = create_access_token({"sub": user_dict["email"], "id": user_dict["id"]})
    return {"token": token, "user": UserOut(**user_dict)}
