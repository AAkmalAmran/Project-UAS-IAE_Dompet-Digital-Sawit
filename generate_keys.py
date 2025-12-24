import os
import shutil
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Tentukan lokasi folder target (kunci harus ada di user-service)
target_folder = "user-service"

# Pastikan folder user-service ada
if not os.path.exists(target_folder):
    os.makedirs(target_folder)

# Fungsi untuk membersihkan file/folder lama yang bikin error
def clean_path(filename):
    path = os.path.join(target_folder, filename)
    if os.path.exists(path):
        if os.path.isdir(path):
            try:
                shutil.rmtree(path) # Hapus paksa jika itu folder
            except Exception as e:
                print(f"Gagal hapus folder {path}: {e}")
            print(f"🧹 Folder palsu '{filename}' berhasil dihapus.")
        else:
            try:
                os.remove(path) # Hapus jika itu file lama
            except Exception as e:
                print(f"Gagal hapus file {path}: {e}")
            print(f"🗑️ File lama '{filename}' dihapus.")

# 1. Bersihkan area dulu (Hapus folder/file lama)
print("🔍 Memeriksa file kunci lama...")
clean_path("private.pem")
clean_path("public.pem")

# 2. Generate Kunci RSA Baru (2048 bit)
print("🔐 Sedang membuat kunci RSA baru...")
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# 3. Simpan Private Key
priv_path = os.path.join(target_folder, "private.pem")
with open(priv_path, "wb") as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ))

# 4. Generate & Simpan Public Key
public_key = private_key.public_key()
pub_path = os.path.join(target_folder, "public.pem")

with open(pub_path, "wb") as f:
    f.write(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ))

print(f"✅ SUKSES! File 'private.pem' dan 'public.pem' baru sudah ada di folder '{target_folder}'")