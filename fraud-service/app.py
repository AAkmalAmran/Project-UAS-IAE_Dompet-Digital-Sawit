import os
import uuid
import uvicorn
import httpx
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy import create_engine, Column, String, Float, DateTime, Enum
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from jose import jwt, JWTError

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fraud.db")

# --- AUTH SETUP ---
ALGORITHM = "RS256"
PUBLIC_KEY_PATH = "/app/public.pem" # Pastikan file ini ada via Docker Volume

try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

def verify_token(authorization: str = Header(...)):
    """Cek apakah token valid (Role apa saja boleh)"""
    if not authorization.startswith("Bearer "): raise HTTPException(401, "Invalid Header")
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Token Invalid/Expired")

def verify_admin(payload: dict = Depends(verify_token)):
    """Cek apakah User adalah Admin"""
    # Pastikan di User Service role-nya 'Admin' (huruf besar A)
    if payload.get("role") != "Admin":
        raise HTTPException(403, "Access Denied: Admin only")
    return payload

# --- DATABASE ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
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
    status = Column(Enum(FraudStatus), default=FraudStatus.SAFE)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

app = FastAPI(title="Fraud Service (Strict)")

# ================= REST API =================
class CheckFraudRequest(BaseModel):
    user_id: str
    amount: float

@app.post("/rest/check", tags=["REST"])
def check_fraud_rest(req: CheckFraudRequest, user=Depends(verify_token), db: Session = Depends(get_db)):
    """
    Endpoint ini bisa diakses User biasa (via Transaction Service),
    karena User perlu dicek transaksinya.
    """
    amount = req.amount
    status_res = FraudStatus.SAFE
    reason = "Transaksi Aman"
    is_fraud = False

    # Logika Deteksi Sederhana
    if amount > 50000000:
        status_res = FraudStatus.FRAUD
        reason = "Nominal melebihi batas 50jt"
        is_fraud = True
    elif amount > 10000000:
        status_res = FraudStatus.SUSPICIOUS
        reason = "Transaksi besar (>10jt)"

    new_log = FraudLog(
        user_id=req.user_id,
        amount=amount,
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

@app.get("/rest/logs", tags=["REST"])
def get_logs_rest(user=Depends(verify_admin), db: Session = Depends(get_db)):
    """
    Hanya ADMIN yang boleh melihat seluruh log fraud.
    """
    return db.query(FraudLog).all()

# ================= GRAPHQL WRAPPER =================
type_defs = """
    type FraudLog {
        logId: String
        userId: String
        amount: Float
        status: String
        reason: String
    }
    
    type FraudCheckResult {
        is_fraud: Boolean
        status: String
        reason: String
        log_id: String
    }

    input CheckFraudInput {
        userId: String!
        amount: Float!
    }

    type Query {
        getFraudLogs: [FraudLog]
    }

    type Mutation {
        checkFraud(input: CheckFraudInput!): FraudCheckResult
    }
"""

query = QueryType()
mutation = MutationType()
LOCAL_URL = "http://localhost:8004"

@query.field("getFraudLogs")
async def resolve_logs(_, info):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")
    
    async with httpx.AsyncClient() as client:
        # Panggil endpoint REST Logs (Admin Only)
        resp = await client.get(
            f"{LOCAL_URL}/rest/logs",
            headers={"Authorization": auth_header}
        )
        
        if resp.status_code == 403:
            raise Exception("Access Denied: Anda bukan Admin")
        if resp.status_code != 200:
            raise Exception("Error fetching logs")
            
        data = resp.json()
        return [
            {
                "logId": d["log_id"], "userId": d["user_id"], 
                "amount": d["amount"], "status": d["status"], "reason": d["reason"]
            } for d in data
        ]

@mutation.field("checkFraud")
async def resolve_check(_, info, input):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LOCAL_URL}/rest/check", 
            json={"user_id": input["userId"], "amount": input["amount"]},
            headers={"Authorization": auth_header}
        )
        if resp.status_code != 200:
            raise Exception("Error checking fraud")
            
        return resp.json()

schema = make_executable_schema(type_defs, query, mutation)

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8004)