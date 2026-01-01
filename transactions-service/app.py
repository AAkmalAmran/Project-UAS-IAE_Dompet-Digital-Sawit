import os
import uuid
import uvicorn
import httpx
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from jose import jwt
from ariadne import QueryType, MutationType, make_executable_schema, EnumType
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transactions.db")

# --- SERVICE URLs (Target GraphQL Endpoints) ---
WALLET_URL = os.getenv("WALLET_URL", "http://wallet-service:8002/graphql")
FRAUD_URL = os.getenv("FRAUD_URL", "http://fraud-service:8004/graphql")
HISTORY_URL = os.getenv("HISTORY_URL", "http://history-service:8005/graphql")
EXTERNAL_ORDER_URL = os.getenv("EXTERNAL_ORDER_URL", "http://host.docker.internal:7003/graphql") # INTEGRASI MARKETPLACE

PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", "/app/public.pem")
try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

# --- DB ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Transaction(Base):
    __tablename__ = "transactions"
    transaction_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String)
    wallet_id = Column(String)
    amount = Column(Float)
    type = Column(String)
    va_number = Column(String, nullable=True)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_current_user(request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    except:
        raise Exception("Unauthorized")

# --- HELPER: INTEGRASI MARKETPLACE ---
async def call_external_api_group(va_number: str, amount: float):
    print(f"[INTEGRATION] Checking Marketplace VA: {va_number}")
    async with httpx.AsyncClient() as client:
        try:
            # 1. Cek Tagihan
            q_check = "query($va: String!) { getOrderByVA(vaNumber: $va) { totalHarga } }"
            res = await client.post(EXTERNAL_ORDER_URL, json={"query": q_check, "variables": {"va": va_number}})
            if res.status_code != 200: return {"success": False, "message": "Connection Error"}
            
            data = res.json().get("data", {}).get("getOrderByVA")
            if not data: return {"success": False, "message": "VA Not Found"}
            
            if float(data["totalHarga"]) != float(amount):
                return {"success": False, "message": "Nominal Mismatch"}

            # 2. Update Status di Marketplace
            q_pay = 'mutation($va: String!, $s: String!) { updatePaymentStatus(vaNumber: $va, status: $s) }'
            await client.post(EXTERNAL_ORDER_URL, json={"query": q_pay, "variables": {"va": va_number, "s": "PROCESSED"}})
            
            return {"success": True, "message": "Verified"}
        except Exception as e:
            return {"success": False, "message": str(e)}

# --- HELPER: CALL GRAPHQL SERVICE LAIN ---
async def gql_request(url, query, variables, headers):
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={"query": query, "variables": variables}, headers=headers)
        if resp.status_code != 200: raise Exception(f"Service Error: {resp.text}")
        res = resp.json()
        if "errors" in res: raise Exception(res["errors"][0]["message"])
        return res["data"]

# --- GRAPHQL ---
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
    type Query {
        myTransactions: [Transaction]
    }
    type Mutation {
        createTransaction(input: TransactionInput!): Transaction
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("myTransactions")
def resolve_list(_, info):
    request = info.context["request"]
    user = get_current_user(request)
    db = SessionLocal()
    try:
        trx = db.query(Transaction).filter(Transaction.user_id == str(user["user_id"])).all()
        return [{
            "transactionId": t.transaction_id, 
            "userId": t.user_id, 
            "walletId": t.wallet_id, 
            "amount": t.amount, 
            "type": t.type, 
            "status": t.status, 
            "vaNumber": t.va_number, 
            "createdAt": str(t.created_at)} for t in trx]
    finally:
        db.close()

@mutation.field("createTransaction")
async def resolve_create(_, info, input):
    request = info.context["request"]
    user = get_current_user(request)
    headers = {"Authorization": request.headers.get("Authorization")}
    
    amount = input["amount"]
    wallet_id = input["walletId"]
    trx_type = input["type"]
    va_number = input.get("vaNumber")

    # 1. INTEGRASI MARKETPLACE (Jika Payment)
    if trx_type == "PAYMENT":
        if not va_number: raise Exception("VA Number Required for Payment")
        integ = await call_external_api_group(va_number, amount)
        if not integ["success"]: raise Exception(f"Marketplace Error: {integ['message']}")

    # 2. CEK FRAUD (Call Fraud Service GQL)
    f_q = "mutation($u: String!, $a: Float!) { checkFraud(userId: $u, amount: $a) { is_fraud reason } }"
    f_res = await gql_request(FRAUD_URL, f_q, {"u": str(user["user_id"]), "a": amount}, headers)
    if f_res["checkFraud"]["is_fraud"]: raise Exception(f"Fraud Detected: {f_res['checkFraud']['reason']}")

    # 3. UPDATE WALLET (Call Wallet Service GQL)
    if trx_type == "DEPOSIT":
        w_q = "mutation($id: String!, $a: Float!) { topupWallet(walletId: $id, amount: $a) { balance } }"
    else: # PAYMENT / TRANSFER
        w_q = "mutation($id: String!, $a: Float!) { deductWallet(walletId: $id, amount: $a) { balance } }"
    
    await gql_request(WALLET_URL, w_q, {"id": wallet_id, "a": amount}, headers)

    # 4. SAVE DB
    db = SessionLocal()
    trx = Transaction(user_id=str(user["user_id"]), wallet_id=wallet_id, amount=amount, type=trx_type, va_number=va_number, status="SUCCESS")
    db.add(trx)
    db.commit()
    db.refresh(trx)
    db.close()

    # 5. LOG HISTORY (Call History Service GQL)
    h_q = "mutation($i: HistoryInput!) { addHistory(input: $i) }"
    h_in = {"transactionId": trx.transaction_id, "userId": trx.user_id, "amount": amount, "type": trx_type, "status": "SUCCESS"}
    try: await gql_request(HISTORY_URL, h_q, {"i": h_in}, headers)
    except: pass

    return {"transactionId": trx.transaction_id, "userId": trx.user_id, "walletId": trx.wallet_id, "amount": trx.amount, "type": trx.type, "status": trx.status, "vaNumber": trx.va_number, "createdAt": str(trx.created_at)}

schema = make_executable_schema(type_defs, query, mutation, EnumType("TransactionType", {"DEPOSIT": "DEPOSIT", "PAYMENT": "PAYMENT", "TRANSFER": "TRANSFER"}))
app = FastAPI(title="Transaction Service GraphQL")

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)