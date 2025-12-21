"""
Wallet Service - Dompet Digital System
A production-ready FastAPI microservice for managing digital wallets (Bank Jago Style)

Features:
- Multiple wallets per user
- JWT Bearer token authentication
- Transaction integration via Internal API
- GraphQL support with Ariadne
- SQLite database with SQLAlchemy ORM

Requirements:
pip install fastapi uvicorn sqlalchemy python-jose[cryptography] python-dotenv ariadne

Run:
uvicorn wallet_service:app --host 0.0.0.0 --port 8001 --reload
"""

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

# Ariadne GraphQL imports
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallets.db")
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

# =============================================================================
# DATABASE SETUP
# =============================================================================

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============================================================================
# ENUMS
# =============================================================================

class WalletStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class MutationType_(str, PyEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


# =============================================================================
# DATABASE MODELS
# =============================================================================

class Wallet(Base):
    """
    Wallet model - Bank Jago Style (Multiple wallets per user)
    """
    __tablename__ = "wallets"

    wallet_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False, index=True)  # NOT Unique - Multiple wallets per user
    wallet_name = Column(String(100), nullable=False)
    balance = Column(Float, default=0.0, nullable=False)
    status = Column(Enum(WalletStatus), default=WalletStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship
    mutations = relationship("MutationLog", back_populates="wallet", cascade="all, delete-orphan")

    # Index for faster queries
    __table_args__ = (
        Index('idx_wallet_user_id', 'user_id'),
    )


class MutationLog(Base):
    """
    Mutation Log - Transaction history for each wallet
    """
    __tablename__ = "mutation_logs"

    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), ForeignKey("wallets.wallet_id"), nullable=False, index=True)
    transaction_ref_id = Column(String(100), nullable=True)  # Reference from Transaction Service
    type = Column(Enum(MutationType_), nullable=False)
    amount = Column(Float, nullable=False)
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    wallet = relationship("Wallet", back_populates="mutations")


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

# --- Request Schemas ---
class CreateWalletRequest(BaseModel):
    wallet_name: str = Field(..., min_length=1, max_length=100, description="Name for the new wallet")


class UpdateWalletRequest(BaseModel):
    wallet_name: str = Field(..., min_length=1, max_length=100, description="New name for the wallet")


class DeductBalanceRequest(BaseModel):
    wallet_id: str = Field(..., description="Wallet ID to deduct from")
    amount: float = Field(..., gt=0, description="Amount to deduct")
    transaction_ref_id: Optional[str] = Field(None, description="Reference ID from Transaction Service")
    description: Optional[str] = Field(None, description="Transaction description")


class TopupRequest(BaseModel):
    wallet_id: str = Field(..., description="Wallet ID to topup")
    amount: float = Field(..., gt=0, description="Amount to topup")
    transaction_ref_id: Optional[str] = Field(None, description="Reference ID from Transaction Service")
    description: Optional[str] = Field(None, description="Topup description")


# --- Response Schemas ---
class WalletResponse(BaseModel):
    wallet_id: str
    user_id: int
    wallet_name: str
    balance: float
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MutationLogResponse(BaseModel):
    log_id: str
    wallet_id: str
    transaction_ref_id: Optional[str]
    type: str
    amount: float
    balance_before: float
    balance_after: float
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class DeductBalanceResponse(BaseModel):
    success: bool
    message: str
    wallet_id: str
    new_balance: float
    mutation_log_id: str


class TopupResponse(BaseModel):
    success: bool
    message: str
    wallet_id: str
    new_balance: float
    mutation_log_id: str


class MessageResponse(BaseModel):
    success: bool
    message: str


# --- Token Payload Schema ---
class TokenPayload(BaseModel):
    user_id: int
    role: str
    username: str


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="Wallet Service - Dompet Digital",
    description="Microservice for managing digital wallets with Bank Jago style (multiple wallets per user)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()


# =============================================================================
# DATABASE DEPENDENCY
# =============================================================================

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# AUTHENTICATION
# =============================================================================

def decode_token(token: str) -> TokenPayload:
    """
    Decode JWT token and extract user information
    Token is generated by external User Service
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id") or payload.get("sub")
        role = payload.get("role", "nasabah")
        username = payload.get("username", "")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: user_id not found",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return TokenPayload(user_id=int(user_id), role=role, username=username)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> TokenPayload:
    """Dependency to get current authenticated user from JWT token"""
    return decode_token(credentials.credentials)


def require_admin(current_user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """Dependency to require admin role"""
    if current_user.role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin role required."
        )
    return current_user


# =============================================================================
# STARTUP EVENT
# =============================================================================

@app.on_event("startup")
def startup_event():
    """Create database tables on startup"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully!")


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "wallet-service", "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# USER WALLET ENDPOINTS
# =============================================================================

@app.post("/wallets", response_model=WalletResponse, status_code=status.HTTP_201_CREATED, tags=["Wallets"])
def create_wallet(
    request: CreateWalletRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user)
):
    """
    Create a new wallet for the authenticated user.
    Bank Jago Style: Users can have multiple wallets (e.g., "Tabungan Nikah", "Jajan Game")
    """
    new_wallet = Wallet(
        wallet_id=str(uuid.uuid4()),
        user_id=current_user.user_id,
        wallet_name=request.wallet_name,
        balance=0.0,
        status=WalletStatus.ACTIVE
    )
    
    db.add(new_wallet)
    db.commit()
    db.refresh(new_wallet)
    
    return new_wallet


@app.put("/wallets/{wallet_id}", response_model=WalletResponse, tags=["Wallets"])
def update_wallet(
    wallet_id: str,
    request: UpdateWalletRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user)
):
    """
    Update/Rename a wallet. Only the owner can update their wallet.
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    # Verify ownership
    if wallet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only update your own wallet."
        )
    
    wallet.wallet_name = request.wallet_name
    wallet.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(wallet)
    
    return wallet


@app.get("/wallets", response_model=List[WalletResponse], tags=["Wallets"])
def get_my_wallets(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user)
):
    """
    Get all wallets belonging to the authenticated user.
    Users can only see their own wallets.
    """
    wallets = db.query(Wallet).filter(Wallet.user_id == current_user.user_id).all()
    return wallets


@app.get("/wallets/{wallet_id}", response_model=WalletResponse, tags=["Wallets"])
def get_wallet_by_id(
    wallet_id: str,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user)
):
    """
    Get a specific wallet by ID.
    Users can only see their own wallets. Admin can see any wallet.
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    # Verify ownership (unless admin)
    if wallet.user_id != current_user.user_id and current_user.role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only view your own wallet."
        )
    
    return wallet


@app.get("/wallets/{wallet_id}/history", response_model=List[MutationLogResponse], tags=["Wallets"])
def get_wallet_history(
    wallet_id: str,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user)
):
    """
    Get mutation history/logs for a specific wallet.
    Users can only see history of their own wallets.
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    # Verify ownership (unless admin)
    if wallet.user_id != current_user.user_id and current_user.role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only view your own wallet history."
        )
    
    mutations = db.query(MutationLog)\
        .filter(MutationLog.wallet_id == wallet_id)\
        .order_by(MutationLog.created_at.desc())\
        .all()
    
    return mutations


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.get("/admin/wallets", response_model=List[WalletResponse], tags=["Admin"])
def get_all_wallets(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin)
):
    """
    Get all wallets in the system (Admin only).
    """
    wallets = db.query(Wallet).all()
    return wallets


@app.get("/admin/wallets/user/{user_id}", response_model=List[WalletResponse], tags=["Admin"])
def get_wallets_by_user_id(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin)
):
    """
    Get all wallets for a specific user (Admin only).
    """
    wallets = db.query(Wallet).filter(Wallet.user_id == user_id).all()
    return wallets


@app.put("/admin/wallets/{wallet_id}/freeze", response_model=WalletResponse, tags=["Admin"])
def freeze_wallet(
    wallet_id: str,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin)
):
    """
    Freeze a wallet (Admin only). Frozen wallets cannot be used for transactions.
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    wallet.status = WalletStatus.FROZEN
    wallet.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(wallet)
    
    return wallet


@app.put("/admin/wallets/{wallet_id}/unfreeze", response_model=WalletResponse, tags=["Admin"])
def unfreeze_wallet(
    wallet_id: str,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin)
):
    """
    Unfreeze/Activate a wallet (Admin only).
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    wallet.status = WalletStatus.ACTIVE
    wallet.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(wallet)
    
    return wallet


# =============================================================================
# INTERNAL API ENDPOINTS (For Transaction Service)
# =============================================================================

@app.post("/internal/deduct-balance", response_model=DeductBalanceResponse, tags=["Internal"])
def deduct_balance(
    request: DeductBalanceRequest,
    db: Session = Depends(get_db)
):
    """
    Internal API endpoint for Transaction Service to deduct balance from a wallet.
    
    Logic (Sequence Diagram Compliance):
    1. Check if Wallet exists and is ACTIVE
    2. Check if balance >= amount
    3. If insufficient, raise HTTP 400 with "Saldo tidak mencukupi"
    4. If safe, deduct balance -> Save Wallet -> Create MutationLog (DEBIT)
    5. Return success response with new_balance
    """
    # Step 1: Check if wallet exists
    wallet = db.query(Wallet).filter(Wallet.wallet_id == request.wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    # Step 1b: Check if wallet is ACTIVE
    if wallet.status != WalletStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet is frozen. Cannot perform transactions."
        )
    
    # Step 2: Check if balance >= amount
    if wallet.balance < request.amount:
        # Step 3: CRUCIAL - Raise specific error for frontend notification
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Saldo tidak mencukupi"  # Insufficient Funds
        )
    
    # Step 4: Deduct balance
    balance_before = wallet.balance
    wallet.balance -= request.amount
    balance_after = wallet.balance
    wallet.updated_at = datetime.utcnow()
    
    # Create MutationLog (DEBIT)
    mutation_log = MutationLog(
        log_id=str(uuid.uuid4()),
        wallet_id=wallet.wallet_id,
        transaction_ref_id=request.transaction_ref_id,
        type=MutationType_.DEBIT,
        amount=request.amount,
        balance_before=balance_before,
        balance_after=balance_after,
        description=request.description or "Balance deduction"
    )
    
    db.add(mutation_log)
    db.commit()
    db.refresh(wallet)
    db.refresh(mutation_log)
    
    # Step 5: Return success response
    return DeductBalanceResponse(
        success=True,
        message="Balance deducted successfully",
        wallet_id=wallet.wallet_id,
        new_balance=wallet.balance,
        mutation_log_id=mutation_log.log_id
    )


@app.post("/internal/topup", response_model=TopupResponse, tags=["Internal"])
def topup_balance(
    request: TopupRequest,
    db: Session = Depends(get_db)
):
    """
    Internal API endpoint to topup/add balance to a wallet (CREDIT).
    """
    # Check if wallet exists
    wallet = db.query(Wallet).filter(Wallet.wallet_id == request.wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    # Check if wallet is ACTIVE
    if wallet.status != WalletStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet is frozen. Cannot perform transactions."
        )
    
    # Add balance
    balance_before = wallet.balance
    wallet.balance += request.amount
    balance_after = wallet.balance
    wallet.updated_at = datetime.utcnow()
    
    # Create MutationLog (CREDIT)
    mutation_log = MutationLog(
        log_id=str(uuid.uuid4()),
        wallet_id=wallet.wallet_id,
        transaction_ref_id=request.transaction_ref_id,
        type=MutationType_.CREDIT,
        amount=request.amount,
        balance_before=balance_before,
        balance_after=balance_after,
        description=request.description or "Balance topup"
    )
    
    db.add(mutation_log)
    db.commit()
    db.refresh(wallet)
    db.refresh(mutation_log)
    
    return TopupResponse(
        success=True,
        message="Topup successful",
        wallet_id=wallet.wallet_id,
        new_balance=wallet.balance,
        mutation_log_id=mutation_log.log_id
    )


@app.get("/internal/wallet/{wallet_id}", response_model=WalletResponse, tags=["Internal"])
def get_wallet_internal(
    wallet_id: str,
    db: Session = Depends(get_db)
):
    """
    Internal API to get wallet details (for other microservices).
    No authentication required for internal calls.
    """
    wallet = db.query(Wallet).filter(Wallet.wallet_id == wallet_id).first()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    
    return wallet


@app.get("/internal/wallets/user/{user_id}", response_model=List[WalletResponse], tags=["Internal"])
def get_user_wallets_internal(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Internal API to get all wallets for a user (for other microservices).
    No authentication required for internal calls.
    """
    wallets = db.query(Wallet).filter(Wallet.user_id == user_id).all()
    return wallets


# =============================================================================
# GRAPHQL SETUP (Ariadne)
# =============================================================================

type_defs = """
    type Query {
        myWallets: [Wallet!]!
        allWalletsAdmin: [Wallet!]!
        walletHistory(walletId: String!): [MutationLog!]!
    }
    
    type Mutation {
        createWallet(walletName: String!): Wallet!
        updateWalletName(walletId: String!, walletName: String!): Wallet!
        topupWallet(walletId: String!, amount: Float!, description: String): TopupResult!
        deleteWallet(walletId: String!): DeleteResult!
    }
    
    type TopupResult {
        success: Boolean!
        message: String!
        walletId: String!
        newBalance: Float!
        mutationLogId: String!
    }
    
    type DeleteResult {
        success: Boolean!
        message: String!
    }
    
    type Wallet {
        walletId: String!
        userId: Int!
        walletName: String!
        balance: Float!
        status: String!
        createdAt: String!
        updatedAt: String!
    }
    
    type MutationLog {
        logId: String!
        walletId: String!
        transactionRefId: String
        type: String!
        amount: Float!
        balanceBefore: Float!
        balanceAfter: Float!
        description: String
        createdAt: String!
    }
"""

query = QueryType()
mutation = MutationType()


def get_user_from_context(info) -> TokenPayload:
    """Extract user from GraphQL context (request headers)"""
    request = info.context["request"]
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header.startswith("Bearer "):
        raise Exception("Authorization header required")
    
    token = auth_header.replace("Bearer ", "")
    return decode_token(token)


@query.field("myWallets")
def resolve_my_wallets(_, info):
    """Get all wallets for the authenticated user"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        wallets = db.query(Wallet).filter(Wallet.user_id == user.user_id).all()
        return [
            {
                "walletId": w.wallet_id,
                "userId": w.user_id,
                "walletName": w.wallet_name,
                "balance": w.balance,
                "status": w.status.value if hasattr(w.status, 'value') else w.status,
                "createdAt": w.created_at.isoformat(),
                "updatedAt": w.updated_at.isoformat()
            }
            for w in wallets
        ]
    finally:
        db.close()


@query.field("allWalletsAdmin")
def resolve_all_wallets_admin(_, info):
    """Get all wallets (Admin only)"""
    user = get_user_from_context(info)
    
    if user.role.lower() != "admin":
        raise Exception("Access denied. Admin role required.")
    
    db = SessionLocal()
    try:
        wallets = db.query(Wallet).all()
        return [
            {
                "walletId": w.wallet_id,
                "userId": w.user_id,
                "walletName": w.wallet_name,
                "balance": w.balance,
                "status": w.status.value if hasattr(w.status, 'value') else w.status,
                "createdAt": w.created_at.isoformat(),
                "updatedAt": w.updated_at.isoformat()
            }
            for w in wallets
        ]
    finally:
        db.close()


@query.field("walletHistory")
def resolve_wallet_history(_, info, walletId: str):
    """Get mutation history for a wallet"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        wallet = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        
        if not wallet:
            raise Exception("Wallet not found")
        
        if wallet.user_id != user.user_id and user.role.lower() != "admin":
            raise Exception("Access denied")
        
        mutations = db.query(MutationLog)\
            .filter(MutationLog.wallet_id == walletId)\
            .order_by(MutationLog.created_at.desc())\
            .all()
        
        return [
            {
                "logId": m.log_id,
                "walletId": m.wallet_id,
                "transactionRefId": m.transaction_ref_id,
                "type": m.type.value if hasattr(m.type, 'value') else m.type,
                "amount": m.amount,
                "balanceBefore": m.balance_before,
                "balanceAfter": m.balance_after,
                "description": m.description,
                "createdAt": m.created_at.isoformat()
            }
            for m in mutations
        ]
    finally:
        db.close()


@mutation.field("createWallet")
def resolve_create_wallet(_, info, walletName: str):
    """Create a new wallet for the authenticated user"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        new_wallet = Wallet(
            wallet_id=str(uuid.uuid4()),
            user_id=user.user_id,
            wallet_name=walletName,
            balance=0.0,
            status=WalletStatus.ACTIVE
        )
        
        db.add(new_wallet)
        db.commit()
        db.refresh(new_wallet)
        
        return {
            "walletId": new_wallet.wallet_id,
            "userId": new_wallet.user_id,
            "walletName": new_wallet.wallet_name,
            "balance": new_wallet.balance,
            "status": new_wallet.status.value if hasattr(new_wallet.status, 'value') else new_wallet.status,
            "createdAt": new_wallet.created_at.isoformat(),
            "updatedAt": new_wallet.updated_at.isoformat()
        }
    finally:
        db.close()


@mutation.field("updateWalletName")
def resolve_update_wallet_name(_, info, walletId: str, walletName: str):
    """Update/Rename a wallet"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        wallet = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        
        if not wallet:
            raise Exception("Wallet not found")
        
        if wallet.user_id != user.user_id:
            raise Exception("Access denied. You can only update your own wallet.")
        
        wallet.wallet_name = walletName
        wallet.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(wallet)
        
        return {
            "walletId": wallet.wallet_id,
            "userId": wallet.user_id,
            "walletName": wallet.wallet_name,
            "balance": wallet.balance,
            "status": wallet.status.value if hasattr(wallet.status, 'value') else wallet.status,
            "createdAt": wallet.created_at.isoformat(),
            "updatedAt": wallet.updated_at.isoformat()
        }
    finally:
        db.close()


@mutation.field("topupWallet")
def resolve_topup_wallet(_, info, walletId: str, amount: float, description: str = None):
    """Topup/Add balance to a wallet"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        wallet = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        
        if not wallet:
            raise Exception("Wallet not found")
        
        # Verify ownership
        if wallet.user_id != user.user_id:
            raise Exception("Access denied. You can only topup your own wallet.")
        
        # Check if wallet is active
        if wallet.status != WalletStatus.ACTIVE:
            raise Exception("Wallet is frozen. Cannot perform transactions.")
        
        # Validate amount
        if amount <= 0:
            raise Exception("Amount must be greater than 0")
        
        # Add balance
        balance_before = wallet.balance
        wallet.balance += amount
        balance_after = wallet.balance
        wallet.updated_at = datetime.utcnow()
        
        # Create MutationLog (CREDIT)
        mutation_log = MutationLog(
            log_id=str(uuid.uuid4()),
            wallet_id=wallet.wallet_id,
            transaction_ref_id=None,
            type=MutationType_.CREDIT,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description or "Topup via GraphQL"
        )
        
        db.add(mutation_log)
        db.commit()
        db.refresh(wallet)
        db.refresh(mutation_log)
        
        return {
            "success": True,
            "message": "Topup successful",
            "walletId": wallet.wallet_id,
            "newBalance": wallet.balance,
            "mutationLogId": mutation_log.log_id
        }
    finally:
        db.close()


@mutation.field("deleteWallet")
def resolve_delete_wallet(_, info, walletId: str):
    """Delete a wallet (balance must be 0)"""
    user = get_user_from_context(info)
    db = SessionLocal()
    try:
        wallet = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        
        if not wallet:
            raise Exception("Wallet not found")
        
        # Verify ownership
        if wallet.user_id != user.user_id:
            raise Exception("Access denied. You can only delete your own wallet.")
        
        # Check balance - must be 0 to delete
        if wallet.balance > 0:
            raise Exception(f"Cannot delete wallet with balance. Current balance: {wallet.balance}. Please withdraw all funds first.")
        
        # Delete the wallet (this will also cascade delete mutation logs)
        db.delete(wallet)
        db.commit()
        
        return {
            "success": True,
            "message": f"Wallet '{wallet.wallet_name}' deleted successfully"
        }
    finally:
        db.close()


# Create GraphQL schema
schema = make_executable_schema(type_defs, query, mutation)

# Mount Ariadne's default GraphQL ASGI app (same as user-service)
app.add_route("/graphql", GraphQL(schema, debug=True))


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, reload=True)

