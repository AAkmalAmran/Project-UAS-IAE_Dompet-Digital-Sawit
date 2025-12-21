# Wallet Service Documentation

## Overview
The Wallet Service is a FastAPI-based microservice for managing digital wallets in a Bank Jago-style system, allowing multiple wallets per user. It supports REST API and GraphQL, with JWT authentication using RSA keys.

## Prerequisites
- Docker and Docker Compose installed.
- Copy [`user-service/.env.example`](user-service/.env.example ) to [`transactions-service/.env`](transactions-service/.env ) and configure environment variables (e.g., [`DATABASE_URL`](user-service/app.py ), [`ALGORITHM`](user-service/app.py ), [`PUBLIC_KEY_PATH`](wallet-service/app.py )).
- Ensure `public.pem` is available (shared from user-service).

## Running the Service
1. Navigate to the project root ([``]( )).
2. Copy file public.pem from user-service
3. Paste file public.pem from user-service
4. Run the service: `docker-compose up --build -d wallet-service`
5. The service will be available at `http://localhost:8002`.
6. Access REST API docs at `http://localhost:8002/docs`.
7. Access GraphQL playground at `http://localhost:8002/graphql`.

## REST API Endpoints
All endpoints require authentication via JWT token in the [`Authorization: Bearer <token>`](user-service/app.py ) header, except internal endpoints.

### Health Check
- **GET /health**: Health check endpoint.
  - Response: [`{"status": "healthy", "service": "wallet-service", "timestamp": "ISO string"}`](wallet-service/app.py )

### User Wallet Endpoints
- **POST /wallets**: Create a new wallet.
  - Body: [`{"wallet_name": "string"}`](wallet-service/app.py )
  - Response: Wallet details.
- **PUT /wallets/{wallet_id}**: Update wallet name.
  - Body: [`{"wallet_name": "string"}`](wallet-service/app.py )
  - Response: Updated wallet details.
- **GET /wallets**: Get all user's wallets.
  - Response: List of wallets.
- **GET /wallets/{wallet_id}**: Get specific wallet.
  - Response: Wallet details.
- **GET /wallets/{wallet_id}/history**: Get wallet mutation history.
  - Response: List of mutation logs.

### Admin Endpoints
- **GET /admin/wallets**: Get all wallets (Admin only).
  - Response: List of all wallets.
- **GET /admin/wallets/user/{user_id}**: Get wallets for a user (Admin only).
  - Response: List of user's wallets.
- **PUT /admin/wallets/{wallet_id}/freeze**: Freeze a wallet (Admin only).
  - Response: Updated wallet.
- **PUT /admin/wallets/{wallet_id}/unfreeze**: Unfreeze a wallet (Admin only).
  - Response: Updated wallet.

### Internal Endpoints (For Other Services)
- **POST /internal/deduct-balance**: Deduct balance from wallet.
  - Body: [`{"wallet_id": "string", "amount": float, "transaction_ref_id": "string", "description": "string"}`](wallet-service/app.py )
  - Response: Deduction result.
- **POST /internal/topup**: Topup balance to wallet.
  - Body: [`{"wallet_id": "string", "amount": float, "transaction_ref_id": "string", "description": "string"}`](wallet-service/app.py )
  - Response: Topup result.
- **GET /internal/wallet/{wallet_id}**: Get wallet details.
  - Response: Wallet details.
- **GET /internal/wallets/user/{user_id}**: Get user's wallets.
  - Response: List of wallets.

## GraphQL API
The service includes a GraphQL API at `/graphql`.

### Schema
```graphql
type Query {
  myWallets: [Wallet!]!
  allWalletsAdmin: [Wallet!]!
  walletHistory(walletId: String!): [MutationLog!]!
}

type Mutation {
  createWallet(walletName: String!): Wallet!
  updateWalletName(walletId: String!, walletName: String!): Wallet!
  topupWallet(walletId: String!, amount: Float!, description: String): TopupResult!
  deleteWallet(walletId: String!): DeleteResult!
}

type TopupResult {
  success: Boolean!
  message: String!
  walletId: String!
  newBalance: Float!
  mutationLogId: String!
}

type DeleteResult {
  success: Boolean!
  message: String!
}

type Wallet {
  walletId: String!
  userId: Int!
  walletName: String!
  balance: Float!
  status: String!
  createdAt: String!
  updatedAt: String!
}

type MutationLog {
  logId: String!
  walletId: String!
  transactionRefId: String
  type: String!
  amount: Float!
  balanceBefore: Float!
  balanceAfter: Float!
  description: String
  createdAt: String!
}
```

### Queries
- **myWallets**: Get all wallets for the authenticated user.
- **allWalletsAdmin**: Get all wallets (Admin only).
- **walletHistory(walletId: String!)**: Get mutation history for a wallet.

### Mutations
- **createWallet(walletName: String!)**: Create a new wallet.
- **updateWalletName(walletId: String!, walletName: String!)**: Update wallet name.
- **topupWallet(walletId: String!, amount: Float!, description: String)**: Topup wallet balance.
- **deleteWallet(walletId: String!)**: Delete a wallet (balance must be 0).
```
```// filepath: d:\Project\Project-UAS-IAE_Dompet-Digital-Sawit\wallet-service\README.md
# Wallet Service Documentation

## Overview
The Wallet Service is a FastAPI-based microservice for managing digital wallets in a Bank Jago-style system, allowing multiple wallets per user. It supports REST API and GraphQL, with JWT authentication using RSA keys.

## Prerequisites
- Docker and Docker Compose installed.
- Copy [`user-service/.env.example`](user-service/.env.example ) to [`transactions-service/.env`](transactions-service/.env ) and configure environment variables (e.g., [`DATABASE_URL`](user-service/app.py ), [`ALGORITHM`](user-service/app.py ), [`PUBLIC_KEY_PATH`](wallet-service/app.py )).
- Ensure `public.pem` is available (shared from user-service).

## Running the Service
1. Navigate to the project root ([``]( )).
2. Run the service: `docker-compose up --build -d wallet-service`
3. The service will be available at `http://localhost:8002`.
4. Access REST API docs at `http://localhost:8002/docs`.
5. Access GraphQL playground at `http://localhost:8002/graphql`.

## REST API Endpoints
All endpoints require authentication via JWT token in the [`Authorization: Bearer <token>`](user-service/app.py ) header, except internal endpoints.

### Health Check
- **GET /health**: Health check endpoint.
  - Response: [`{"status": "healthy", "service": "wallet-service", "timestamp": "ISO string"}`](wallet-service/app.py )

### User Wallet Endpoints
- **POST /wallets**: Create a new wallet.
  - Body: [`{"wallet_name": "string"}`](wallet-service/app.py )
  - Response: Wallet details.
- **PUT /wallets/{wallet_id}**: Update wallet name.
  - Body: [`{"wallet_name": "string"}`](wallet-service/app.py )
  - Response: Updated wallet details.
- **GET /wallets**: Get all user's wallets.
  - Response: List of wallets.
- **GET /wallets/{wallet_id}**: Get specific wallet.
  - Response: Wallet details.
- **GET /wallets/{wallet_id}/history**: Get wallet mutation history.
  - Response: List of mutation logs.

### Admin Endpoints
- **GET /admin/wallets**: Get all wallets (Admin only).
  - Response: List of all wallets.
- **GET /admin/wallets/user/{user_id}**: Get wallets for a user (Admin only).
  - Response: List of user's wallets.
- **PUT /admin/wallets/{wallet_id}/freeze**: Freeze a wallet (Admin only).
  - Response: Updated wallet.
- **PUT /admin/wallets/{wallet_id}/unfreeze**: Unfreeze a wallet (Admin only).
  - Response: Updated wallet.

### Internal Endpoints (For Other Services)
- **POST /internal/deduct-balance**: Deduct balance from wallet.
  - Body: [`{"wallet_id": "string", "amount": float, "transaction_ref_id": "string", "description": "string"}`](wallet-service/app.py )
  - Response: Deduction result.
- **POST /internal/topup**: Topup balance to wallet.
  - Body: [`{"wallet_id": "string", "amount": float, "transaction_ref_id": "string", "description": "string"}`](wallet-service/app.py )
  - Response: Topup result.
- **GET /internal/wallet/{wallet_id}**: Get wallet details.
  - Response: Wallet details.
- **GET /internal/wallets/user/{user_id}**: Get user's wallets.
  - Response: List of wallets.

## GraphQL API
The service includes a GraphQL API at `/graphql`.

### Schema
```graphql
type Query {
  myWallets: [Wallet!]!
  allWalletsAdmin: [Wallet!]!
  walletHistory(walletId: String!): [MutationLog!]!
}

type Mutation {
  createWallet(walletName: String!): Wallet!
  updateWalletName(walletId: String!, walletName: String!): Wallet!
  topupWallet(walletId: String!, amount: Float!, description: String): TopupResult!
  deleteWallet(walletId: String!): DeleteResult!
}

type TopupResult {
  success: Boolean!
  message: String!
  walletId: String!
  newBalance: Float!
  mutationLogId: String!
}

type DeleteResult {
  success: Boolean!
  message: String!
}

type Wallet {
  walletId: String!
  userId: Int!
  walletName: String!
  balance: Float!
  status: String!
  createdAt: String!
  updatedAt: String!
}

type MutationLog {
  logId: String!
  walletId: String!
  transactionRefId: String
  type: String!
  amount: Float!
  balanceBefore: Float!
  balanceAfter: Float!
  description: String
  createdAt: String!
}
```

### Queries
- **myWallets**: Get all wallets for the authenticated user.
- **allWalletsAdmin**: Get all wallets (Admin only).
- **walletHistory(walletId: String!)**: Get mutation history for a wallet.

### Mutations
- **createWallet(walletName: String!)**: Create a new wallet.
- **updateWalletName(walletId: String!, walletName: String!)**: Update wallet name.
- **topupWallet(walletId: String!, amount: Float!, description: String)**: Topup wallet balance.
- **deleteWallet(walletId: String!)**: Delete a wallet (balance must be 0).
```