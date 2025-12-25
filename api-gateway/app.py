import os
import httpx
from jose import jwt
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import Optional

# ================= ENV & KEYS =================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
ALGORITHM = os.getenv("ALGORITHM", "RS256")

PUBLIC_KEY_PATH = os.path.join(BASE_DIR, "public.pem")
if os.path.exists(PUBLIC_KEY_PATH):
    with open(PUBLIC_KEY_PATH) as f:
        PUBLIC_KEY = f.read()
else:
    PUBLIC_KEY = "" 

app = FastAPI(title="API Gateway Microservices")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= CONFIGURATION =================
SERVICE_MAP = {
    "auth": os.getenv("USER_SERVICE_URL", "http://localhost:8001"),        
    "wallet": os.getenv("WALLET_SERVICE_URL", "http://localhost:8002"),   
    "transactions": os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:8003"), 
    "fraud": os.getenv("FRAUD_SERVICE_URL", "http://localhost:8004"),      
    "history": os.getenv("HISTORY_SERVICE_URL", "http://localhost:8005"),   
}


STRIP_PREFIX_SERVICES = ["wallet", "fraud"]


# ================= AUTH HELPER =================
async def verify_token(request: Request):
    path = request.url.path
    
    # 1. BYPASS AUTH untuk endpoint public (Login, Register, Docs)
    if "login" in path or "register" in path or "docs" in path or "openapi" in path:
        return None

    # 2. VALIDASI TOKEN
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None 

    token = auth_header.split(" ")[1]
    try:
        if not PUBLIC_KEY:
            raise HTTPException(status_code=500, detail="Public Key not found on Gateway")
            
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Token Invalid atau Expired")

# ================= PROXY ROUTE UTAMA =================
@app.api_route("/{service_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway_proxy(service_name: str, path: str, request: Request, user=Depends(verify_token)):
    
    # 1. Cek Service Ada
    target_base_url = SERVICE_MAP.get(service_name)
    if not target_base_url:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' tidak ditemukan")

    # 2. LOGIKA PENYUSUNAN URL
    
    # A. Jika GraphQL -> SELALU STRIP (Langsung ke /graphql)
    if path == "graphql":
        target_url = f"{target_base_url}/{path}"
    
    # B. Jika Service termasuk List STRIP (Wallet, Fraud, History)
    elif service_name in STRIP_PREFIX_SERVICES:
        target_url = f"{target_base_url}/{path}"
        
    # C. Jika Service butuh Prefix (Auth, Transactions)
    else:
        target_url = f"{target_base_url}/{service_name}/{path}"
    
    # 3. KIRIM REQUEST
    query_params = request.url.query
    async with httpx.AsyncClient() as client:
        try:
            req_headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
            
            if user:
                req_headers["x-user-id"] = str(user.get("user_id"))
                req_headers["x-user-role"] = str(user.get("role"))

            body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                params=query_params,
                headers=req_headers,
                content=body,
                timeout=30.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
        except httpx.RequestError as e:
            print(f"Connection Error to {target_url}: {str(e)}")
            raise HTTPException(status_code=503, detail=f"Gagal koneksi ke service {service_name}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)