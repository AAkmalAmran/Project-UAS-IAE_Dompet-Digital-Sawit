import os
import shutil

# Daftar folder service yang memiliki file .env.example
services = [
    "auth-service",        
    "wallet-service",
    "transactions-service",
    "fraud-service",
    "history-service"
]

print("🚀 Memulai proses setup file .env...\n")

for service in services:
    # Tentukan lokasi file sumber dan tujuan
    example_file = os.path.join(service, ".env.example")
    target_file = os.path.join(service, ".env")

    # Cek apakah folder service ada
    if not os.path.exists(service):
        print(f"❌ Folder tidak ditemukan: {service}")
        continue

    # Cek apakah .env.example ada
    if not os.path.exists(example_file):
        print(f"⚠️  Dilewati: Tidak ada .env.example di {service}")
        continue

    # Cek apakah .env sudah ada (agar tidak menimpa konfigurasi yang sudah diedit)
    if os.path.exists(target_file):
        print(f"ℹ️  Dilewati: .env sudah ada di {service}")
    else:
        try:
            shutil.copy(example_file, target_file)
            print(f"✅ Sukses: .env dibuat untuk {service}")
        except Exception as e:
            print(f"🔥 Error menyalin di {service}: {e}")

print("\n✨ Selesai! Sekarang Anda bisa mengedit isi file .env jika diperlukan.")