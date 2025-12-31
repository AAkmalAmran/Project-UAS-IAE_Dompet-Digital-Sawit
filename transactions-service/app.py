import os
import uuid
import uvicorn
import httpx
import enum
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel, field_validator
from jose import jwt, JWTError
from ariadne import QueryType, MutationType, make_executable_schema, EnumType
from ariadne.asgi import GraphQL

# ================= 1. CONFIGURATION & ENV =================
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transactions.db")

# Service URLs
WALLET_SERVICE_URL = os.getenv("WALLET_SERVICE_URL", "http://wallet-service:8002")
FRAUD_SERVICE_URL = os.getenv("FRAUD_SERVICE_URL", "http://fraud-service:8004")
HISTORY_SERVICE_URL = os.getenv("HISTORY_SERVICE_URL", "http://history-service:8005")
EXTERNAL_ORDER_SERVICE_URL = "http://host.docker.internal:7003/graphql" # BlackDoctrine

# Auth Configuration
ALGORITHM = os.getenv("ALGORITHM", "RS256")
PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", "/app/public.pem")

try:
    with open(PUBLIC_KEY_PATH, "r") as f:
        PUBLIC_KEY = f.read()
except FileNotFoundError:
    print("WARNING: Public Key not found. Auth will fail.")
    PUBLIC_KEY = ""

# ================= 2. ENUMS & MODELS =================
class TransactionTypeEnum(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    PAYMENT = "PAYMENT"
    TRANSFER = "TRANSFER"

# Pydantic Model (Input Validation)
class TransactionReq(BaseModel):
    wallet_id: str
    amount: float
    type: TransactionTypeEnum
    va_number: Optional[str] = None

    # [FITUR BARU] Auto-convert "payment" -> "PAYMENT"
    @field_validator('type', mode='before')
    def case_insensitive_enum(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

# SQLAlchemy Model (Database)
Base = declarative_base()
class Transaction(Base):
    __tablename__ = "transactions"
    transaction_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String)
    wallet_id = Column(String)
    amount = Column(Float)
    type = Column(String) # Disimpan sebagai string di DB
    va_number = Column(String, nullable=True) 
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# ================= 3. DATABASE SETUP =================
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ================= 4. HELPER FUNCTIONS =================
def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Header")
    token = authorization.replace("Bearer ", "")
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Token Invalid atau Expired")

async def call_external_api_group(va_number: str, amount: float):
    """Integrasi ke BlackDoctrine via VA Number"""
    print(f"[INTEGRATION] Connecting to BlackDoctrine via VA: {va_number}")
    async with httpx.AsyncClient() as client:
        try:
            # Step 1: Validasi Tagihan
            query_check = """
                query($va: String!) {
                    getOrderByVA(vaNumber: $va) { nomorVA totalHarga status }
                }
            """
            res_check = await client.post(
                EXTERNAL_ORDER_SERVICE_URL, 
                json={"query": query_check, "variables": {"va": va_number}}
            )
            
            if res_check.status_code != 200: 
                raise Exception(f"Connection Error: {res_check.status_code}")
            
            data = res_check.json().get("data", {}).get("getOrderByVA")
            if not data: 
                return {"success": False, "message": f"VA {va_number} tidak ditemukan!"}
            
            if float(data["totalHarga"]) != float(amount): 
                return {
                    "success": False, 
                    "message": f"Nominal mismatch! Tagihan: {data['totalHarga']}, Input: {amount}"
                }
            
            # Step 2: Konfirmasi Pembayaran
            mutation_pay = """
                mutation($va: String!, $status: String!) {
                    updatePaymentStatus(vaNumber: $va, status: $status)
                }
            """
            res_pay = await client.post(
                EXTERNAL_ORDER_SERVICE_URL,
                json={"query": mutation_pay, "variables": {"va": va_number, "status": "PROCESSED"}}
            )
            
            if res_pay.status_code == 200 and res_pay.json().get("data", {}).get("updatePaymentStatus"):
                return {"success": True, "message": "Verified by Marketplace"}
            
            return {"success": False, "message": "Failed to update status in Marketplace"}

        except Exception as e:
            print(f"Integration Error: {e}")
            return {"success": False, "message": f"Marketplace Error: {str(e)}"}

# ================= 5. REST API ENDPOINTS =================
app = FastAPI(title="Transaction Service")

@app.post("/rest/transactions", tags=["REST"])
async def create_transaction_rest(
    req: TransactionReq, 
    authorization: str = Header(...),
    user=Depends(verify_token),
    db: Session = Depends(get_db)
):
    user_id = str(user["user_id"])
    forward_headers = {"Authorization": authorization}

    # A. Cek Integrasi (Hanya tipe PAYMENT)
    if req.type == TransactionTypeEnum.PAYMENT:
        if not req.va_number:
            raise HTTPException(400, "VA Number wajib diisi untuk PAYMENT")
        
        integ_res = await call_external_api_group(req.va_number, req.amount)
        if not integ_res["success"]:
            raise HTTPException(400, f"Integrasi Gagal: {integ_res['message']}")

    # B. Cek Fraud
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{FRAUD_SERVICE_URL}/rest/check",
                json={"user_id": user_id, "amount": req.amount},
                headers=forward_headers
            )
            if res.status_code == 200 and res.json().get("is_fraud"):
                 raise HTTPException(400, f"Fraud Detected: {res.json().get('reason')}")
    except httpx.RequestError:
        pass 

    # C. Update Wallet (Deduct / Topup)
    endpoint = "/internal/topup" if req.type == TransactionTypeEnum.DEPOSIT else "/internal/deduct"
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{WALLET_SERVICE_URL}{endpoint}",
            json={"wallet_id": req.wallet_id, "amount": req.amount},
            headers=forward_headers
        )
        if res.status_code != 200:
            raise HTTPException(400, res.json().get("detail", "Gagal Update Saldo"))

    # D. Simpan Transaksi
    trx = Transaction(
        user_id=user_id,
        wallet_id=req.wallet_id,
        amount=req.amount,
        type=req.type.value,
        va_number=req.va_number,
        status="SUCCESS"
    )
    db.add(trx)
    db.commit()
    db.refresh(trx)

    # E. Log History (Async)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{HISTORY_SERVICE_URL}/rest/history",
                json={
                    "transaction_id": trx.transaction_id,
                    "user_id": user_id,
                    "amount": trx.amount,
                    "type": trx.type,
                    "status": "SUCCESS"
                },
                headers=forward_headers
            )
    except: pass

    return trx

@app.get("/rest/transactions/me", tags=["REST"])
def get_my_trx(user=Depends(verify_token), db: Session = Depends(get_db)):
    return db.query(Transaction).filter(Transaction.user_id == str(user["user_id"])).all()

# ================= 6. GRAPHQL CONFIGURATION =================
type_defs = """
    enum TransactionType {
        DEPOSIT
        PAYMENT
        TRANSFER
    }

    type Transaction {
        transactionId: String
        userId: String
        walletId: String
        amount: Float
        type: TransactionType
        vaNumber: String
        status: String
        createdAt: String
    }

    input TransactionInput {
        walletId: String!
        amount: Float!
        type: TransactionType!
        vaNumber: String
    }

    type Query { myTransactions: [Transaction] }
    type Mutation { createTransaction(input: TransactionInput!): Transaction }
"""

# Mapping Enum Python -> GraphQL
transaction_type_enum = EnumType("TransactionType", TransactionTypeEnum)

query = QueryType()
mutation = MutationType()
LOCAL_URL = "http://localhost:8003"

@query.field("myTransactions")
async def resolve_list(_, info):
    request = info.context["request"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{LOCAL_URL}/rest/transactions/me",
            headers={"Authorization": request.headers.get("Authorization")}
        )
        if resp.status_code != 200: return []
        
        return [
            {
                "transactionId": t["transaction_id"],
                "userId": t["user_id"],
                "walletId": t["wallet_id"],
                "amount": t["amount"],
                "type": t["type"],
                "status": t["status"],
                "vaNumber": t.get("va_number"),
                "createdAt": t["created_at"]
            } for t in resp.json()
        ]

@mutation.field("createTransaction")
async def resolve_create(_, info, input):
    request = info.context["request"]
    
    # Payload ke REST API
    payload = {
        "wallet_id": input["walletId"],
        "amount": input["amount"],
        "type": input["type"],
        "va_number": input.get("vaNumber")
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LOCAL_URL}/rest/transactions",
            json=payload,
            headers={"Authorization": request.headers.get("Authorization")}
        )
        
        if resp.status_code != 200:
            raise Exception(resp.json().get("detail", "Transaction Failed"))
        
        t = resp.json()
        return {
            "transactionId": t["transaction_id"],
            "userId": t["user_id"],
            "walletId": t["wallet_id"],
            "amount": t["amount"],
            "type": t["type"],
            "status": t["status"],
            "vaNumber": t.get("va_number"),
            "createdAt": t["created_at"]
        }

# Schema Creation
schema = make_executable_schema(type_defs, query, mutation, transaction_type_enum)

@app.on_event("startup")
def startup(): 
    Base.metadata.create_all(bind=engine)

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)