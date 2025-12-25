import os
import uuid
import uvicorn
import httpx
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from jose import jwt, JWTError

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transactions.db")

# URL Microservices Lain
WALLET_SERVICE_URL = os.getenv("WALLET_SERVICE_URL", "http://wallet-service:8002")
FRAUD_SERVICE_URL = os.getenv("FRAUD_SERVICE_URL", "http://fraud-service:8004")
HISTORY_SERVICE_URL = os.getenv("HISTORY_SERVICE_URL", "http://history-service:8005")

# URL Integrasi Marketplace
EXTERNAL_ORDER_SERVICE_URL = "http://host.docker.internal:6003/graphql"

# --- AUTH SETUP ---
ALGORITHM = "RS256"
PUBLIC_KEY_PATH = "/app/public.pem" 

try:
    with open(PUBLIC_KEY_PATH, "r") as f:
        PUBLIC_KEY = f.read()
except FileNotFoundError:
    print("WARNING: Public Key not found")
    PUBLIC_KEY = ""

def verify_token(authorization: str = Header(...)):
    """Validasi token user sebelum memproses transaksi"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Header")
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Token Invalid atau Expired")

# --- DATABASE ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Transaction(Base):
    __tablename__ = "transactions"
    transaction_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String)
    wallet_id = Column(String)
    amount = Column(Float)
    type = Column(String) # DEPOSIT, PAYMENT
    # [TAMBAHAN] Kolom Order ID untuk referensi Marketplace
    order_id = Column(String, nullable=True) 
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- FUNGSI INTEGRASI MARKETPLACE ---
async def call_external_api_group(order_id: str, amount: float):
    print(f"[INTEGRATION] Connecting to BlackDoctrine Order Service... Order: {order_id}")
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. Validasi: Cek Order ID & Harga
            query_check = """
                query($id: ID!) {
                    getOrder(id: $id) {
                        id
                        totalHarga
                        status
                    }
                }
            """
            res_check = await client.post(
                EXTERNAL_ORDER_SERVICE_URL, 
                json={"query": query_check, "variables": {"id": order_id}}
            )
            
            if res_check.status_code != 200:
                raise Exception("Gagal menghubungi marketplace")
            
            data = res_check.json().get("data", {}).get("getOrder")
            
            if not data:
                return {"success": False, "message": "Order ID tidak ditemukan di BlackDoctrine"}
            
            # Cek Tagihan
            if float(data["totalHarga"]) != float(amount):
                return {
                    "success": False, 
                    "message": f"Nominal salah! Tagihan: {data['totalHarga']}, Dibayar: {amount}"
                }
            
            # 2. Update Status Pembayaran di Marketplace
            mutation_pay = """
                mutation($id: ID!, $status: String!) {
                    updatePaymentStatus(id: $id, status: $status)
                }
            """
            res_pay = await client.post(
                EXTERNAL_ORDER_SERVICE_URL,
                json={"query": mutation_pay, "variables": {"id": order_id, "status": "PROCESSED"}}
            )
            
            if res_pay.status_code == 200 and res_pay.json().get("data", {}).get("updatePaymentStatus"):
                return {"success": True, "message": "Pembayaran berhasil diverifikasi Marketplace"}
            else:
                return {"success": False, "message": "Gagal update status di Marketplace"}

        except Exception as e:
            print(f"Integration Error: {e}")
            return {"success": False, "message": f"Koneksi Marketplace Error: {str(e)}"}

app = FastAPI(title="Transaction Service (Strict + Integration)")

# ================= REST API (ORCHESTRATOR) =================
class TransactionReq(BaseModel):
    wallet_id: str
    amount: float
    type: str
    order_id: Optional[str] = None

@app.post("/rest/transactions", tags=["REST"])
async def create_transaction_rest(
    req: TransactionReq, 
    authorization: str = Header(...),
    user=Depends(verify_token),
    db: Session = Depends(get_db)
):
    user_id = str(user["user_id"])
    forward_headers = {"Authorization": authorization}

    # 1. CEK INTEGRASI MARKETPLACE (Jika Tipe PAYMENT)
    if req.type == "PAYMENT":
        if not req.order_id:
            raise HTTPException(400, "Order ID wajib diisi untuk pembayaran")
            
        # Panggil fungsi integrasi
        integration_res = await call_external_api_group(req.order_id, req.amount)
        if not integration_res["success"]:
            raise HTTPException(400, f"Integrasi Gagal: {integration_res['message']}")

    # 2. CEK FRAUD SERVICE
    async with httpx.AsyncClient() as client:
        try:
            fraud_res = await client.post(
                f"{FRAUD_SERVICE_URL}/rest/check",
                json={"user_id": user_id, "amount": req.amount},
                headers=forward_headers
            )
            if fraud_res.status_code == 200:
                fraud_data = fraud_res.json()
                if fraud_data.get("is_fraud"):
                    raise HTTPException(400, f"Transaksi Ditolak (Fraud): {fraud_data.get('reason')}")
        except httpx.RequestError:
            print("Warning: Fraud Service tidak merespon")

    # 3. UPDATE WALLET SERVICE
    endpoint = "/internal/topup" if req.type == "DEPOSIT" else "/internal/deduct"
    
    async with httpx.AsyncClient() as client:
        wallet_res = await client.post(
            f"{WALLET_SERVICE_URL}{endpoint}",
            json={"wallet_id": req.wallet_id, "amount": req.amount},
            headers=forward_headers
        )
        
        if wallet_res.status_code != 200:
            error_msg = wallet_res.json().get("detail", "Wallet Error")
            raise HTTPException(400, f"Gagal Update Saldo: {error_msg}")

    # 4. SIMPAN TRANSAKSI LOKAL
    trx = Transaction(
        user_id=user_id,
        wallet_id=req.wallet_id,
        amount=req.amount,
        type=req.type,
        order_id=req.order_id, # [TAMBAHAN] Simpan Order ID
        status="SUCCESS"
    )
    db.add(trx)
    db.commit()
    db.refresh(trx)

    # 5. LOG KE HISTORY SERVICE
    async with httpx.AsyncClient() as client:
        try:
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
        except Exception:
            pass

    return trx

@app.get("/rest/transactions/me", tags=["REST"])
def get_my_trx(user=Depends(verify_token), db: Session = Depends(get_db)):
    user_id = str(user["user_id"])
    return db.query(Transaction).filter(Transaction.user_id == user_id).all()

# ================= GRAPHQL WRAPPER =================
type_defs = """
    type Transaction {
        transactionId: String
        userId: String
        walletId: String
        amount: Float
        type: String
        orderId: String
        status: String
        createdAt: String
    }

    input TransactionInput {
        walletId: String!
        amount: Float!
        type: String!
        orderId: String 
    }

    type Query {
        myTransactions: [Transaction]
    }

    type Mutation {
        createTransaction(input: TransactionInput!): Transaction
    }
"""

query = QueryType()
mutation = MutationType()
LOCAL_URL = "http://localhost:8003"

@query.field("myTransactions")
async def resolve_list(_, info):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{LOCAL_URL}/rest/transactions/me",
            headers={"Authorization": auth_header}
        )
        if resp.status_code != 200: return []
        
        data = resp.json()
        return [
            {
                "transactionId": t["transaction_id"], "userId": t["user_id"],
                "walletId": t["wallet_id"], "amount": t["amount"],
                "type": t["type"], "status": t["status"],
                "orderId": t.get("order_id"), 
                "createdAt": t["created_at"]
            } for t in data
        ]

@mutation.field("createTransaction")
async def resolve_create(_, info, input):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")
    
    payload = {
        "wallet_id": input["walletId"], 
        "amount": input["amount"],
        "type": input["type"],
        "order_id": input.get("orderId")
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LOCAL_URL}/rest/transactions",
            json=payload,
            headers={"Authorization": auth_header}
        )
        
        if resp.status_code != 200:
            error_detail = resp.json().get("detail", "Transaction Failed")
            raise Exception(error_detail)
        
        t = resp.json()
        return {
            "transactionId": t["transaction_id"], "userId": t["user_id"],
            "walletId": t["wallet_id"], "amount": t["amount"],
            "type": t["type"], "status": t["status"],
            "orderId": t.get("order_id"),
            "createdAt": t["created_at"]
        }

schema = make_executable_schema(type_defs, query, mutation)

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)