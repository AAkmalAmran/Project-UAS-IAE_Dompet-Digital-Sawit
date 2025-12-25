import os
import uuid
import asyncio
from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Column, String, Float, Integer, DateTime, 
    ForeignKey, Enum, Index, Text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from jose import jwt, JWTError
import httpx 

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ================= ENV =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

ALGORITHM = os.getenv("ALGORITHM", "RS256")
PUBLIC_KEY = os.getenv("PUBLIC_KEY", "public.pem")

try:
    with open(PUBLIC_KEY, "r") as f:
        PUBLIC_KEY_CONTENT = f.read()
except Exception:
    PUBLIC_KEY_CONTENT = ""

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transactions.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# URL Microservices
WALLET_SERVICE_URL = os.getenv("WALLET_SERVICE_URL", "http://wallet-service:8002")
FRAUD_SERVICE_URL = os.getenv("FRAUD_SERVICE_URL", "http://fraud-service:8004")
HISTORY_SERVICE_URL = os.getenv("HISTORY_SERVICE_URL", "http://history-service:8005")

# ================= Models =================
# [FIX] Tambahkan 'str' agar Enum diperlakukan sebagai string juga oleh SQLAlchemy
class TransactionType(str, PyEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PAYMENT = "payment"
    REFUND = "refund"

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    wallet_id = Column(String, index=True)
    wallet_name = Column(String, nullable=True)
    
    # SQLAlchemy akan otomatis menggunakan value ("deposit", dll) karena class inherit 'str'
    transaction_type = Column(Enum(TransactionType)) 
    
    order_id = Column(String, index=True)
    amount = Column(Float)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="completed")

    __table_args__ = (
        Index('idx_user_order', 'user_id', 'order_id'),
    )

Base.metadata.create_all(bind=engine)

# ================= HELPER FUNCTIONS =================

async def verify_wallet(user_id: str, wallet_id: str) -> bool:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallets/user/{user_id}")
            if response.status_code == 200:
                wallets = response.json()
                return any(wallet["wallet_id"] == wallet_id for wallet in wallets)
        except Exception:
            return False
    return False
        
async def get_wallet_name(wallet_id: str) -> str:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallet/{wallet_id}")
            if response.status_code == 200:
                wallet = response.json()
                return wallet.get("wallet_name", "")
        except: pass
    return "Unknown"

async def update_wallet_balance(wallet_id: str, amount: float, transaction_type: str):
    async with httpx.AsyncClient() as client:
        # Tentukan endpoint berdasarkan jenis transaksi
        if transaction_type == "deposit":
            url = f"{WALLET_SERVICE_URL}/internal/topup"
        else:
            url = f"{WALLET_SERVICE_URL}/internal/deduct-balance"

        payload = {"wallet_id": wallet_id, "amount": amount}
        response = await client.post(url, json=payload)
        
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Wallet update failed")
            raise HTTPException(status_code=400, detail=error_detail)

async def check_fraud_status(user_id: str, amount: float):
    async with httpx.AsyncClient() as client:
        try:
            payload = {"user_id": str(user_id), "amount": amount}
            res = await client.post(f"{FRAUD_SERVICE_URL}/check", json=payload)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            print(f"Fraud check error: {e}")
    return {"is_fraud": False, "reason": "Service unreachable"}

async def log_transaction_history(transaction_data: dict):
    try:
        print(f"Sending request to history-service: {transaction_data}")  # Tambah logging untuk debug
        response = httpx.post(
            f"{HISTORY_SERVICE_URL}/internal/history/transaction",
            json=transaction_data,
            timeout=10.0
        )
        response.raise_for_status()
        print(f"History log success: {response.status_code}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error logging to history: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        print(f"Error logging to history: {str(e)}")
        raise

async def call_external_api_group(order_id: str, amount: float):
    print(f"📡 [MOCK] Calling External API... Order: {order_id}, Amount: {amount}")
    return {"success": True, "message": "External system accepted transaction"}


# ================= Pydantic Schemas =================
class TransactionCreate(BaseModel):
    wallet_id: str
    transaction_type: TransactionType
    order_id: str
    amount: float
    description: Optional[str] = None

class TransactionResponse(BaseModel):
    transaction_id: str
    user_id: str
    wallet_id: str
    wallet_name: str
    transaction_type: str
    order_id: str
    amount: float
    description: Optional[str]
    created_at: datetime
    status: str

class TransactionUpdate(BaseModel):
    transaction_type: TransactionType

# ================= Auth =================
class JWTBearer(HTTPBearer):
    async def __call__(self, request: Request):
        credentials = await super().__call__(request)
        if credentials:
            try:
                payload = jwt.decode(credentials.credentials, PUBLIC_KEY_CONTENT, algorithms=[ALGORITHM])
                return payload
            except JWTError:
                raise HTTPException(status_code=403, detail="Invalid token")
        raise HTTPException(status_code=403, detail="Invalid auth")

# ================= FastAPI App =================
app = FastAPI(title="Transactions Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ================= GraphQL Schema =================
type_defs = """
    type Transaction {
        transaction_id: String!
        user_id: String!
        wallet_id: String!
        wallet_name: String!
        transaction_type: String!
        order_id: String!
        amount: Float!
        description: String
        created_at: String!
        status: String!
    }

    type Query {
        getTransaction(transaction_id: String!): Transaction
        listTransactions(user_id: String!): [Transaction!]!
    }

    input TransactionInput {
        wallet_id: String! 
        transaction_type: String!
        order_id: String!
        amount: Float!
        description: String
    }

    input UpdateTransactionInput {
        transaction_id: String!
        transaction_type: String!
    }

    type Mutation {
        createTransaction(input: TransactionInput!): Transaction
        updateTransaction(input: UpdateTransactionInput!): Transaction
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("getTransaction")
def resolve_get_transaction(_, info, transaction_id):
    db: Session = next(get_db())
    transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not transaction: raise Exception("Transaction not found")
    return transaction

@query.field("listTransactions")
def resolve_list_transactions(_, info, user_id):
    db: Session = next(get_db())
    return db.query(Transaction).filter(Transaction.user_id == user_id).all()

@mutation.field("createTransaction")
async def resolve_create_transaction(_, info, input):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "): raise Exception("Authorization header required")
    token = auth_header.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, PUBLIC_KEY_CONTENT, algorithms=[ALGORITHM])
    except JWTError: raise Exception("Invalid token")
        
    user_id = str(payload.get("user_id"))
    
    # 1. Verifikasi
    if not await verify_wallet(user_id, input["wallet_id"]):
        raise Exception("Invalid wallet_id for this user")

    # 2. Fraud Check
    fraud_check = await check_fraud_status(user_id, input["amount"])
    if fraud_check.get("is_fraud") is True:
        raise Exception(f"Transaction Rejected: Fraud Detected ({fraud_check.get('reason')})")

    # 3. Mock API Check
    trx_type_str = input["transaction_type"]
    if trx_type_str == "payment":
        ext_res = await call_external_api_group(input["order_id"], input["amount"])
        if not ext_res["success"]: raise Exception("External API Rejected Transaction")
    
    # 4. Convert String ke Enum Object [PENTING: FIX ERROR ENUM]
    try:
        trx_type_enum = TransactionType(trx_type_str)
    except ValueError:
        raise Exception(f"Invalid transaction type: {trx_type_str}. Valid: deposit, withdrawal, payment, refund")

    wallet_name = await get_wallet_name(input["wallet_id"])

    # Cek apakah Saldo di Wallet cukup jika Withdrawal atau Payment
    if trx_type_enum in [TransactionType.WITHDRAWAL, TransactionType.PAYMENT]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallet/{input['wallet_id']}")
                if response.status_code == 200:
                    wallet = response.json()
                    if wallet.get("balance", 0) < input["amount"]:
                        raise Exception("Insufficient wallet balance for this transaction")
            except Exception as e:
                raise Exception(f"Wallet service error: {e}")
    
    # 5. Save DB
    db: Session = next(get_db())
    new_transaction = Transaction(
        user_id=user_id,
        wallet_id=input["wallet_id"],
        wallet_name=wallet_name,
        transaction_type=trx_type_enum, # Gunakan Object Enum, BUKAN String
        order_id=input["order_id"],
        amount=input["amount"],
        description=input.get("description")
    )

    # Log to History Service
    history_log = {
        "transaction_id": new_transaction.transaction_id or str(uuid.uuid4()),  # Pastikan string, generate jika None
        "user_id": new_transaction.user_id,
        "wallet_id": new_transaction.wallet_id,
        "wallet_name": new_transaction.wallet_name,
        "transaction_type": new_transaction.transaction_type.value,
        "order_id": new_transaction.order_id,
        "amount": new_transaction.amount,
        "description": new_transaction.description,
        "transaction_created_at": (new_transaction.created_at or datetime.utcnow()).isoformat(),
        "status": new_transaction.status or "completed"  # Pastikan string, default jika None
    }
    await log_transaction_history(history_log)

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    # 6. Update Wallet
    await update_wallet_balance(input["wallet_id"], input["amount"], trx_type_str)
    
    return new_transaction

@mutation.field("updateTransaction")
async def resolve_update_transaction(_, info, input):
    transaction_id = input.get("transaction_id")
    trx_type_str = input.get("transaction_type")
    
    db: Session = next(get_db())
    transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not transaction: raise Exception("Transaction not found")
    
    # Fix Error Enum Update
    try:
        transaction.transaction_type = TransactionType(trx_type_str)
    except ValueError:
        raise Exception("Invalid transaction type")
        
    db.commit()
    db.refresh(transaction)
    return transaction

schema = make_executable_schema(type_defs, query, mutation)
app.add_route("/graphql", GraphQL(schema, debug=True))

# ================= REST Endpoints =================
@app.post("/transactions/", response_model=TransactionResponse, dependencies=[Depends(JWTBearer())])
async def create_transaction(transaction: TransactionCreate, token: dict = Depends(JWTBearer()), db: Session = Depends(get_db)):
    user_id = str(token.get("user_id"))
    
    if not await verify_wallet(user_id, transaction.wallet_id):
        raise HTTPException(status_code=400, detail="Wallet invalid")
    
    fraud = await check_fraud_status(user_id, transaction.amount)
    if fraud.get("is_fraud"):
        raise HTTPException(status_code=400, detail=f"Fraud Detected: {fraud.get('reason')}")

    if transaction.transaction_type == TransactionType.PAYMENT:
        ext = await call_external_api_group(transaction.order_id, transaction.amount)
        if not ext["success"]: raise HTTPException(status_code=400, detail="External API Rejected")

    wallet_name = await get_wallet_name(transaction.wallet_id)

    # Cek apakah Saldo di Wallet cukup jika Withdrawal atau Payment
    if transaction.transaction_type in [TransactionType.WITHDRAWAL, TransactionType.PAYMENT]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallet/{transaction.wallet_id}")
                if response.status_code == 200:
                    wallet = response.json()
                    if wallet.get("balance", 0) < transaction.amount:
                        raise HTTPException(status_code=400, detail="Insufficient wallet balance for this transaction")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Wallet service error: {e}")

    # Pydantic otomatis convert string ke Enum, jadi aman
    db_trx = Transaction(
        user_id=user_id,
        wallet_id=transaction.wallet_id,
        wallet_name=wallet_name,
        transaction_type=transaction.transaction_type, 
        order_id=transaction.order_id,
        amount=transaction.amount,
        description=transaction.description
    )
    db.add(db_trx)
    db.commit()
    db.refresh(db_trx)

    # Log to History Service
    history_log = {
        "transaction_id": db_trx.transaction_id or str(uuid.uuid4()),  # Pastikan string, generate jika None
        "user_id": db_trx.user_id,
        "wallet_id": db_trx.wallet_id,
        "wallet_name": db_trx.wallet_name,
        "transaction_type": db_trx.transaction_type.value,
        "order_id": db_trx.order_id,
        "amount": db_trx.amount,
        "description": db_trx.description,
        "transaction_created_at": (db_trx.created_at or datetime.utcnow()).isoformat(),
        "status": db_trx.status or "completed"  # Pastikan string, default jika None
    }
    await log_transaction_history(history_log)
    
    await update_wallet_balance(transaction.wallet_id, transaction.amount, transaction.transaction_type.value)
    return db_trx

@app.put("/transactions/{transaction_id}", response_model=TransactionResponse, dependencies=[Depends(JWTBearer())])
async def update_transaction(transaction_id: str, transaction_update: TransactionUpdate, db: Session = Depends(get_db)):
    db_trx = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not db_trx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    try:
        db_trx.transaction_type = TransactionType(transaction_update.transaction_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transaction type")
    
    db.commit()
    db.refresh(db_trx)
    return db_trx

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=True)