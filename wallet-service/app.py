import os
import uuid
import uvicorn
from enum import Enum as PyEnum
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine, Column, String, Float, Enum
from sqlalchemy.orm import sessionmaker, declarative_base
from jose import jwt
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/wallets.db")
PUBLIC_KEY_PATH = "/app/public.pem"
try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

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

def get_current_user(request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    except:
        raise Exception("Unauthorized")

type_defs = """
    type Wallet {
        walletId: String
        userId: String
        walletName: String
        balance: Float
        status: String
    }
    type DeleteResponse {
        success: Boolean
        message: String
    }
    type Query {
        myWallets: [Wallet]
    }
    type Mutation {
        createWallet(walletName: String!): Wallet
        topupWallet(walletId: String!, amount: Float!): Wallet
        deductWallet(walletId: String!, amount: Float!): Wallet
        deleteWallet(walletId: String!): DeleteResponse
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("myWallets")
def resolve_wallets(_, info):
    request = info.context["request"]
    user = get_current_user(request)
    db = SessionLocal()
    try:
        wallets = db.query(Wallet).filter(Wallet.user_id == str(user["user_id"])).all()
        return [{"walletId": w.wallet_id, "userId": w.user_id, "walletName": w.wallet_name, "balance": w.balance, "status": w.status} for w in wallets]
    finally:
        db.close()

@mutation.field("createWallet")
def resolve_create(_, info, walletName):
    request = info.context["request"]
    user = get_current_user(request)
    db = SessionLocal()
    try:
        w = Wallet(user_id=str(user["user_id"]), wallet_name=walletName)
        db.add(w)
        db.commit()
        db.refresh(w)
        return {"walletId": w.wallet_id, "userId": w.user_id, "walletName": w.wallet_name, "balance": w.balance, "status": w.status}
    finally:
        db.close()

@mutation.field("topupWallet")
def resolve_topup(_, info, walletId, amount):
    # Validasi token (Service-to-Service juga perlu token valid)
    request = info.context["request"]
    get_current_user(request) 
    
    # Validasi amount tidak boleh negatif
    if amount < 0: raise Exception("Amount must be positive")
    
    db = SessionLocal()
    try:
        w = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        if not w: raise Exception("Wallet not found")
        w.balance += amount
        db.commit()
        return {"walletId": w.wallet_id, "userId": w.user_id, "walletName": w.wallet_name, "balance": w.balance, "status": w.status}
    finally:
        db.close()

@mutation.field("deductWallet")
def resolve_deduct(_, info, walletId, amount):
    request = info.context["request"]
    get_current_user(request)
    
    # Validasi amount tidak boleh negatif
    if amount < 0: raise Exception("Amount must be positive")
    
    db = SessionLocal()
    try:
        w = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        if not w: raise Exception("Wallet not found")
        if w.balance < amount: raise Exception("Saldo Tidak Mencukupi")
        w.balance -= amount
        db.commit()
        return {"walletId": w.wallet_id, "userId": w.user_id, "walletName": w.wallet_name, "balance": w.balance, "status": w.status}
    finally:
        db.close()

@mutation.field("deleteWallet")
def resolve_delete(_, info, walletId):
    request = info.context["request"]
    user = get_current_user(request)
    
    db = SessionLocal()
    try:
        w = db.query(Wallet).filter(Wallet.wallet_id == walletId).first()
        if not w:
            return {"success": False, "message": "Wallet tidak ditemukan"}
        if w.user_id != str(user["user_id"]):
            return {"success": False, "message": "Anda tidak memiliki akses ke wallet ini"}
        
        db.delete(w)
        db.commit()
        return {"success": True, "message": f"Wallet '{w.wallet_name}' berhasil dihapus"}
    finally:
        db.close()

schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="Wallet Service GraphQL")

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)