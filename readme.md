# Project Dompet Digital Sawit

## Cara run sistem untuk saat ini
1. Copy Paste .env.example
2. Rename .env.example to .env
3. open gitbash, run ('cd user-service') 
4. Run (`openssl genrsa -out private.pem 2048`) 
5. Run (`openssl rsa -in private.pem -pubout -out public.pem`)
6. Copy file public.pem from user-service
7. Paste file public.pem from user-service to each services
8. Navigate to the project root (`d:\Project\Project-UAS-IAE_Dompet-Digital-Sawit`).
9. Run the service: `docker-compose up --build -d`