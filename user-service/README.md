# User Service

This is a FastAPI-based user management service with REST API and GraphQL support. It handles user registration, login, and role-based access control using JWT tokens and SQLite database.

## Prerequisites
- Docker and Docker Compose installed.
- Copy `.env.example` to `.env` and configure environment variables (e.g., `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`).

## Running the Service
1. open gitbash, run ('cd user-service') 
2. Run (`openssl genrsa -out private.pem 2048`) 
3. Run (`openssl rsa -in private.pem -pubout -out public.pem`)
4. Navigate to the project root (`d:\Project\Project-UAS-IAE_Dompet-Digital-Sawit`).
5. Run the service: `docker-compose up --build -d user-service`
6. The service will be available at `http://localhost:8001`.
7. Access GraphQL playground at `http://localhost:8001/graphql`.

## REST API Endpoints
All endpoints require authentication via JWT token in the `Authorization: Bearer <token>` header, except for registration and login.

- **POST /auth/register**: Register a new user.
  - Body: `{"username": "string", "fullname": "string", "email": "string", "password": "string"}`
  - Response: `{"message": "User registered successfully"}`

- **POST /auth/login**: Login and get JWT token.
  - Body: `{"email": "string", "password": "string"}`
  - Response: `{"access_token": "string", "token_type": "bearer"}`

- **GET /nasabah**: Get user info (requires "Nasabah" role).
  - Response: User details.

- **GET /admin**: Get admin info (requires "Admin" role).
  - Response: Admin details.

- **GET /all-users**: Get all users (requires "Admin" role).
  - Response: List of users.

## GraphQL
The service includes a GraphQL API at `/graphql`.

### Schema
```graphql
type Query {
  myRole(token: String!): String!
}

type Mutation {
  registerUser(
 username: String!
 fullname: String!
 email: String!
 password: String!
  ): String!

  loginUser(
 email: String!
 password: String!
  ): String!
}
