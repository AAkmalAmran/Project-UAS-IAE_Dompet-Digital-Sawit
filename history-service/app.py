# history-service/app.py
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, status, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Column, String, Float, DateTime, Enum, Index, Text
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from enum import Enum as PyEnum
from dotenv import load_dotenv

from ariadne import QueryType, make_executable_schema
from ariadne.asgi import GraphQL

# =============== ENV & DB SETUP ===============
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./history.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============== ENUMS ===============
class TransactionType(str, PyEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PAYMENT = "payment"
    REFUND = "refund"


class MutationType(str, PyEnum):
    DEBIT = "DEBIT"    # uang keluar
    CREDIT = "CREDIT"  # uang masuk


# =============== MODELS ===============
class HistoryTransaksi(Base):
    """
    Mirror dari Transaction di service_transaksi.
    Menyimpan snapshot transaksi yang sudah terjadi.
    """
    __tablename__ = "history_transaksi"

    history_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String, index=True, nullable=False)  # referensi ke transaksi asli
    user_id = Column(String, index=True, nullable=False)
    wallet_id = Column(String, index=True, nullable=False)
    wallet_name = Column(String, nullable=True)

    transaction_type = Column(Enum(TransactionType), nullable=False)

    order_id = Column(String, index=True, nullable=True)
    amount = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    # waktu log history dicatat
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # waktu transaksi asli di service_transaksi
    transaction_created_at = Column(DateTime, nullable=False)
    status = Column(String, default="completed", nullable=False)

    __table_args__ = (
        Index("idx_hist_trx_user_order", "user_id", "order_id"),
        Index("idx_hist_trx_wallet", "wallet_id"),
    )


class HistoryWallet(Base):
    """
    Mirror dari MutationLog di wallet-service.
    Menyimpan setiap perubahan saldo wallet.
    """
    __tablename__ = "history_wallet"

    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)  # opsional
    transaction_ref_id = Column(String(100), nullable=True)  # id transaksi dari service_transaksi
    type = Column(Enum(MutationType), nullable=False)
    amount = Column(Float, nullable=False)
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_hist_wallet_created_at", "wallet_id", "created_at"),
    )


# =============== Pydantic Schemas ===============
# ---- History Wallet ----
class CreateHistoryWalletRequest(BaseModel):
    wallet_id: str = Field(..., description="Wallet ID")
    user_id: Optional[str] = Field(None, description="User ID pemilik wallet")
    transaction_ref_id: Optional[str] = Field(None, description="Reference dari service_transaksi (transaction_id)")
    type: MutationType
    amount: float
    balance_before: float
    balance_after: float
    description: Optional[str] = None


class HistoryWalletResponse(BaseModel):
    log_id: str
    wallet_id: str
    user_id: Optional[str]
    transaction_ref_id: Optional[str]
    type: str
    amount: float
    balance_before: float
    balance_after: float
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---- History Transaksi ----
class CreateHistoryTransaksiRequest(BaseModel):
    transaction_id: str
    user_id: str
    wallet_id: str
    wallet_name: Optional[str] = None
    transaction_type: TransactionType
    order_id: Optional[str] = None
    amount: float
    description: Optional[str] = None
    transaction_created_at: datetime
    status: str = "completed"


class HistoryTransaksiResponse(BaseModel):
    history_id: str
    transaction_id: str
    user_id: str
    wallet_id: str
    wallet_name: Optional[str]
    transaction_type: str
    order_id: Optional[str]
    amount: float
    description: Optional[str]
    created_at: datetime
    transaction_created_at: datetime
    status: str

    class Config:
        from_attributes = True


# =============== FASTAPI APP ===============
app = FastAPI(
    title="History Service",
    description="Service untuk menyimpan dan membaca riwayat transaksi dan mutasi wallet",
    version="1.0.0",
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "healthy",
        "service": "history-service",
        "timestamp": datetime.utcnow().isoformat()
    }


# =============== REST ENDPOINTS UNTUK SERVICE LAIN ===============
# ---- History Wallet (dipanggil wallet-service) ----
@app.post(
    "/internal/history/wallet",
    response_model=HistoryWalletResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Internal-Wallet"],
)
def create_history_wallet(
    request: CreateHistoryWalletRequest,
    db: Session = Depends(get_db),
):
    log = HistoryWallet(
        wallet_id=request.wallet_id,
        user_id=request.user_id,
        transaction_ref_id=request.transaction_ref_id,
        type=request.type,
        amount=request.amount,
        balance_before=request.balance_before,
        balance_after=request.balance_after,
        description=request.description,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@app.get(
    "/wallet/{wallet_id}",
    response_model=List[HistoryWalletResponse],
    tags=["Internal-Wallet"],
)
def get_history_by_wallet(
    wallet_id: str,
    db: Session = Depends(get_db),
):
    logs = (
        db.query(HistoryWallet)
        .filter(HistoryWallet.wallet_id == wallet_id)
        .order_by(HistoryWallet.created_at.desc())
        .all()
    )
    return logs


# ---- History Transaksi (dipanggil service_transaksi) ----
@app.post(
    "/internal/history/transaction",
    response_model=HistoryTransaksiResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Internal-Transaksi"],
)
def create_history_transaction(
    request: CreateHistoryTransaksiRequest,
    db: Session = Depends(get_db),
):
    hist = HistoryTransaksi(
        transaction_id=request.transaction_id,
        user_id=request.user_id,
        wallet_id=request.wallet_id,
        wallet_name=request.wallet_name,
        transaction_type=request.transaction_type,
        order_id=request.order_id,
        amount=request.amount,
        description=request.description,
        transaction_created_at=request.transaction_created_at,
        status=request.status,
    )
    db.add(hist)
    db.commit()
    db.refresh(hist)
    return hist

# Retrieve semua history transaksi berdasarkan user_id atau transaction_id
@app.get("/history/transactions/") 
def get_transactions_by_user_or_id(
    user_id: Optional[str] = Query(None, description="User ID untuk filter"),
    transaction_id: Optional[str] = Query(None, description="Transaction ID untuk filter"),
    db: Session = Depends(get_db)
):
    query = db.query(HistoryTransaksi)
    
    if user_id:
        query = query.filter(HistoryTransaksi.user_id == user_id)
    if transaction_id:
        query = query.filter(HistoryTransaksi.transaction_id == transaction_id)
    
    histories = query.all()
    
    if not histories:
        raise HTTPException(status_code=404, detail="No transaction histories found for the given criteria")
    
    return histories


# =============== GRAPHQL SCHEMA ===============
type_defs = """
    type HistoryWallet {
        log_id: String!
        wallet_id: String!
        user_id: String
        transaction_ref_id: String
        type: String!
        amount: Float!
        balance_before: Float!
        balance_after: Float!
        description: String
        created_at: String!
    }

    type HistoryTransaksi {
        history_id: String!
        transaction_id: String!
        user_id: String!
        wallet_id: String!
        wallet_name: String
        transaction_type: String!
        order_id: String
        amount: Float!
        description: String
        created_at: String!
        transaction_created_at: String!
        status: String!
    }

    type Query {
        walletHistory(wallet_id: String!): [HistoryWallet!]!
        transactionHistoryByUser(user_id: String!): [HistoryTransaksi!]!
    }
"""

query = QueryType()


@query.field("walletHistory")
def resolve_wallet_history(_, info, wallet_id: str):
    db: Session = SessionLocal()
    try:
        logs = (
            db.query(HistoryWallet)
            .filter(HistoryWallet.wallet_id == wallet_id)
            .order_by(HistoryWallet.created_at.desc())
            .all()
        )
        return [
            {
                "log_id": log.log_id,
                "wallet_id": log.wallet_id,
                "user_id": log.user_id,
                "transaction_ref_id": log.transaction_ref_id,
                "type": log.type.value if hasattr(log.type, "value") else str(log.type),
                "amount": log.amount,
                "balance_before": log.balance_before,
                "balance_after": log.balance_after,
                "description": log.description,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    finally:
        db.close()


@query.field("transactionHistoryByUser")
def resolve_transaction_history_by_user(_, info, user_id: str):
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(HistoryTransaksi)
            .filter(HistoryTransaksi.user_id == user_id)
            .order_by(HistoryTransaksi.created_at.desc())
            .all()
        )
        return [
            {
                "history_id": row.history_id,
                "transaction_id": row.transaction_id,
                "user_id": row.user_id,
                "wallet_id": row.wallet_id,
                "wallet_name": row.wallet_name,
                "transaction_type": row.transaction_type.value
                if hasattr(row.transaction_type, "value") else str(row.transaction_type),
                "order_id": row.order_id,
                "amount": row.amount,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
                "transaction_created_at": row.transaction_created_at.isoformat(),
                "status": row.status,
            }
            for row in rows
        ]
    finally:
        db.close()


schema = make_executable_schema(type_defs, query)
app.add_route("/graphql", GraphQL(schema, debug=True))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005, reload=True)
