import os
import uuid
import uvicorn
import httpx
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from jose import jwt, JWTError

from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./history.db")

# --- AUTH SETUP ---
ALGORITHM = "RS256"
PUBLIC_KEY_PATH = "/app/public.pem"
try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "): raise HTTPException(401, "Invalid Header")
    token = authorization.replace("Bearer ", "")
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid Token")

# --- DATABASE ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class History(Base):
    __tablename__ = "history_transaksi"
    history_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String)
    user_id = Column(String)
    amount = Column(Float)
    type = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

app = FastAPI(title="History Service (Strict)")

# ================= REST API =================
class CreateHistoryReq(BaseModel):
    transaction_id: str
    user_id: str
    amount: float
    type: str
    status: str

@app.post("/rest/history", tags=["REST"])
def create_history_rest(req: CreateHistoryReq, user=Depends(verify_token), db: Session = Depends(get_db)):
    """
    Wajib ada Token. Transaction Service harus forward token user saat call endpoint ini.
    """
    h = History(
        transaction_id=req.transaction_id,
        user_id=req.user_id,
        amount=req.amount,
        type=req.type,
        status=req.status
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h

@app.get("/rest/history/me", tags=["REST"])
def get_my_history_rest(user=Depends(verify_token), db: Session = Depends(get_db)):
    """
    Hanya bisa melihat history milik user yang sedang login
    """
    user_id = str(user["user_id"])
    return db.query(History).filter(History.user_id == user_id).all()

# ================= GRAPHQL WRAPPER =================
type_defs = """
    type History {
        historyId: String
        transactionId: String
        userId: String
        amount: Float
        type: String
        status: String
        createdAt: String
    }

    type Query {
        myHistory: [History]
    }
"""

query = QueryType()
LOCAL_URL = "http://localhost:8005"

@query.field("myHistory")
async def resolve_history(_, info):
    request = info.context["request"]
    auth_header = request.headers.get("Authorization")

    async with httpx.AsyncClient() as client:
        # Forward token ke endpoint /me
        resp = await client.get(
            f"{LOCAL_URL}/rest/history/me",
            headers={"Authorization": auth_header}
        )
        if resp.status_code != 200: return []
        
        data = resp.json()
        return [
            {
                "historyId": h["history_id"], "transactionId": h["transaction_id"],
                "userId": h["user_id"], "amount": h["amount"],
                "type": h["type"], "status": h["status"],
                "createdAt": h["created_at"]
            } for h in data
        ]

schema = make_executable_schema(type_defs, query)

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)