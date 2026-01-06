import os
import uuid
import uvicorn
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from jose import jwt
from ariadne import QueryType, MutationType, make_executable_schema
from ariadne.asgi import GraphQL

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/history.db")
PUBLIC_KEY_PATH = "/app/public.pem"
try:
    with open(PUBLIC_KEY_PATH, "r") as f: PUBLIC_KEY = f.read()
except: PUBLIC_KEY = ""

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

def get_current_user(request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    try:
        return jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    except:
        raise Exception("Unauthorized")

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
    input HistoryInput {
        transactionId: String!
        userId: String!
        amount: Float!
        type: String!
        status: String!
    }
    type Query {
        myHistory: [History]
    }
    type Mutation {
        addHistory(input: HistoryInput!): Boolean
        deleteHistory(historyId: String!): Boolean
    }
"""

query = QueryType()
mutation = MutationType()

@query.field("myHistory")
def resolve_history(_, info):
    request = info.context["request"]
    user = get_current_user(request)
    db = SessionLocal()
    try:
        hist = db.query(History).filter(History.user_id == str(user["user_id"])).order_by(History.created_at.desc()).all()
        return [{"historyId": h.history_id, "transactionId": h.transaction_id, "userId": h.user_id, "amount": h.amount, "type": h.type, "status": h.status, "createdAt": str(h.created_at)} for h in hist]
    finally:
        db.close()

@mutation.field("addHistory")
def resolve_add(_, info, input):
    db = SessionLocal()
    try:
        h = History(transaction_id=input["transactionId"], user_id=input["userId"], amount=input["amount"], type=input["type"], status=input["status"])
        db.add(h)
        db.commit()
        return True
    finally:
        db.close()

@mutation.field("deleteHistory")
def resolve_delete(_, info, historyId):
    request = info.context["request"]
    user = get_current_user(request)
    db = SessionLocal()
    try:
        db.query(History).filter(History.history_id == historyId, History.user_id == str(user["user_id"])).delete()
        db.commit()
        return True
    finally:
        db.close()

schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="History Service GraphQL")

@app.on_event("startup")
def startup(): Base.metadata.create_all(bind=engine)
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)