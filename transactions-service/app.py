import os
import uuid
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
import httpx  # Tambahkan ini untuk HTTP requests ke wallet-service

# Ariadne GraphQL imports
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# ================= ENV =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

ALGORITHM = os.getenv("ALGORITHM", "RS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
PUBLIC_KEY = os.getenv("PUBLIC_KEY", "public.pem")

with open(PUBLIC_KEY, "r") as f:
    PUBLIC_KEY = f.read()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transactions.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

WALLET_SERVICE_URL = os.getenv("WALLET_SERVICE_URL", "http://localhost:8002")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001")

# ================= Models =================
class TransactionType(PyEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PAYMENT = "payment"
    REFUND = "refund"


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    wallet_id = Column(String, index=True)
    wallet_name = Column(String, nullable=True)  # Tambahkan kolom wallet_name
    transaction_type = Column(Enum(TransactionType))
    order_id = Column(String, index=True)
    amount = Column(Float)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = Column(String, default="completed")

    __table_args__ = (
        Index('idx_user_order', 'user_id', 'order_id'),
    )

Base.metadata.create_all(bind=engine)

# ================= Verify Wallet Service =================
async def verify_wallet(user_id: str, wallet_id: str) -> bool:
    """Verifikasi apakah wallet_id milik user_id dengan memanggil wallet-service."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallets/user/{user_id}")
            response.raise_for_status()
            wallets = response.json()
            # Periksa apakah wallet_id ada di daftar wallet pengguna
            return any(wallet["wallet_id"] == wallet_id for wallet in wallets)
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=500, detail="Error communicating with wallet-service")
        except Exception:
            return False
        
async def get_wallet_name(wallet_id: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{WALLET_SERVICE_URL}/internal/wallet/{wallet_id}")
        response.raise_for_status()
        wallet = response.json()
        return wallet.get("wallet_name", "")

async def update_wallet_balance(wallet_id: str, amount: float, transaction_type: str):
    async with httpx.AsyncClient() as client:
        if transaction_type == "deposit":
            # Topup
            payload = {"wallet_id": wallet_id, "amount": amount}
            response = await client.post(f"{WALLET_SERVICE_URL}/internal/topup", json=payload)
        else:
            # Deduct for withdrawal or payment
            payload = {"wallet_id": wallet_id, "amount": amount}
            response = await client.post(f"{WALLET_SERVICE_URL}/internal/deduct-balance", json=payload)
        response.raise_for_status()


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
    wallet_name: str  # Tambahkan ini
    transaction_type: str
    order_id: str
    amount: float
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    status: str

class TransactionUpdate(BaseModel):
    transaction_type: TransactionType

# ================= Auth =================
class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super(JWTBearer, self).__init__(auto_error=auto_error)

    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            payload = self.verify_jwt(credentials.credentials)
            if not payload:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token or expired token.")
            return payload  # Return payload instead of just token
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authorization code.")

    def verify_jwt(self, jwtoken: str) -> dict:
        try:
            payload = jwt.decode(jwtoken, PUBLIC_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None

# ================= FastAPI App =================
app = FastAPI(title="Transactions Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
        updated_at: String!
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
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction

@query.field("listTransactions")
def resolve_list_transactions(_, info, user_id):
    db: Session = next(get_db())
    transactions = db.query(Transaction).filter(Transaction.user_id == user_id).all()
    return transactions

@mutation.field("createTransaction")
async def resolve_create_transaction(_, info, input):
    # Ekstrak user_id dari token
    request = info.context["request"]
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header required")
    token = auth_header.replace("Bearer ", "")
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("user_id")
    
    # Verifikasi wallet_id
    wallet_valid = await verify_wallet(user_id, input["wallet_id"])
    if not wallet_valid:
        raise HTTPException(status_code=400, detail="Invalid wallet_id for this user")

    
    # Dapatkan wallet_name
    wallet_name = await get_wallet_name(input["wallet_id"])
    
    db: Session = next(get_db())
    new_transaction = Transaction(
        user_id=user_id,
        wallet_id=input["wallet_id"],
        wallet_name=wallet_name,  # Tambahkan ini
        transaction_type=input["transaction_type"],
        order_id=input["order_id"],
        amount=input["amount"],
        description=input.get("description")
    )
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    # Update balance di wallet-service
    await update_wallet_balance(input["wallet_id"], input["amount"], input["transaction_type"])
    
    return new_transaction

@mutation.field("updateTransaction")
async def update_transaction_type(_, info, input):
    # 1. Ambil data dari dictionary 'input'
    transaction_id = input.get("transaction_id")
    transaction_type = input.get("transaction_type")

    # 2. Inisialisasi DB
    db: Session = next(get_db())

    # 3. Cari Transaksi
    transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()

    if not transaction:
        # Gunakan Exception biasa agar muncul di array 'errors' GraphQL
        raise Exception("Transaction not found")
    
    # 4. Validasi apakah tipe transaksi ada di enum
    if transaction_type not in TransactionType.__members__:
        raise Exception("Invalid transaction type")
    
    # 5. Update tipe transaksi
    transaction.transaction_type = TransactionType[transaction_type]


    db.commit()
    db.refresh(transaction)
    
    return transaction

schema = make_executable_schema(type_defs, query, mutation)
app.add_route("/graphql", GraphQL(schema, debug=True))

# ================= REST Endpoints =================

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "transactions-service", "timestamp": datetime.utcnow().isoformat()}


@app.post("/transactions/", response_model=TransactionResponse, dependencies=[Depends(JWTBearer())])
async def create_transaction(transaction: TransactionCreate, token_payload: dict = Depends(JWTBearer()), db: Session = Depends(get_db)):
    user_id = token_payload.get("user_id")
    
    # Verifikasi wallet_id
    wallet_valid = await verify_wallet(user_id, transaction.wallet_id)
    if not wallet_valid:
        raise HTTPException(status_code=400, detail="Invalid wallet_id for this user")
    
    # Dapatkan wallet_name
    wallet_name = await get_wallet_name(transaction.wallet_id)
    
    db_transaction = Transaction(
        user_id=user_id,
        wallet_id=transaction.wallet_id,
        wallet_name=wallet_name,  # Tambahkan ini
        transaction_type=transaction.transaction_type,
        order_id=transaction.order_id,
        amount=transaction.amount,
        description=transaction.description
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    
    # Update balance di wallet-service
    await update_wallet_balance(transaction.wallet_id, transaction.amount, transaction.transaction_type.value)
    
    return db_transaction

@app.put("/transactions/{transaction_id}", response_model=TransactionResponse, dependencies=[Depends(JWTBearer())])
def update_transaction(
    transaction_id: str, 
    body: TransactionUpdate, 
    db: Session = Depends(get_db)
):
    db_transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    
    if db_transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Ambil data dari body
    db_transaction.transaction_type = body.transaction_type
    
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@app.get("/transactions/{transaction_id}", response_model=TransactionResponse, dependencies=[Depends(JWTBearer())])
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    db_transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if db_transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return db_transaction

@app.get("/users/{user_id}/transactions/", response_model=List[TransactionResponse], dependencies=[Depends(JWTBearer())])
def list_transactions(user_id: str, db: Session = Depends(get_db)):
    transactions = db.query(Transaction).filter(Transaction.user_id == user_id).all()
    return transactions

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=True)

