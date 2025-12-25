import os
import uvicorn
import httpx
import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from jose import jwt, JWTError
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ================= KONFIGURASI ENV =================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ALGORITHM = os.getenv("ALGORITHM", "RS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
SECRET_KEY = os.getenv("SECRET_KEY", "rahasia-negara")

# Konfigurasi Admin Default (Dari .env atau Fallback)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin12345")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

# Load Keys
try:
    with open(BASE_DIR / "private.pem") as f:
        PRIVATE_KEY = f.read()
    with open(BASE_DIR / "public.pem") as f:
        PUBLIC_KEY = f.read()
except FileNotFoundError:
    print("WARNING: Keys not found. Generate keys first!")
    PRIVATE_KEY = "secret"
    PUBLIC_KEY = "secret"

# ================= DATABASE =================
DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    fullname = Column(String)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="Nasabah")

# ================= HELPER AUTH & SEEDING =================
def hash_password(password: str) -> str:
    return hmac.new(SECRET_KEY.encode(), password.encode(), hashlib.sha256).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed)

def create_access_token(data: dict):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, PRIVATE_KEY, algorithm=ALGORITHM)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- FUNGSI PENTING: MEMBUAT ADMIN OTOMATIS ---
def seed_admin():
    db = SessionLocal()
    try:
        # Cek apakah admin sudah ada berdasarkan email
        if db.query(User).filter(User.email == ADMIN_EMAIL).first():
            print(f"Admin ({ADMIN_EMAIL}) sudah ada. Skip seeding.")
            return

        print(f"Membuat user Admin baru ({ADMIN_EMAIL})...")
        admin = User(
            username=ADMIN_USERNAME,
            fullname="System Administrator",
            email=ADMIN_EMAIL,
            password=hash_password(ADMIN_PASSWORD),
            role="Admin"  # Role harus 'Admin' (Case sensitive sesuai logika service lain)
        )
        db.add(admin)
        db.commit()
        print("Admin berhasil dibuat!")
    except Exception as e:
        print(f"Gagal membuat admin: {e}")
    finally:
        db.close()

# ================= REST API (CORE LOGIC) =================
app = FastAPI(title="User Service - Hybrid")

class RegisterRequest(BaseModel):
    username: str
    fullname: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@app.post("/rest/auth/register", tags=["REST"])
def register_rest(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    
    user = User(
        username=data.username,
        fullname=data.fullname,
        email=data.email,
        password=hash_password(data.password),
        role="Nasabah"
    )
    db.add(user)
    db.commit()
    return {"message": "Success", "user_id": user.user_id}

@app.post("/rest/auth/login", tags=["REST"])
def login_rest(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="Email atau Password Salah")
    
    token = create_access_token({
        "sub": user.email,
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"user_id": user.user_id, "username": user.username, "email": user.email, "role": user.role}
    }

@app.get("/rest/users/me", tags=["REST"])
def get_me_rest(token: str):
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid Token")

# ================= GRAPHQL (WRAPPER) =================
type_defs = """
    type UserProfile {
        user_id: ID
        username: String
        email: String
        role: String
    }

    type LoginResponse {
        access_token: String
        token_type: String
        user: UserProfile
    }

    type Query {
        myProfile(token: String!): UserProfile
    }

    type Mutation {
        registerUser(username: String!, fullname: String!, email: String!, password: String!): String
        loginUser(email: String!, password: String!): LoginResponse
    }
"""

query = QueryType()
mutation = MutationType()

# URL Localhost container ini sendiri
LOCAL_URL = "http://localhost:8001"

@mutation.field("registerUser")
async def resolve_register(_, info, username, fullname, email, password):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{LOCAL_URL}/rest/auth/register", json={
            "username": username, "fullname": fullname, "email": email, "password": password
        })
        if resp.status_code != 200:
            raise Exception(resp.json().get("detail", "Error Register"))
        return "Registrasi Berhasil"

@mutation.field("loginUser")
async def resolve_login(_, info, email, password):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{LOCAL_URL}/rest/auth/login", json={
            "email": email, "password": password
        })
        if resp.status_code != 200:
            raise Exception(resp.json().get("detail", "Error Login"))
        return resp.json()

@query.field("myProfile")
async def resolve_profile(_, info, token):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{LOCAL_URL}/rest/users/me", params={"token": token})
        if resp.status_code != 200: return None
        data = resp.json()
        return {
            "user_id": data.get("user_id"),
            "username": data.get("username"),
            "email": data.get("sub"),
            "role": data.get("role")
        }

schema = make_executable_schema(type_defs, query, mutation)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_admin() 

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)