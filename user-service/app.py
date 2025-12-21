import os
import uvicorn
import hashlib
import hmac
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jose import jwt, JWTError
from dotenv import load_dotenv

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ===== ENV =====
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# ===== DATABASE =====
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

# ===== SEED ADMIN =====
def seed_admin():
    db = SessionLocal()
    try:
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")

        if not admin_email or not admin_password:
            print("Admin ENV tidak lengkap")
            return

        admin = db.query(User).filter(User.email == admin_email).first()
        if admin:
            print("Admin sudah ada")
            return

        admin = User(
            username=os.getenv("ADMIN_USERNAME", "admin"),
            fullname=os.getenv("ADMIN_FULLNAME", "Admin"),
            email=admin_email,
            password=hash_password(admin_password),
            role="Admin"
        )
        db.add(admin)
        db.commit()
        print("Admin berhasil dibuat")
    finally:
        db.close()

# ===== APP =====
app = FastAPI(title="User Service")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_admin()


# ===== DB DEP =====
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===== PASSWORD =====
def validate_password(password: str):
    if len(password) < 8 or len(password) > 64:
        raise HTTPException(
            status_code=400,
            detail="Password harus 8 sampai 64 karakter"
        )

def hash_password(password: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(),
        password.encode(),
        hashlib.sha256
    ).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed)

# ==== EMAIL =====
def validate_email(email: str):
    if "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="Email tidak valid"
        )
    if email.startswith("@") or email.endswith("@"):
        raise HTTPException(
            status_code=400,
            detail="Email tidak valid"
        )


# ===== JWT =====
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(roles: list):
    def checker(token: str = Depends(oauth2_scheme)):
        payload = decode_token(token)
        if payload.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return payload
    return checker

# ===== REST =====
@app.post("/auth/register")
def register(
    username: str,
    fullname: str,
    email: str,
    password: str,
    db: Session = Depends(get_db)
):
    validate_email(email)
    validate_password(password)

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email sudah ada")

    user = User(
        username=username,
        fullname=fullname,
        email=email,
        password=hash_password(password),
        role="Nasabah"
    )
    db.add(user)
    db.commit()

    return {
        "message": "User registered",
        "user_id": user.user_id,
        "username": user.username,
        "fullname": user.fullname,
        "email": user.email,
        "role": user.role
    }


@app.post("/auth/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Error: Password atau email salah")

    token = create_access_token({
        "sub": user.email,
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role
    })

    return {"access_token": token}

@app.get("/nasabah")
def nasabah_area(user=Depends(require_role(["Nasabah", "Admin"]))):
    return {"message": "Akses Nasabah"}

@app.get("/admin")
def admin_area(user=Depends(require_role(["Admin"]))):
    return {"message": "Akses Admin"}

@app.get("/all-users")
def get_all_users(user=Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
    users = db.query(User).all()
    result = []
    for user in users:
        result.append({
            "user_id": user.user_id,
            "username": user.username,
            "fullname": user.fullname,
            "email": user.email,
            "role": user.role
        })
    return result

# ===== GRAPHQL =====
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
def resolve_my_role(_, info, token):
    payload = decode_token(token)
    return payload.get("role")

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

# ===== RUN =====
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
