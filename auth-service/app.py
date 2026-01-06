import os
import uvicorn
import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from jose import jwt, JWTError
from dotenv import load_dotenv
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/users.db")
ALGORITHM = os.getenv("ALGORITHM", "RS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
SECRET_KEY = os.getenv("SECRET_KEY", "ini-sangat-berbahaya-loh-dattebayo")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin12345")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

try:
    with open(BASE_DIR / "private.pem") as f: PRIVATE_KEY = f.read()
    with open(BASE_DIR / "public.pem") as f: PUBLIC_KEY = f.read()
except:
    PRIVATE_KEY = "secret"; PUBLIC_KEY = "secret"

# --- DB ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    fullname = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String, default="Nasabah")

# --- HELPER ---
def hash_password(p): return hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
def verify_password(p, h): return hmac.compare_digest(hash_password(p), h)
def create_token(data):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)})
    return jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)

def seed_admin():
    db = SessionLocal()
    if not db.query(User).filter(User.email == ADMIN_EMAIL).first():
        db.add(User(username=ADMIN_USERNAME, fullname="Admin", email=ADMIN_EMAIL, password=hash_password(ADMIN_PASSWORD), role="Admin"))
        db.commit()
    db.close()

# --- GRAPHQL ---
type_defs = """
    type User {
        user_id: ID
        username: String
        fullname: String
        email: String
        role: String
    }
    type LoginResponse {
        access_token: String
        token_type: String
        user: User
    }
    type Query {
        myProfile(token: String!): User
    }
    type Mutation {
        registerUser(username: String!, fullname: String!, email: String!, password: String!): String
        loginUser(email: String!, password: String!): LoginResponse
    }
"""

query = QueryType()
mutation = MutationType()

@mutation.field("registerUser")
def resolve_register(_, info, username, fullname, email, password):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            raise Exception("Email already registered")
        user = User(username=username, fullname=fullname, email=email, password=hash_password(password))
        db.add(user)
        db.commit()
        return "Registrasi Berhasil"
    finally:
        db.close()

@mutation.field("loginUser")
def resolve_login(_, info, email, password):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password):
            raise Exception("Invalid Credentials")
        
        token = create_token({"sub": user.email, "user_id": user.user_id, "username": user.username, "role": user.role})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user
        }
    finally:
        db.close()

@query.field("myProfile")
def resolve_profile(_, info, token):
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return {
            "user_id": payload["user_id"],
            "username": payload["username"],
            "email": payload["sub"],
            "role": payload["role"],
            "fullname": "User" 
        }
    except JWTError:
        raise Exception("Invalid Token")

schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="Auth Service GraphQL")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_admin()

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)