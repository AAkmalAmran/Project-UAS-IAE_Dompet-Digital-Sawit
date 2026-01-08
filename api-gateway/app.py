import httpx
from fastapi import FastAPI, Request
from ariadne import QueryType, MutationType, make_executable_schema, load_schema_from_path
from ariadne.asgi import GraphQL
from fastapi.responses import HTMLResponse
import os

# URL Service (GraphQL Endpoints)
USER_URL = "http://auth-service:8001/graphql"
WALLET_URL = "http://wallet-service:8002/graphql"
TRX_URL = "http://transactions-service:8003/graphql"
FRAUD_URL = "http://fraud-service:8004/graphql"
HISTORY_URL = "http://history-service:8005/graphql"

async def proxy_gql(url, query, vars, req):
    headers = {"Authorization": req.headers.get("Authorization", "")}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={"query": query, "variables": vars}, headers=headers)
            res = resp.json()
            if "errors" in res: raise Exception(res["errors"][0]["message"])
            return res["data"]
        except httpx.RequestError:
            raise Exception("Service Unavailable")

query = QueryType()
mutation = MutationType()

# --- PROXY RESOLVERS ---

# AUTH
@query.field("myProfile")
async def r_prof(_, info, token):
    q = "query($t: String!) { myProfile(token: $t) { user_id username fullname email role } }"
    return (await proxy_gql(USER_URL, q, {"t": token}, info.context["request"]))["myProfile"]

@mutation.field("loginUser")
async def r_login(_, info, email, password):
    q = "mutation($e: String!, $p: String!) { loginUser(email: $e, password: $p) { access_token token_type user { user_id username email role } } }"
    return (await proxy_gql(USER_URL, q, {"e": email, "p": password}, info.context["request"]))["loginUser"]

@mutation.field("registerUser")
async def r_reg(_, info, username, fullname, email, password):
    q = "mutation($u: String!, $f: String!, $e: String!, $p: String!) { registerUser(username: $u, fullname: $f, email: $e, password: $p) }"
    return (await proxy_gql(USER_URL, q, {"u": username, "f": fullname, "e": email, "p": password}, info.context["request"]))["registerUser"]

# WALLET
@query.field("myWallets")
async def r_wallets(_, info):
    q = "{ myWallets { walletId userId walletName balance status } }"
    return (await proxy_gql(WALLET_URL, q, {}, info.context["request"]))["myWallets"]

@mutation.field("createWallet")
async def r_create_wallet(_, info, walletName):
    q = "mutation($n: String!) { createWallet(walletName: $n) { walletId userId walletName balance status } }"
    return (await proxy_gql(WALLET_URL, q, {"n": walletName}, info.context["request"]))["createWallet"]

@mutation.field("deleteWallet")
async def r_delete_wallet(_, info, walletId):
    q = "mutation($id: String!) { deleteWallet(walletId: $id) { success message } }"
    return (await proxy_gql(WALLET_URL, q, {"id": walletId}, info.context["request"]))["deleteWallet"]

# TRANSACTION
@query.field("myTransactions")
async def r_trx(_, info):
    q = "{ myTransactions { transactionId userId walletId amount type status vaNumber createdAt } }"
    return (await proxy_gql(TRX_URL, q, {}, info.context["request"]))["myTransactions"]

@mutation.field("createTransaction")
async def r_create_trx(_, info, input):
    q = "mutation($i: TransactionInput!) { createTransaction(input: $i) { transactionId userId walletId amount type status vaNumber createdAt } }"
    return (await proxy_gql(TRX_URL, q, {"i": input}, info.context["request"]))["createTransaction"]

@mutation.field("deleteAllTransactions")
async def r_delete_all_trx(_, info):
    q = "mutation { deleteAllTransactions }"
    return (await proxy_gql(TRX_URL, q, {}, info.context["request"]))["deleteAllTransactions"]

# FRAUD
@query.field("getFraudLogs")
async def r_fraud(_, info):
    q = "{ getFraudLogs { logId userId amount status reason } }"
    return (await proxy_gql(FRAUD_URL, q, {}, info.context["request"]))["getFraudLogs"]

@mutation.field("deleteFraudLog")
async def r_del_fraud(_, info, logId):
    return (await proxy_gql(FRAUD_URL, "mutation($l: String!) { deleteFraudLog(logId: $l) }", {"l": logId}, info.context["request"]))["deleteFraudLog"]

# HISTORY
@query.field("myHistory")
async def r_hist(_, info):
    q = "{ myHistory { historyId transactionId userId amount type status createdAt } }"
    return (await proxy_gql(HISTORY_URL, q, {}, info.context["request"]))["myHistory"]

@mutation.field("deleteHistory")
async def r_del_hist(_, info, historyId):
    return (await proxy_gql(HISTORY_URL, "mutation($h: String!) { deleteHistory(historyId: $h) }", {"h": historyId}, info.context["request"]))["deleteHistory"]

type_defs = load_schema_from_path("schema.graphql")
schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="Gateway")

@app.get("/", response_class=HTMLResponse) 
async def serve_frontend(): 
    with open("index.html", "r") as f: return f.read()
    
app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)