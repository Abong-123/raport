# 📚 Sistem Informasi Manajemen Sekolah

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Status](https://img.shields.io/badge/status-stable-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Argon2](https://img.shields.io/badge/Argon2id-Secure-FF6B6B?style=for-the-badge)](https://argon2.online/)

> Sistem informasi manajemen sekolah berbasis web untuk mengelola data siswa, guru, admin, dan akademik dengan autentikasi aman.

---

## 📋 Daftar Isi
- [Fitur](#-fitur)
- [Teknologi](#-teknologi)
- [Tampilan Aplikasi](#-tampilan-aplikasi)
- [Instalasi](#-instalasi)
- [Default Login](#-default-login)
- [Database Schema](#-database-schema)
- [Lisensi](#-lisensi)

---

## 🚀 Fitur

### 👨‍💼 Admin
- Manajemen User (CRUD admin, guru, murid)
- List & Filter User
- Pengaturan Kelas & Jurusan
- Kelola Ekstrakurikuler
- Rekap Kelas
- Reset Password User

### 👨‍🏫 Guru
- Dashboard khusus guru
- Input & kelola nilai siswa
- Monitoring kelas

### 🧑‍🎓 Murid
- Lihat raport online
- Cetak raport
- Lihat ekstrakurikuler

### 🔐 Keamanan
- Password hashing dengan **Argon2id**
- Role-based access control (Admin, Guru, Murid)

---

## 🛠 Teknologi

| Komponen | Teknologi |
|----------|-----------|
| Backend | FastAPI (Python 3.11) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy |
| Autentikasi | Argon2id hashing |
| Frontend | HTML, CSS, JavaScript |
| Server | Uvicorn |

---

## 📸 Tampilan Aplikasi

Berikut adalah tampilan antarmuka aplikasi:

| Fitur | Screenshot |
|-------|------------|
| Halaman Login | ![Login](picture/login.png) |
| Landing Page | ![Landing](picture/landing.png) |
| Admin - Manajemen User | ![Manajemen User](picture/admin-manajement_user.png) |
| Admin - List User | ![List User](picture/admin-list_user.png) |
| Admin - Pengaturan Kelas | ![Pengaturan Kelas](picture/admin-pengaturan_kelas.png) |
| Admin - Kelola Ekstrakurikuler | ![Ekstrakurikuler](picture/admin-kelola_ekstrakulikuler.png) |
| Admin - Rekap Kelas | ![Rekap Kelas](picture/admin-rekap_kelas.png) |
| Dashboard Guru | ![Dashboard Guru](picture/dashboard_guru.png) |
| Raport Murid | ![Raport Murid](picture/raport_murid.png) |
| Cetak Raport | ![Cetak Raport](picture/raport_murid_cetak.png) |

---

## 💻 Instalasi

### Prasyarat
- Python 3.11+
- PostgreSQL 16+
- pip

### Langkah Instalasi

```bash
# 1. Clone repository
git clone https://github.com/Abong-123/raport.git
cd raport

# 2. Buat virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# atau
venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt
