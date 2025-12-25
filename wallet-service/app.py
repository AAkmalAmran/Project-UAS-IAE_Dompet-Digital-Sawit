import os
import uuid
import uvicorn
import httpx
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from sqlalchemy import create_engine, Column, String, Float, DateTime, Enum
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from jose import jwt, JWTError

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallets.db")

# --- STRICT AUTH SETUP ---
ALGORITHM = "RS256"
PUBLIC_KEY_PATH = "/app/public.pem"  # Path sesuai mounting docker

try:
    with open(PUBLIC_KEY_PATH, "r") as f:
        PUBLIC_KEY = f.read()
except FileNotFoundError:
    print("WARNING: public.pem not found! Auth will fail.")
    PUBLIC_KEY = ""

def verify_token(authorization: str = Header(...)):
    """Validasi Token JWT menggunakan Public Key"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Auth Header")
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload # Mengembalikan data user (user_id, role, dll)
    except JWTError:
        raise HTTPException(401, "Token Invalid atau Expired")

# --- DATABASE ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class WalletStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"

class Wallet(Base):
    __tablename__ = "wallets"
    wallet_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    wallet_name = Column(String)
    balance = Column(Float, default=0.0)
    status = Column(Enum(WalletStatus), default=WalletStatus.ACTIVE)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

app = FastAPI(title="Wallet Service (Strict JWT)")

# --- REST API (SECURED) ---
class CreateWalletReq(BaseModel):
    wallet_name: str

class UpdateBalanceReq(BaseModel):
    wallet_id: str
    amount: float

@app.post("/rest/wallets", tags=["REST"])
def create_wallet_rest(req: CreateWalletReq, user=Depends(verify_token), db: Session = Depends(get_db)):
    # User ID diambil otomatis dari token, jadi tidak bisa memalsukan user lain
    user_id = str(user["user_id"])
    
    wallet = Wallet(user_id=user_id, wallet_name=req.wallet_name)
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet

@app.get("/rest/wallets/me", tags=["REST"])
def get_my_wallets_rest(user=Depends(verify_token), db: Session = Depends(get_db)):
    user_id = str(user["user_id"])
    return db.query(Wallet).filter(Wallet.user_id == user_id).all()

# Endpoint Internal juga harus diamankan (Service-to-Service pass token)
@app.post("/internal/topup", tags=["INTERNAL"])
def topup_rest(req: UpdateBalanceReq, user=Depends(verify_token), db: Session = Depends(get_db)):
    # Opsional: Cek role jika perlu, atau percayakan validasi token saja
    wallet = db.query(Wallet).filter(Wallet.wallet_id == req.wallet_id).first()
    if not wallet: raise HTTPException(404, "Wallet not found")
    
    wallet.balance += req.amount
    db.commit()
    return {"success": True, "new_balance": wallet.balance}

@app.post("/internal/deduct", tags=["INTERNAL"])
def deduct_rest(req: UpdateBalanceReq, user=Depends(verify_token), db: Session = Depends(get_db)):
    wallet = db.query(Wallet).filter(Wallet.wallet_id == req.wallet_id).first()
    if not wallet: raise HTTPException(404, "Wallet not found")
    
    if wallet.balance < req.amount:
        raise HTTPException(400, "Saldo tidak mencukupi")
    
    wallet.balance -= req.amount
    db.commit()
    return {"success": True, "new_balance": wallet.balance}

# --- GRAPHQL WRAPPER ---
type_defs = """
    type Wallet {
        walletId: String
        userId: String
        walletName: String
        balance: Float
        status: String
    }
    type Query {
        myWallets(userId: String): [Wallet] 
        # userId di sini opsional karena kita ambil dari token
    }
    type Mutation {
        createWallet(walletName: String!): Wallet
    }
"""

query = QueryType()
mutation = MutationType()
LOCAL_URL = "http://localhost:8002"

@query.field("myWallets")
async def resolve_my_wallets(_, info, userId=None):
    # Ambil token dari Header Request GraphQL
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")
    
    async with httpx.AsyncClient() as client:
        # Forward Token ke REST API lokal
        resp = await client.get(
            f"{LOCAL_URL}/rest/wallets/me", 
            headers={"Authorization": auth_header}
        )
        if resp.status_code != 200: return [] # Atau raise Error
        
        data = resp.json()
        return [
            {
                "walletId": w["wallet_id"], "userId": w["user_id"],
                "walletName": w["wallet_name"], "balance": w["balance"],
                "status": w["status"]
            } for w in data
        ]

@mutation.field("createWallet")
async def resolve_create(_, info, walletName):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LOCAL_URL}/rest/wallets", 
            json={"wallet_name": walletName},
            headers={"Authorization": auth_header}
        )
        if resp.status_code != 200:
            raise Exception("Gagal membuat wallet: " + resp.text)
            
        w = resp.json()
        return {
             "walletId": w["wallet_id"], "userId": w["user_id"],
             "walletName": w["wallet_name"], "balance": w["balance"],
             "status": w["status"]
        }

schema = make_executable_schema(type_defs, query, mutation)

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)