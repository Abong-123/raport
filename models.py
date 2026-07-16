# models.py - FIXED VERSION
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, Enum, Date, UniqueConstraint, Text
from sqlalchemy.orm import relationship
from database import Base
import enum
from datetime import date

# ========== ENUMS ==========
class UserRole(enum.Enum):
    admin = "admin"
    guru = "guru"
    murid = "murid"

class StatusRaport(enum.Enum):
    draft = "draft"           # Belum diisi
    submitted = "submitted"   # Sudah diisi guru
    published = "published"   # Sudah dipublikasi (bisa dilihat murid)


# =========== KURIKULUM =========
class Kurikulum(Base):
    __tablename__ = 'kurikulum'
    
    id = Column(Integer, primary_key=True)
    nama_kurikulum = Column(String(100), nullable=False)
    tahun_ajaran = Column(String(20), nullable=False)
    semester = Column(String(10), nullable=False)  # <-- PINDAHKAN SEMESTER KE SINI
    deskripsi = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=date.today)
    
    # Relasi (pake string, lowercase)
    kelas = relationship("Kelas", back_populates="kurikulum")
    mata_pelajaran = relationship("MataPelajaran", back_populates="kurikulum")
    
    __table_args__ = (UniqueConstraint('tahun_ajaran', 'semester', name='unique_tahun_semester'),)


# ========== MATA PELAJARAN ==========
class MataPelajaran(Base):
    __tablename__ = 'mata_pelajaran'
    
    id = Column(Integer, primary_key=True)
    kurikulum_id = Column(Integer, ForeignKey("kurikulum.id", ondelete="CASCADE"), nullable=False)
    
    kode_mapel = Column(String(20), nullable=False)  # <-- REMOVE unique=True (already in composite)
    nama_mapel = Column(String(100), nullable=False)
    kategori = Column(String(50), nullable=True)
    kkm = Column(Integer, nullable=False, default=75)
    is_active = Column(Boolean, default=True)
    
    # Relasi
    kurikulum = relationship("Kurikulum", back_populates="mata_pelajaran")
    kelas_mapel = relationship("KelasMapel", back_populates="mapel")
    
    __table_args__ = (UniqueConstraint('kurikulum_id', 'kode_mapel', name='unique_mapel_per_kurikulum'),)


# ========== KELAS ==========
class Kelas(Base):
    __tablename__ = 'kelas'
    
    id = Column(Integer, primary_key=True)
    kurikulum_id = Column(Integer, ForeignKey("kurikulum.id", ondelete="CASCADE"), nullable=False)  # <-- FIXED: lowercase
    
    nama_kelas = Column(String(50), nullable=False)
    tingkat = Column(String(10), nullable=False)
    jurusan = Column(String(50), nullable=True)
    wali_kelas_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relasi
    kurikulum = relationship("Kurikulum", back_populates="kelas")
    wali_kelas = relationship("User", foreign_keys=[wali_kelas_id], back_populates="kelas_diampu")
    kelas_mapel = relationship("KelasMapel", back_populates="kelas", cascade="all, delete-orphan")
    murid = relationship("User", secondary="kelas_murid", back_populates="kelas_diikuti", viewonly=True)
    raports = relationship("Raport", back_populates="kelas")


# ========== KELAS MAPEL (Pivot Kelas x Mapel) ==========
class KelasMapel(Base):
    __tablename__ = 'kelas_mapel'
    
    id = Column(Integer, primary_key=True)
    kelas_id = Column(Integer, ForeignKey("kelas.id", ondelete="CASCADE"), nullable=False)
    mapel_id = Column(Integer, ForeignKey("mata_pelajaran.id", ondelete="CASCADE"), nullable=False)
    
    # Relasi
    kelas = relationship("Kelas", back_populates="kelas_mapel")
    mapel = relationship("MataPelajaran", back_populates="kelas_mapel")
    guru_mengajar = relationship("GuruMengajar", back_populates="kelas_mapel", cascade="all, delete-orphan")
    
    __table_args__ = (UniqueConstraint('kelas_id', 'mapel_id', name='unique_kelas_mapel'),)


# ========== USER ==========
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    nama = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.murid)
    nip_nis = Column(String(20), unique=True, nullable=True)
    photo = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=date.today)
    
    jurusan = Column(String(50), nullable=True)   # untuk murid & guru
    angkatan = Column(Integer, nullable=True)
    
    # Relasi GURU
    kelas_diampu = relationship("Kelas", foreign_keys="Kelas.wali_kelas_id", back_populates="wali_kelas")
    guru_mengajar = relationship("GuruMengajar", foreign_keys="GuruMengajar.guru_id", back_populates="guru")
    
    # Relasi MURID
    kelas_diikuti = relationship("Kelas", secondary="kelas_murid", back_populates="murid")
    raports = relationship("Raport", foreign_keys="Raport.murid_id", back_populates="murid")


# ========== KELAS MURID (Pivot) ==========
class KelasMurid(Base):
    __tablename__ = 'kelas_murid'
    
    id = Column(Integer, primary_key=True)
    kelas_id = Column(Integer, ForeignKey("kelas.id", ondelete="CASCADE"), nullable=False)
    murid_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tanggal_masuk = Column(Date, default=date.today)
    
    __table_args__ = (UniqueConstraint('kelas_id', 'murid_id', name='unique_kelas_murid'),)


# ========== GURU MENGAJAR ==========
class GuruMengajar(Base):
    __tablename__ = 'guru_mengajar'
    
    id = Column(Integer, primary_key=True)
    guru_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kelas_mapel_id = Column(Integer, ForeignKey("kelas_mapel.id", ondelete="CASCADE"), nullable=False)
    
    # Relasi
    guru = relationship("User", foreign_keys=[guru_id], back_populates="guru_mengajar")
    kelas_mapel = relationship("KelasMapel", back_populates="guru_mengajar")
    raports = relationship("Raport", back_populates="guru_mengajar")
    
    __table_args__ = (UniqueConstraint('guru_id', 'kelas_mapel_id', name='unique_guru_kelas_mapel'),)


# ========== RAPORT ==========
class Raport(Base):
    __tablename__ = 'raport'
    
    id = Column(Integer, primary_key=True)
    murid_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kelas_id = Column(Integer, ForeignKey("kelas.id", ondelete="CASCADE"), nullable=False)
    kelas_mapel_id = Column(Integer, ForeignKey("kelas_mapel.id", ondelete="CASCADE"), nullable=False)
    guru_mengajar_id = Column(Integer, ForeignKey("guru_mengajar.id", ondelete="SET NULL"), nullable=True)
    
    # Nilai
    nilai_pengetahuan = Column(Float, nullable=True)
    nilai_keterampilan = Column(Float, nullable=True)
    nilai_akhir = Column(Float, nullable=True)
    predikat = Column(String(5), nullable=True)
    deskripsi = Column(Text, nullable=True)
    
    # Status
    status = Column(Enum(StatusRaport), default=StatusRaport.draft)
    tanggal_input = Column(Date, default=date.today)
    tanggal_publish = Column(Date, nullable=True)
    
    # Relasi
    murid = relationship("User", foreign_keys=[murid_id], back_populates="raports")
    kelas = relationship("Kelas", foreign_keys=[kelas_id], back_populates="raports")
    kelas_mapel = relationship("KelasMapel")
    guru_mengajar = relationship("GuruMengajar", back_populates="raports")
    
    __table_args__ = (UniqueConstraint('murid_id', 'kelas_mapel_id', name='unique_murid_kelas_mapel'),)


# ========== EKSTRAKURIKULER ==========
class Ekstrakurikuler(Base):
    __tablename__ = 'ekstrakurikuler'
    
    id = Column(Integer, primary_key=True)
    nama_ekskul = Column(String(100), nullable=False)
    # Relasi
    nilai_ekskul = relationship("NilaiEkstrakurikuler", back_populates="ekskul")


class NilaiEkstrakurikuler(Base):
    __tablename__ = 'nilai_ekstrakurikuler'
    
    id = Column(Integer, primary_key=True)
    murid_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ekskul_id = Column(Integer, ForeignKey("ekstrakurikuler.id", ondelete="CASCADE"), nullable=False)
    nilai = Column(String(20), nullable=True)
    deskripsi = Column(Text, nullable=True)
    
    # Ambil dari Kurikulum
    kurikulum_id = Column(Integer, ForeignKey("kurikulum.id"), nullable=False)
    
    # Relasi
    murid = relationship("User", foreign_keys=[murid_id])
    ekskul = relationship("Ekstrakurikuler", back_populates="nilai_ekskul")
    kurikulum = relationship("Kurikulum")
    
    __table_args__ = (UniqueConstraint('murid_id', 'ekskul_id', 'kurikulum_id', name='unique_nilai_ekskul'),)

class ResetSchedule(Base):
    __tablename__ = 'reset_schedule'

    id           = Column(Integer, primary_key=True)
    kurikulum_id = Column(Integer, ForeignKey("kurikulum.id"), nullable=False)
    tanggal_reset = Column(Date, nullable=False)
    tipe_reset       = Column(String(20), default='naik_kelas')  # ✅ tambah ini
    sudah_dijalankan = Column(Boolean, default=False)
    dijalankan_at    = Column(Date, nullable=True)
    created_at   = Column(Date, default=date.today)

    kurikulum = relationship("Kurikulum")

class Presensi(Base):
    __tablename__ = 'presensi'

    id           = Column(Integer, primary_key=True)
    murid_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kelas_id     = Column(Integer, ForeignKey("kelas.id", ondelete="CASCADE"), nullable=False)
    kurikulum_id = Column(Integer, ForeignKey("kurikulum.id", ondelete="CASCADE"), nullable=False)
    sakit        = Column(Integer, default=0)
    izin         = Column(Integer, default=0)
    alpha        = Column(Integer, default=0)

    murid     = relationship("User")
    kelas     = relationship("Kelas")
    kurikulum = relationship("Kurikulum")

    __table_args__ = (
        UniqueConstraint('murid_id', 'kelas_id', 'kurikulum_id', name='unique_presensi'),
    )