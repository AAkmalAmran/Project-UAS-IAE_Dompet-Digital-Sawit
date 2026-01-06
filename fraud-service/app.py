import os
import uuid
import uvicorn
from datetime import datetime
from enum import Enum as PyEnum
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine, Column, String, Float, DateTime, Enum
from sqlalchemy.orm import sessionmaker, declarative_base
from jose import jwt
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/fraud.db")
PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", "/app/public.pem")
try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

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
    user_id = Column(String)
    amount = Column(Float)
    status = Column(Enum(FraudStatus), default=FraudStatus.SAFE)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_current_user(request):
    auth = request.headers.get("Authorization", "")
    if not auth:
        raise Exception("Missing Authorization Header")
    
    # Handle case "Bearer <token>" lebih rapi
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
    else:
        # Fallback jika user mengirim token mentah tanpa 'Bearer'
        token = auth
        
    if not token:
        raise Exception("Token is empty")

    try:
        # Pastikan PUBLIC_KEY tidak kosong
        if not PUBLIC_KEY:
             raise Exception("Server Error: Public Key not loaded")
             
        return jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    except Exception as e:
        print(f"Token Decode Error: {e}") # Debugging di log console
        raise Exception("Unauthorized: Invalid Token")

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
    }
    type Query {
        getFraudLogs: [FraudLog]
    }
    type Mutation {
        checkFraud(userId: String!, amount: Float!): FraudCheckResult
        deleteFraudLog(logId: String!): String
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("getFraudLogs")
def resolve_logs(_, info):
    request = info.context["request"]
    user = get_current_user(request)
    if user.get("role") != "Admin": raise Exception("Admin Only")
    
    db = SessionLocal()
    try:
        logs = db.query(FraudLog).all()
        return [{"logId": l.log_id, "userId": l.user_id, "amount": l.amount, "status": l.status, "reason": l.reason} for l in logs]
    finally:
        db.close()

@mutation.field("checkFraud")
def resolve_check(_, info, userId, amount):
    # Logika Deteksi
    status_res = FraudStatus.SAFE
    reason = "Aman"
    is_fraud = False

    if amount > 50000000:
        status_res = FraudStatus.FRAUD; reason = "Limit > 50jt"; is_fraud = True
    elif amount > 10000000:
        status_res = FraudStatus.SUSPICIOUS; reason = "Transaksi Besar > 10jt"

    db = SessionLocal()
    try:
        log = FraudLog(user_id=userId, amount=amount, status=status_res, reason=reason)
        db.add(log)
        db.commit()
        return {"is_fraud": is_fraud, "status": status_res, "reason": reason}
    finally:
        db.close()

@mutation.field("deleteFraudLog")
def resolve_delete(_, info, logId):
    request = info.context["request"]
    user = get_current_user(request)
    if user.get("role") != "Admin": raise Exception("Admin Only")
    
    db = SessionLocal()
    try:
        db.query(FraudLog).filter(FraudLog.log_id == logId).delete()
        db.commit()
        return "Deleted"
    finally:
        db.close()

schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="Fraud Service GraphQL")

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8004)