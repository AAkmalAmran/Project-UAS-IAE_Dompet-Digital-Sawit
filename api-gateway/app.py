import httpx
from fastapi import FastAPI, Request
# Import load_schema_from_path
from ariadne import QueryType, MutationType, make_executable_schema, load_schema_from_path
from ariadne.asgi import GraphQL
import os

# ================= CONFIG URLs =================
USER_SRV_URL = "http://user-service:8001/graphql"
WALLET_SRV_URL = "http://wallet-service:8002/graphql"
TRX_SRV_URL = "http://transactions-service:8003/graphql"
FRAUD_SRV_URL = "http://fraud-service:8004/graphql"
HISTORY_SRV_URL = "http://history-service:8005/graphql"

# ================= HELPER: PROXY REQUEST =================
async def forward_request(url: str, query: str, variables: dict, request: Request):
    headers = {}
    auth_header = request.headers.get("Authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={"query": query, "variables": variables}, headers=headers)
            if resp.status_code != 200:
                raise Exception(f"Service Error ({resp.status_code}): {resp.text}")

            result = resp.json()
            if "errors" in result:
                raise Exception(result["errors"][0]["message"])
            
            return result.get("data")
        except httpx.RequestError:
            raise Exception("Gagal menghubungi Microservice. Pastikan container berjalan.")

# ================= LOAD SCHEMA DARI FILE =================
# Pastikan file schema.graphql ada di folder yang sama
type_defs = load_schema_from_path("schema.graphql")

query = QueryType()
mutation = MutationType()

# ================= RESOLVERS =================

# --- USER SERVICE ---
@query.field("myProfile")
async def resolve_my_profile(_, info, token):
    q = "query($t: String!) { myProfile(token: $t) { user_id username email role } }"
    data = await forward_request(USER_SRV_URL, q, {"t": token}, info.context["request"])
    return data["myProfile"]

@mutation.field("registerUser")
async def resolve_register(_, info, username, fullname, email, password):
    q = """
        mutation($u: String!, $f: String!, $e: String!, $p: String!) {
            registerUser(username: $u, fullname: $f, email: $e, password: $p)
        }
    """
    vars = {"u": username, "f": fullname, "e": email, "p": password}
    data = await forward_request(USER_SRV_URL, q, vars, info.context["request"])
    return data["registerUser"]

@mutation.field("loginUser")
async def resolve_login(_, info, email, password):
    q = """
        mutation($e: String!, $p: String!) {
            loginUser(email: $e, password: $p) {
                access_token token_type user { user_id username email role }
            }
        }
    """
    data = await forward_request(USER_SRV_URL, q, {"e": email, "p": password}, info.context["request"])
    return data["loginUser"]

# --- WALLET SERVICE ---
@query.field("myWallets")
async def resolve_wallets(_, info):
    q = "{ myWallets { walletId userId walletName balance status } }"
    data = await forward_request(WALLET_SRV_URL, q, {}, info.context["request"])
    return data["myWallets"]

@mutation.field("createWallet")
async def resolve_create_wallet(_, info, walletName):
    q = """
        mutation($n: String!) {
            createWallet(walletName: $n) { walletId userId walletName balance status }
        }
    """
    data = await forward_request(WALLET_SRV_URL, q, {"n": walletName}, info.context["request"])
    return data["createWallet"]

# --- TRANSACTION SERVICE ---
@query.field("myTransactions")
async def resolve_my_trx(_, info):
    q = "{ myTransactions { transactionId userId walletId amount type status createdAt } }"
    data = await forward_request(TRX_SRV_URL, q, {}, info.context["request"])
    return data["myTransactions"]

@mutation.field("createTransaction")
async def resolve_create_trx(_, info, input):
    q = """
        mutation($i: TransactionInput!) {
            createTransaction(input: $i) { transactionId userId walletId amount type status createdAt }
        }
    """
    data = await forward_request(TRX_SRV_URL, q, {"i": input}, info.context["request"])
    return data["createTransaction"]

# --- HISTORY SERVICE ---
@query.field("myHistory")
async def resolve_history(_, info):
    q = "{ myHistory { historyId transactionId userId amount type status createdAt } }"
    data = await forward_request(HISTORY_SRV_URL, q, {}, info.context["request"])
    return data["myHistory"]

# --- FRAUD SERVICE ---
@query.field("getFraudLogs")
async def resolve_fraud_logs(_, info):
    q = "{ getFraudLogs { logId userId amount status reason } }"
    data = await forward_request(FRAUD_SRV_URL, q, {}, info.context["request"])
    return data["getFraudLogs"]

@mutation.field("checkFraud")
async def resolve_check_fraud(_, info, input):
    q = """
        mutation($i: CheckFraudInput!) {
            checkFraud(input: $i) { is_fraud status reason log_id }
        }
    """
    data = await forward_request(FRAUD_SRV_URL, q, {"i": input}, info.context["request"])
    return data["checkFraud"]

# ================= APP SETUP =================
schema = make_executable_schema(type_defs, query, mutation)
app = FastAPI(title="API Gateway (Unified GraphQL)")

@app.get("/health")
def health():
    return {"status": "Gateway Healthy", "port": 8000}

app.add_route("/graphql", GraphQL(schema, debug=True))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)