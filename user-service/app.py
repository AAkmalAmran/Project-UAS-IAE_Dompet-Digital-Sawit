import os
import uvicorn
import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from jose import jwt, JWTError
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ================= ENV =================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ALGORITHM = os.getenv("ALGORITHM", "RS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

SECRET_KEY = os.getenv("SECRET_KEY", "password-secret")

with open(BASE_DIR / "private.pem") as f:
    PRIVATE_KEY = f.read()

with open(BASE_DIR / "public.pem") as f:
    PUBLIC_KEY = f.read()

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RegisterRequest(BaseModel):
    username: str
    fullname: str
    email: EmailStr
    password: str

# ================= DATABASE =================
DATABASE_URL = "sqlite:///./users.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    fullname = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="Nasabah")

# ================= PASSWORD =================
def validate_password(password: str):
    if len(password) < 8 or len(password) > 64:
        raise HTTPException(status_code=400, detail="Password 8–64 karakter")

def hash_password(password: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(),
        password.encode(),
        hashlib.sha256
    ).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed)

def validate_email(email: str):
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Email tidak valid")

# ================= JWT =================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(data: dict):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")

def decode_token(token: str):
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(roles: list):
    def checker(token: str = Depends(oauth2_scheme)):
        payload = decode_token(token)
        if payload.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return payload
    return checker

# ================= SEED ADMIN =================
def seed_admin():
    print("Running admin seed...")
    db = SessionLocal()
    try:
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")

        if not email or not password:
            print("Admin ENV tidak lengkap")
            return

        if db.query(User).filter(User.email == email).first():
            print("Admin already exists")
            return

        admin = User(
            username=os.getenv("ADMIN_USERNAME", "admin"),
            fullname=os.getenv("ADMIN_FULLNAME", "Admin"),
            email=email,
            password=hash_password(password),
            role="Admin"
        )
        db.add(admin)
        db.commit()
        print("Admin seeded successfully")
    finally:
        db.close()

# ================= APP =================
app = FastAPI(title="User Service")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_admin()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================= REST =================
@app.post("/auth/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    validate_email(data.email)
    validate_password(data.password)

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
    return {"message": "User berhasil dibuat", "user_id": user.user_id, "email": user.email}

@app.post("/auth/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Email salah")

    if not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="password salah")

    token = create_access_token({
        "sub": user.email,
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role
    })

    return {
        "access_token": token,
        "token_type": "bearer"
    }


@app.get("/admin")
def admin_area(user=Depends(require_role(["Admin"]))):
    return {"message": "Admin OK"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "user-service", "timestamp": datetime.utcnow().isoformat()}

# ================= GRAPHQL =================
type_defs = """
    type Query {
        myRole(token: String!): String!
    }

    type Mutation {
        registerUser(
            username: String!
            fullname: String!
            email: String!
            password: String!
        ): String!

        loginUser(
            email: String!, 
            password: String!
        ): String!
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("myRole")
def my_role(_, info, token):
    return decode_token(token)["role"]

@mutation.field("registerUser")
def resolve_register(_, info, username, fullname, email, password):
    validate_email(email)
    validate_password(password)

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            return "Email sudah terdaftar"

        user = User(
            username=username,
            fullname=fullname,
            email=email,
            password=hash_password(password),
            role="Nasabah"
        )
        db.add(user)
        db.commit()
        return "User registered"
    finally:
        db.close()

@mutation.field("loginUser")
def resolve_login(_, info, email, password):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password):
            return "Error: Password atau email salah"

        token = create_access_token({
            "sub": user.username,
            "user_id": user.user_id,
            "username": user.username,
            "role": user.role
        })
        return token
    finally:
        db.close()



schema = make_executable_schema(type_defs, query, mutation)
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
