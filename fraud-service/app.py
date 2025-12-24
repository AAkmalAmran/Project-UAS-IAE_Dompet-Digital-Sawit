import os
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Enum, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jose import jwt, JWTError

# Import Ariadne untuk GraphQL
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ================= KONFIGURASI =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fraud.db")
ALGORITHM = os.getenv("ALGORITHM", "RS256")
PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", "public.pem")

try:
    with open(PUBLIC_KEY_PATH, "r") as f:
        PUBLIC_KEY = f.read()
except Exception:
    PUBLIC_KEY = ""

# ================= DATABASE =================
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FraudStatus(str, PyEnum):
    SAFE = "SAFE"
    FRAUD = "FRAUD"
    SUSPICIOUS = "SUSPICIOUS"

class FraudLog(Base):
    __tablename__ = "fraud_logs"
    log_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    amount = Column(Float)
    ip_address = Column(String, nullable=True)
    status = Column(Enum(FraudStatus), default=FraudStatus.SAFE)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ================= REST SCHEMAS (Untuk Internal Call) =================
class FraudCheckRequest(BaseModel):
    user_id: str
    amount: float
    ip_address: Optional[str] = None

# ================= GRAPHQL SCHEMA & RESOLVERS =================

type_defs = """
    type FraudLog {
        log_id: String!
        user_id: String!
        amount: Float!
        ip_address: String
        status: String!
        reason: String
        created_at: String!
    }

    type Query {
        getFraudLog(log_id: String!): FraudLog
        listFraudLogs: [FraudLog!]!
    }

    input FraudCheckInput {
        user_id: String!
        amount: Float!
        ip_address: String
    }

    input UpdateFraudInput {
        log_id: String!
        status: String!
        reason: String
    }

    type Mutation {
        checkFraud(input: FraudCheckInput!): FraudLog
        updateFraudLog(input: UpdateFraudInput!): FraudLog
        deleteFraudLog(log_id: String!): String
    }
"""

query = QueryType()
mutation = MutationType()

# --- Helper Auth untuk GraphQL ---
def check_auth(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise Exception("Authorization header required")
    token = auth_header.replace("Bearer ", "")
    try:
        jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise Exception("Invalid or expired token")

# --- RESOLVERS ---

@query.field("listFraudLogs")
def resolve_list_logs(_, info):
    # check_auth(info.context["request"]) # Uncomment jika ingin proteksi list
    db: Session = next(get_db())
    return db.query(FraudLog).order_by(FraudLog.created_at.desc()).all()

@query.field("getFraudLog")
def resolve_get_log(_, info, log_id):
    db: Session = next(get_db())
    log = db.query(FraudLog).filter(FraudLog.log_id == log_id).first()
    if not log: raise Exception("Log not found")
    return log

@mutation.field("checkFraud")
def resolve_check_fraud(_, info, input):
    # Logic Deteksi Fraud (Sama seperti REST)
    amount = input["amount"]
    status_res = FraudStatus.SAFE
    reason = "Transaction looks safe"

    if amount > 50000000:
        status_res = FraudStatus.FRAUD
        reason = "Amount exceeds maximum limit (50jt)"
    elif amount > 10000000:
        status_res = FraudStatus.SUSPICIOUS
        reason = "Large transaction amount (>10jt)"
    
    db: Session = next(get_db())
    new_log = FraudLog(
        user_id=input["user_id"],
        amount=amount,
        ip_address=input.get("ip_address"),
        status=status_res,
        reason=reason
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return new_log

@mutation.field("updateFraudLog")
def resolve_update_log(_, info, input):
    check_auth(info.context["request"]) # Butuh Token Admin
    
    db: Session = next(get_db())
    log = db.query(FraudLog).filter(FraudLog.log_id == input["log_id"]).first()
    if not log: raise Exception("Log not found")
    
    # Update Status
    try:
        log.status = FraudStatus(input["status"])
    except ValueError:
        raise Exception("Invalid status. Use: SAFE, FRAUD, SUSPICIOUS")
        
    if input.get("reason"):
        log.reason = input["reason"]
        
    db.commit()
    db.refresh(log)
    return log

@mutation.field("deleteFraudLog")
def resolve_delete_log(_, info, log_id):
    check_auth(info.context["request"]) # Butuh Token Admin
    
    db: Session = next(get_db())
    log = db.query(FraudLog).filter(FraudLog.log_id == log_id).first()
    if not log: raise Exception("Log not found")
    
    db.delete(log)
    db.commit()
    return "Log deleted successfully"

schema = make_executable_schema(type_defs, query, mutation)

# ================= APP SETUP =================
app = FastAPI(title="Fraud Service - GraphQL & REST")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. MOUNT GRAPHQL (Untuk CRUD Tugas Besar)
app.add_route("/graphql", GraphQL(schema, debug=True))

# 2. REST ENDPOINT (Agar Transaction Service Tetap Jalan)
@app.post("/check")
def check_fraud_rest(req: FraudCheckRequest, db: Session = Depends(get_db)):
    # Logic yang sama persis
    status_res = FraudStatus.SAFE
    reason = "Transaction looks safe"
    is_fraud = False

    if req.amount > 50000000:
        status_res = FraudStatus.FRAUD
        reason = "Amount exceeds maximum limit (50jt)"
        is_fraud = True
    elif req.amount > 10000000:
        status_res = FraudStatus.SUSPICIOUS
        reason = "Large transaction amount (>10jt)"

    new_log = FraudLog(
        user_id=req.user_id,
        amount=req.amount,
        ip_address=req.ip_address,
        status=status_res,
        reason=reason
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return {
        "is_fraud": is_fraud,
        "status": status_res,
        "reason": reason,
        "log_id": new_log.log_id
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004, reload=True)