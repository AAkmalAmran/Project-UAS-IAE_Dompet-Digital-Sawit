# 💰 Wallet Service - Dompet Digital

Microservice untuk mengelola dompet digital dengan gaya Bank Jago (multiple wallets per user).

## 📋 Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [API Documentation](#api-documentation)
- [GraphQL Demo](#graphql-demo)
- [REST API Testing Guide](#rest-api-testing-guide)

---

## 🎯 Overview

Wallet Service adalah microservice yang menyediakan fitur:
- ✅ **Multiple Wallets per User** - Seperti Bank Jago (Tabungan Nikah, Jajan Game, dll)
- ✅ **JWT Authentication** - Integrasi dengan User Service
- ✅ **REST API + GraphQL** - Dual interface
- ✅ **Mutation History** - Log semua transaksi (DEBIT/CREDIT)
- ✅ **Admin Features** - Freeze/Unfreeze wallet, lihat semua data

---

## 🛠 Tech Stack

| Technology | Purpose |
|------------|---------|
| FastAPI | Web Framework |
| SQLAlchemy | ORM |
| SQLite | Database |
| Ariadne | GraphQL |
| python-jose | JWT Token |

---

## 🚀 Quick Start

### Running with Docker

```bash
# Build and run
docker-compose up --build -d wallet-service

# Check status
docker-compose ps

# View logs
docker-compose logs -f wallet-service
```

### Running Locally

```bash
cd wallet-service
pip install -r requirements.txt
uvicorn wallet_service:app --host 0.0.0.0 --port 8002 --reload
```

### Access Points

| Service | URL |
|---------|-----|
| REST API Docs (Swagger) | http://localhost:8002/docs |
| REST API Docs (ReDoc) | http://localhost:8002/redoc |
| GraphQL Playground | http://localhost:8002/graphql |
| Health Check | http://localhost:8002/health |

---

## 🔐 Authentication

Wallet Service menggunakan JWT token dari User Service.

### Step 1: Login ke User Service

```bash
curl -X POST "http://localhost:8001/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### Step 2: Gunakan Token untuk Wallet Service

```bash
# Set token sebagai variable
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Gunakan di request
curl -X GET "http://localhost:8002/wallets" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📖 API Documentation

### 👤 User Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/wallets` | Buat wallet baru |
| GET | `/wallets` | Lihat semua wallet saya |
| GET | `/wallets/{wallet_id}` | Lihat detail wallet |
| PUT | `/wallets/{wallet_id}` | Rename wallet |
| GET | `/wallets/{wallet_id}/history` | Lihat history mutasi |

### 👑 Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/wallets` | Lihat semua wallet |
| GET | `/admin/wallets/user/{user_id}` | Lihat wallet by user |
| PUT | `/admin/wallets/{wallet_id}/freeze` | Bekukan wallet |
| PUT | `/admin/wallets/{wallet_id}/unfreeze` | Buka blokir wallet |

### 🔧 Internal API (For Transaction Service)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/internal/deduct-balance` | Kurangi saldo (DEBIT) |
| POST | `/internal/topup` | Tambah saldo (CREDIT) |
| GET | `/internal/wallet/{wallet_id}` | Get wallet info |
| GET | `/internal/wallets/user/{user_id}` | Get user wallets |

---

## 🧪 REST API Testing Guide

### 1️⃣ Create New Wallet

```bash
curl -X POST "http://localhost:8002/wallets" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"wallet_name": "Tabungan Nikah"}'
```

**Expected Response:**
```json
{
  "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "wallet_name": "Tabungan Nikah",
  "balance": 0.0,
  "status": "ACTIVE",
  "created_at": "2025-12-20T15:00:00",
  "updated_at": "2025-12-20T15:00:00"
}
```

### 2️⃣ Get My Wallets

```bash
curl -X GET "http://localhost:8002/wallets" \
  -H "Authorization: Bearer $TOKEN"
```

**Expected Response:**
```json
[
  {
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": 1,
    "wallet_name": "Tabungan Nikah",
    "balance": 0.0,
    "status": "ACTIVE",
    "created_at": "2025-12-20T15:00:00",
    "updated_at": "2025-12-20T15:00:00"
  }
]
```

### 3️⃣ Rename Wallet

```bash
curl -X PUT "http://localhost:8002/wallets/{wallet_id}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"wallet_name": "Dana Darurat"}'
```

### 4️⃣ Topup Wallet (Internal API)

```bash
curl -X POST "http://localhost:8002/internal/topup" \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount": 100000,
    "description": "Topup dari Bank BCA"
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Topup successful",
  "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
  "new_balance": 100000.0,
  "mutation_log_id": "log-uuid-here"
}
```

### 5️⃣ Deduct Balance (Internal API)

```bash
curl -X POST "http://localhost:8002/internal/deduct-balance" \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount": 25000,
    "transaction_ref_id": "TRX-001",
    "description": "Bayar pulsa"
  }'
```

**Expected Response (Success):**
```json
{
  "success": true,
  "message": "Balance deducted successfully",
  "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
  "new_balance": 75000.0,
  "mutation_log_id": "log-uuid-here"
}
```

**Expected Response (Insufficient Balance):**
```json
{
  "detail": "Saldo tidak mencukupi"
}
```

### 6️⃣ Get Wallet History

```bash
curl -X GET "http://localhost:8002/wallets/{wallet_id}/history" \
  -H "Authorization: Bearer $TOKEN"
```

**Expected Response:**
```json
[
  {
    "log_id": "log-uuid-2",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "transaction_ref_id": "TRX-001",
    "type": "DEBIT",
    "amount": 25000,
    "balance_before": 100000,
    "balance_after": 75000,
    "description": "Bayar pulsa",
    "created_at": "2025-12-20T15:05:00"
  },
  {
    "log_id": "log-uuid-1",
    "wallet_id": "550e8400-e29b-41d4-a716-446655440000",
    "transaction_ref_id": null,
    "type": "CREDIT",
    "amount": 100000,
    "balance_before": 0,
    "balance_after": 100000,
    "description": "Topup dari Bank BCA",
    "created_at": "2025-12-20T15:00:00"
  }
]
```

### 7️⃣ Admin: Freeze Wallet

```bash
curl -X PUT "http://localhost:8002/admin/wallets/{wallet_id}/freeze" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 🎮 GraphQL Demo

### Access GraphQL Playground

Buka browser dan akses: **http://localhost:8002/graphql**

### Setup Headers

Di tab **Headers** (bawah), tambahkan:

```json
{
  "Authorization": "Bearer YOUR_JWT_TOKEN"
}
```

### Query Examples

#### 📋 Get My Wallets

```graphql
query GetMyWallets {
  myWallets {
    walletId
    userId
    walletName
    balance
    status
    createdAt
    updatedAt
  }
}
```

#### 📋 Get All Wallets (Admin Only)

```graphql
query GetAllWalletsAdmin {
  allWalletsAdmin {
    walletId
    userId
    walletName
    balance
    status
    createdAt
    updatedAt
  }
}
```

#### 📋 Get Wallet History

```graphql
query GetWalletHistory {
  walletHistory(walletId: "YOUR_WALLET_ID_HERE") {
    logId
    walletId
    transactionRefId
    type
    amount
    balanceBefore
    balanceAfter
    description
    createdAt
  }
}
```

### Mutation Examples

#### ✏️ Create New Wallet

```graphql
mutation CreateNewWallet {
  createWallet(walletName: "Tabungan Liburan") {
    walletId
    userId
    walletName
    balance
    status
    createdAt
  }
}
```

#### ✏️ Rename Wallet

```graphql
mutation RenameWallet {
  updateWalletName(
    walletId: "YOUR_WALLET_ID_HERE"
    walletName: "Dana Pendidikan"
  ) {
    walletId
    walletName
    updatedAt
  }
}
```

---

## 📊 Database Schema

### Wallets Table

| Column | Type | Description |
|--------|------|-------------|
| wallet_id | UUID | Primary Key |
| user_id | INTEGER | Owner user ID (NOT UNIQUE - multiple wallets allowed) |
| wallet_name | VARCHAR(100) | Nama wallet |
| balance | FLOAT | Saldo saat ini |
| status | ENUM | ACTIVE / FROZEN |
| created_at | DATETIME | Waktu dibuat |
| updated_at | DATETIME | Waktu update terakhir |

### Mutation Logs Table

| Column | Type | Description |
|--------|------|-------------|
| log_id | UUID | Primary Key |
| wallet_id | UUID | Foreign Key ke Wallets |
| transaction_ref_id | VARCHAR | Reference dari Transaction Service |
| type | ENUM | DEBIT / CREDIT |
| amount | FLOAT | Jumlah transaksi |
| balance_before | FLOAT | Saldo sebelum |
| balance_after | FLOAT | Saldo sesudah |
| description | TEXT | Keterangan |
| created_at | DATETIME | Waktu transaksi |

---

## 🔧 Environment Variables

```env
# Database
DATABASE_URL=sqlite:///./wallets.db

# JWT Configuration (must match User Service)
SECRET_KEY=your-super-secret-key-change-in-production
ALGORITHM=HS256
```

---

## 📞 Support

For issues or questions, please open an issue in the repository.

---

**Made with ❤️ for UAS IAE - Dompet Digital Sawit**
