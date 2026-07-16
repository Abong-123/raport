#----------------------------------- main.py -----------------------------------#
from fastapi import FastAPI, HTTPException, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime
from datetime import date, timedelta
import os
from dotenv import load_dotenv
load_dotenv()
import cloudinary
import cloudinary.uploader
from cloudinary_config import cloudinary
import shutil
from xhtml2pdf import pisa
import io

#------------------------------- import models and schemas -----------------------------------#
import models
import schemas
from database import SessionLocal, engine, get_db, Base
from datetime import datetime, date
from typing import List
from security import hash_password, verify_password
from apscheduler.schedulers.background import BackgroundScheduler
from database import SessionLocal

def cek_reset_otomatis():
    db = SessionLocal()
    try:
        hari_ini = date.today()
        schedules = db.query(models.ResetSchedule).filter(
            models.ResetSchedule.tanggal_reset <= hari_ini,
            models.ResetSchedule.sudah_dijalankan == False
        ).all()

        for s in schedules:
            if s.tipe_reset == "ganti_semester":
                jalankan_ganti_semester(s.kurikulum_id, db)
            else:
                jalankan_reset(s.kurikulum_id, db)
            s.sudah_dijalankan = True
            s.dijalankan_at    = date.today()  # ✅ pastikan ini ada

        db.commit()
        if schedules:
            print(f"[SCHEDULER] {len(schedules)} reset dijalankan: {date.today()}")
    finally:
        db.close()


def jalankan_ganti_semester(kurikulum_id: int, db: Session):
    """
    Ganti semester: murid & guru TETAP di kelas yang sama.
    Hanya raport di-reset ke draft supaya guru bisa input nilai baru.
    Kurikulum aktif berganti ke yang baru (semester berikutnya).
    """
    # Reset semua raport semester ini ke draft
    kelas_ids = [
        k.id for k in db.query(models.Kelas).filter(
            models.Kelas.kurikulum_id == kurikulum_id
        ).all()
    ]

    if kelas_ids:
        db.query(models.Raport).filter(
            models.Raport.kelas_id.in_(kelas_ids),
            models.Raport.status != models.StatusRaport.published
        ).delete(synchronize_session=False)

    # Nonaktifkan kurikulum lama
    kurikulum_lama = db.query(models.Kurikulum).get(kurikulum_id)
    if kurikulum_lama:
        kurikulum_lama.is_active = False

    db.commit()

scheduler = BackgroundScheduler()
scheduler.add_job(cek_reset_otomatis, "cron", hour=1, minute=0)  # jalan tiap jam 1 pagi
scheduler.start()

#------------------------------- settings -----------------------------------#
Base.metadata.create_all(bind=engine, checkfirst=True)
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "SECRET_YANG_RAHASIA_BANGET"),
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------------- Jinja2 -------------------------------
def get_current_user(request: Request):
    return{
        "id": request.session.get("user_id"),
        "nama": request.session.get("user_name"),
        "role": request.session.get("user_role")
    } if "user_id" in request.session else None

def require_role(request: Request, *roles: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user["role"] not in roles:
        return RedirectResponse(url="/dashboard", status_code=303)
    return None


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.email == email
    ).first()
    
    if not user or not verify_password(user.password, password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "email atau password salah"}
        )
    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Akun tidak aktif, hubungi admin"}
        )
    request.session["user_id"] = user.id
    request.session["user_name"] = user.nama
    request.session["user_role"] = user.role.value
    
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/dashboard")
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    role_map = {
        "admin": "/dashboard/admin",
        "guru":  "/dashboard/guru",
        "murid": "/dashboard/murid",
    }
    return RedirectResponse(url=role_map[user["role"]], status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# ========================= LANDING PAGE =========================
@app.get("/", response_class=HTMLResponse)
def landing_page(request: Request):
    # Kalau sudah login, redirect ke dashboard
    if get_current_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("landing.html", {"request": request})

# ========================== ADMIN ====================================
@app.get("/dashboard/admin", response_class=HTMLResponse)
def dashboard_admin(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard:
        return guard
    
    guru_list = db.query(models.User).filter(
        models.User.role == models.UserRole.guru
    ).order_by(models.User.created_at.desc()).all()

    murid_list = db.query(models.User).filter(
        models.User.role == models.UserRole.murid
    ).order_by(models.User.created_at.desc()).all()

    return templates.TemplateResponse("dashboard_admin.html", {
        "request":    request,
        "nama":       request.session["user_name"],
        "guru_list":  guru_list,
        "murid_list": murid_list,
        "active_tab": request.query_params.get("tab", "guru"),
    })

@app.post("/dashboard/admin/create-user")
def admin_create_user(
    request:  Request,
    nama:     str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
    role:     str = Form(...),
    nip_nis:  str = Form(None),
    jurusan:  str = Form(None),   # ✅ tambah
    angkatan: int = Form(None),   # ✅ tambah
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    if db.query(models.User).filter(models.User.email == email).first():
        return RedirectResponse(
            url=f"/dashboard/admin?tab={role}&error=Email+sudah+terdaftar",
            status_code=303
        )

    if nip_nis and db.query(models.User).filter(models.User.nip_nis == nip_nis).first():
        return RedirectResponse(
            url=f"/dashboard/admin?tab={role}&error=NIP/NIS+sudah+terdaftar",
            status_code=303
        )

    new_user = models.User(
        nama=nama,
        email=email,
        password=hash_password(password),
        role=models.UserRole[role],
        nip_nis=nip_nis or None,
        jurusan=jurusan or None,    # ✅
        angkatan=angkatan or None,  # ✅
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url=f"/dashboard/admin?tab={role}", status_code=303)

@app.post("/dashboard/admin/toogle-user/{user_id}")
def admin_toogle_user(
    request: Request,
    user_id: int,
    tab:     str = Form("guru"),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard:
        return guard

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse(url="/dashboard/admin?tab={tab}", status_code=303)

@app.post("/dashboard/admin/delete-user/{user_id}")
def admin_delete_user(
    request: Request,
    user_id: int,
    tab:     str = Form("guru"),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse(url=f"/dashboard/admin?tab={tab}", status_code=303)

JURUSAN_LIST = [
    "Teknik Komputer & Jaringan",
    "Rekayasa Perangkat Lunak",
    "Teknik Kendaraan Ringan",
    "Akutansi",
    "Administrasi Perkantoran",
    "pemasaran",
]

KATEGORI_MAPEL_LIST = [
    "Wajib Nasional",
    "Muatan Lokal",
    "Produktif Teknik Komputer & Jaringan",
    "Produktif Rekayasa Perangkat Lunak",
    "Produktif Teknik Otomotif",
    "Produktif Akuntansi",
    "Produktif Administrasi Perkantoran",
]

@app.get("/dashboard/admin/kelas", response_class=HTMLResponse)
def halaman_kelas(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard
    
    kurikulum_list = db.query(models.Kurikulum).order_by(
        models.Kurikulum.tahun_ajaran.desc()
    ).all()
    
    kurikulum_aktif = db.query(models.Kurikulum).filter(
        models.Kurikulum.is_active == True
    ).first()
    
    kurikulum_id = request.query_params.get("kurikulum_id")
    if kurikulum_id:
        try:
            kurikulum_id = int(kurikulum_id)
            kurikulum_dipilih = db.query(models.Kurikulum).get(kurikulum_id)
            if not kurikulum_dipilih:  # id valid tapi tidak ada di DB
                kurikulum_dipilih = kurikulum_aktif
                kurikulum_id = kurikulum_dipilih.id if kurikulum_dipilih else None
        except ValueError:
            # nilai bukan integer (misal literal "{kurikulum_id}") — fallback ke aktif
            kurikulum_dipilih = kurikulum_aktif
            kurikulum_id = kurikulum_dipilih.id if kurikulum_dipilih else None
    else:
        kurikulum_dipilih = kurikulum_aktif
        kurikulum_id = kurikulum_dipilih.id if kurikulum_dipilih else None
    
    mapel_list = []
    kelas_list = []
    if kurikulum_id:
        mapel_list = db.query(models.MataPelajaran).filter(
            models.MataPelajaran.kurikulum_id == kurikulum_id,
            models.MataPelajaran.is_active == True
        ).order_by(models.MataPelajaran.kode_mapel).all()
        
        kelas_list = db.query(models.Kelas).filter(
            models.Kelas.kurikulum_id == kurikulum_id,
        ).options(
            joinedload(models.Kelas.wali_kelas),
            joinedload(models.Kelas.kelas_mapel).joinedload(models.KelasMapel.mapel),
        ).order_by(models.Kelas.tingkat, models.Kelas.jurusan, models.Kelas.nama_kelas).all()
    
    guru_list = db.query(models.User).filter(
        models.User.role == models.UserRole.guru,
        models.User.is_active == True
    ).order_by(models.User.nama).all()
    
    murid_list = db.query(models.User).filter(
        models.User.role == models.UserRole.murid,
        models.User.is_active == True
    ).order_by(models.User.nama).all()
    
    active_tab = request.query_params.get("tab", "kurikulum")
    
    return templates.TemplateResponse("dashboard_admin_kelas.html", {
        "request":  request,
        "nama":     request.session["user_name"],
        "kurikulum_list":    kurikulum_list,
        "kurikulum_dipilih": kurikulum_dipilih,
        "kurikulum_id":      kurikulum_id,
        "mapel_list":        mapel_list,
        "kelas_list":        kelas_list,
        "guru_list":         guru_list,
        "murid_list":        murid_list,
        "jurusan_list":      JURUSAN_LIST,
        "kategori_mapel_list": KATEGORI_MAPEL_LIST,
        "active_tab":        active_tab,
        "error":             request.query_params.get("error"),
        "success":           request.query_params.get("success"),
    })

@app.post("/dashboard/admin/kelas/kurikulum/create")
def create_kurikulum(
    request:        Request,
    nama_kurikulum: str  = Form(...),
    tahun_ajaran:   str  = Form(...),
    semester:       str  = Form(...),
    deskripsi:      str  = Form(None),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard
    
    existing = db.query(models.Kurikulum).filter(
        models.Kurikulum.tahun_ajaran == tahun_ajaran,
        models.Kurikulum.semester == semester
    ).first()
    if existing:
        return RedirectResponse(
            url="/dashboard/admin/kelas?tab=kurikulum&error=Kurikulum+tahun+ini+sudah+ada", status_code=303
        )
    
    k = models.Kurikulum(
        nama_kurikulum=nama_kurikulum,
        tahun_ajaran=tahun_ajaran,
        semester=semester,
        deskripsi=deskripsi or None,
        is_active=True,
    )
    db.add(k)
    db.commit()
    return RedirectResponse(
        url="/dashboard/admin/kelas?tab=kurikulum&success=Kurikulum+berhasil+dibuat", status_code=303
    )

@app.post("/dashboard/admin/kelas/kurikulum/set-aktif/{kurikulum_id}")
def set_kurikuluma_aktif(request: Request, kurikulum_id: int, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard
    
    db.query(models.Kurikulum).update({"is_active": False})
    k = db.query(models.Kurikulum).get(kurikulum_id)
    if k:
        k.is_active = True
    db.commit()
    return RedirectResponse(url="/dashboard/admin/kelas?tab=kurikulum", status_code=303)

@app.post("/dashboard/admin/kelas/mapel/create")
def create_mapel(
    request: Request,
    kurikulum_id: int = Form(...),
    kode_mapel:   str = Form(...),
    nama_mapel:   str = Form(...),
    kategori:     str = Form(None),
    kkm:          int = Form(75),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard
    
    existing = db.query(models.MataPelajaran).filter(
        models.MataPelajaran.kurikulum_id == kurikulum_id,
        models.MataPelajaran.kode_mapel == kode_mapel.upper()
    ).first()
    if existing:
        return RedirectResponse(
            url="/dashboard/admin/kelas?tab=mapel&kurikulum_id={kurikulum_id}&error=Kode+mapel+sudah+ada", status_code=303
        )
    
    mapel = models.MataPelajaran(
        kurikulum_id=kurikulum_id,
        kode_mapel=kode_mapel.upper(),
        nama_mapel=nama_mapel,
        kategori=kategori or None,
        kkm=kkm,
    )
    db.add(mapel)
    db.commit()
    return RedirectResponse(
        url="/dashboard/admin/kelas?tab=mapel&kurikulum_id={kurikulum_id}&success=Mapel+berhasil+ditambahkan", status_code=303
    )

@app.post("/dashboard/admin/kelas/mapel/delete/{mapel_id}")
def delete_mapel(
    request: Request,
    mapel_id: int,
    kurikulum_id: int = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    mapel = db.query(models.MataPelajaran).filter(
        models.MataPelajaran.id == mapel_id
    ).first()

    if not mapel:
        return RedirectResponse(
            url=f"/dashboard/admin/kelas?tab=mapel&kurikulum_id={kurikulum_id}&error=Mapel+tidak+ditemukan",
            status_code=303
        )

    # Cek apakah mapel ini sudah punya raport — kalau ada, tidak boleh dihapus
    punya_raport = (
        db.query(models.Raport)
        .join(models.KelasMapel)
        .filter(models.KelasMapel.mapel_id == mapel_id)
        .first()
    )
    if punya_raport:
        return RedirectResponse(
            url=f"/dashboard/admin/kelas?tab=mapel&kurikulum_id={kurikulum_id}&error=Mapel+tidak+bisa+dihapus+karena+sudah+ada+data+raport",
            status_code=303
        )

    # Hapus kelas_mapel dulu secara eksplisit, baru hapus mapel
    db.query(models.KelasMapel).filter(
        models.KelasMapel.mapel_id == mapel_id
    ).delete(synchronize_session=False)

    db.delete(mapel)
    db.commit()

    return RedirectResponse(
        url=f"/dashboard/admin/kelas?tab=mapel&kurikulum_id={kurikulum_id}&success=Mapel+berhasil+dihapus",
        status_code=303
    )

@app.post("/dashboard/admin/kelas/kelas/create")
def create_kelas(
    request:      Request,
    kurikulum_id: int = Form(...),
    tingkat:      str = Form(...),
    jurusan:      str = Form(...),
    jurusan_lain: str = Form(None),
    nama_kelas:   str = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard
    
    jurusan_final = jurusan_final.strip() if jurusan == "Lainnya" and jurusan_lain else jurusan
    
    kelas = models.Kelas(
        kurikulum_id=kurikulum_id,
        tingkat=tingkat,
        jurusan=jurusan_final,
        nama_kelas=nama_kelas.upper(),
    )
    db.add(kelas)
    db.commit()
    return RedirectResponse(
        url="/dashboard/admin/kelas?tab=kelas&kurikulum_id={kurikulum_id}succss=Kelas+berhasil+dibuat",
        status_code=303
    )

@app.post("/dashboard/admin/kelas/kelas/delete/{kelas_id}")
def delete_kelas(request: Request, kelas_id: int, kurikulum_id: int = Form(...), db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    kelas = db.query(models.Kelas).get(kelas_id)
    if kelas:
        db.delete(kelas)
        db.commit()
    return RedirectResponse(url=f"/dashboard/admin/kelas?tab=kelas&kurikulum_id={kurikulum_id}", status_code=303)

@app.post("/dashboard/admin/kelas/assign-mapel/{kelas_id}")
def assign_mapel_ke_kelas(
    request:   Request,
    kelas_id:  int,
    mapel_ids: List[int] = Form(default=[]),
    kurikulum_id: int = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard
    
    existing = db.query(models.KelasMapel).filter(
        models.KelasMapel.kelas_id == kelas_id
    ).all()
    for km in existing:
        punya_raport = db.query(models.Raport).filter(
            models.Raport.kelas_mapel_id == km.id
        ).first()
        if not punya_raport:
            db.delete(km)
    db.flush()
    
    existing_mapel_ids = {
        km.mapel_id for km in db.query(models.KelasMapel).filter(
            models.KelasMapel.kelas_id == kelas_id
        ).all()
    }
    for mapel_id in mapel_ids:
        if mapel_id not in existing_mapel_ids:
            db.add(models.KelasMapel(kelas_id=kelas_id, mapel_id=mapel_id))
    
    db.commit()
    return RedirectResponse(
        url="/dashboard/admin/kelas?tab=assign&kurikulum_id={kurikulum_id}&success=Mapel+berhasil+diassign", status_code=303
    )

@app.post("/dashboard/admin/kelas/assign-wali/{kelas_id}")
def assign_wali_kelas(
    request:      Request,
    kelas_id:     int,
    wali_kelas_id: int = Form(...),
    kurikulum_id: int  = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    kelas = db.query(models.Kelas).get(kelas_id)
    if kelas:
        kelas.wali_kelas_id = wali_kelas_id if wali_kelas_id != 0 else None
        db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin/kelas?tab=assign&kurikulum_id={kurikulum_id}",
        status_code=303
    )

@app.post("/dashboard/admin/kelas/assign-guru/{kelas_mapel_id}")
def assign_guru_ke_mapel(
    request:        Request,
    kelas_mapel_id: int,
    guru_id:        int = Form(...),
    kurikulum_id:   int = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    existing = db.query(models.GuruMengajar).filter(
        models.GuruMengajar.kelas_mapel_id == kelas_mapel_id
    ).first()

    if existing:
        if guru_id == 0:
            db.delete(existing)
        else:
            existing.guru_id = guru_id
    elif guru_id != 0:
        db.add(models.GuruMengajar(guru_id=guru_id, kelas_mapel_id=kelas_mapel_id))

    db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin/kelas?tab=assign&kurikulum_id={kurikulum_id}",
        status_code=303
    )

@app.post("/dashboard/admin/kelas/assign-murid/{kelas_id}")
def assign_murid_ke_kelas(
    request:      Request,
    kelas_id:     int,
    murid_ids:    List[int] = Form(default=[]),
    kurikulum_id: int       = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    # Hapus murid lama yang tidak dipilih lagi
    db.query(models.KelasMurid).filter(
        models.KelasMurid.kelas_id == kelas_id
    ).delete()
    db.flush()

    for murid_id in murid_ids:
        db.add(models.KelasMurid(kelas_id=kelas_id, murid_id=murid_id))

    db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin/kelas?tab=assign&kurikulum_id={kurikulum_id}&success=Murid+berhasil+diassign",
        status_code=303
    )


# ===================== ADMIN: PUBLISH NILAI =====================

@app.get("/dashboard/admin/nilai", response_class=HTMLResponse)
def admin_nilai(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    # Ambil semua kelas_mapel yang punya raport submitted
    submitted = (
        db.query(models.KelasMapel)
        .join(models.Raport)
        .filter(models.Raport.status == models.StatusRaport.submitted)
        .options(
            joinedload(models.KelasMapel.kelas)
                .joinedload(models.Kelas.kurikulum),
            joinedload(models.KelasMapel.mapel),
            joinedload(models.KelasMapel.guru_mengajar)
                .joinedload(models.GuruMengajar.guru),
        )
        .distinct()
        .all()
    )

    # Reset schedule
    schedules = db.query(models.ResetSchedule).filter(
        models.ResetSchedule.sudah_dijalankan == False
    ).all()

    kurikulum_list = db.query(models.Kurikulum).filter(
        models.Kurikulum.is_active == True
    ).all()
    
    schedules_done = db.query(models.ResetSchedule).filter(
        models.ResetSchedule.sudah_dijalankan == True
    ).order_by(models.ResetSchedule.dijalankan_at.desc()).limit(20).all()

    return templates.TemplateResponse("dashboard_admin_nilai.html", {
        "request":        request,
        "nama":           request.session["user_name"],
        "submitted":      submitted,
        "schedules":      schedules,
        "kurikulum_list": kurikulum_list,
        "now": datetime.today(),
        "schedules_done": schedules_done,
    })


@app.post("/dashboard/admin/nilai/publish/{kelas_mapel_id}")
def admin_publish_nilai(
    request:        Request,
    kelas_mapel_id: int,
    db:             Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    db.query(models.Raport).filter(
        models.Raport.kelas_mapel_id == kelas_mapel_id,
        models.Raport.status == models.StatusRaport.submitted
    ).update({
        "status": models.StatusRaport.published,
        "tanggal_publish": date.today()
    })
    db.commit()
    return RedirectResponse(url="/dashboard/admin/nilai", status_code=303)


# ===================== ADMIN: SET TANGGAL RESET =====================

@app.post("/dashboard/admin/nilai/set-reset")
def set_reset_schedule(
    request:       Request,
    kurikulum_id:  int  = Form(...),
    tanggal_reset: date = Form(...),
    tipe_reset:    str  = Form("naik_kelas"),  # ✅ tambah ini
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    db.query(models.ResetSchedule).filter(
        models.ResetSchedule.kurikulum_id == kurikulum_id,
        models.ResetSchedule.sudah_dijalankan == False
    ).delete()

    schedule = models.ResetSchedule(
        kurikulum_id=kurikulum_id,
        tanggal_reset=tanggal_reset,
        tipe_reset=tipe_reset,  # ✅
    )
    db.add(schedule)
    db.commit()
    return RedirectResponse(url="/dashboard/admin/nilai?success=Jadwal+reset+disimpan", status_code=303)


# ===================== PROSES RESET OTOMATIS =====================
def jalankan_reset(kurikulum_id: int, db: Session):
    kurikulum_baru = db.query(models.Kurikulum).filter(
        models.Kurikulum.is_active == True
    ).first()
    if not kurikulum_baru:
        return

    kelas_lama = db.query(models.Kelas).filter(
        models.Kelas.kurikulum_id == kurikulum_id
    ).options(
        joinedload(models.Kelas.murid),
        joinedload(models.Kelas.kelas_mapel)
    ).all()

    for kelas in kelas_lama:
        tingkat = int(kelas.tingkat)

        for murid in kelas.murid:

            # Cek apakah murid ini punya nilai E di mapel apapun di kelas ini
            punya_nilai_e = db.query(models.Raport).filter(
                models.Raport.murid_id   == murid.id,
                models.Raport.kelas_id   == kelas.id,
                models.Raport.predikat   == "E",
                models.Raport.status     == models.StatusRaport.published
            ).first()

            if tingkat == 12:
                if punya_nilai_e:
                    # Kelas 12 nilai E → tidak lulus, nonaktifkan saja
                    murid.is_active = False
                else:
                    # Kelas 12 lulus → hapus dari sistem
                    db.delete(murid)
                continue

            # Kelas 10 & 11
            if punya_nilai_e:
                # Tinggal kelas → cari kelas yang SAMA di kurikulum BARU
                # misal 11 RPL-A → tetap di 11 RPL-A kurikulum baru
                kelas_tujuan = db.query(models.Kelas).filter(
                    models.Kelas.kurikulum_id == kurikulum_baru.id,
                    models.Kelas.tingkat      == str(tingkat),   # tingkat SAMA
                    models.Kelas.jurusan      == kelas.jurusan,
                    models.Kelas.nama_kelas   == kelas.nama_kelas,
                ).first()
            else:
                # Naik kelas → cari kelas tingkat+1 di kurikulum baru
                kelas_tujuan = db.query(models.Kelas).filter(
                    models.Kelas.kurikulum_id == kurikulum_baru.id,
                    models.Kelas.tingkat      == str(tingkat + 1),  # naik tingkat
                    models.Kelas.jurusan      == kelas.jurusan,
                    models.Kelas.nama_kelas   == kelas.nama_kelas,
                ).first()

            if kelas_tujuan:
                sudah_ada = db.query(models.KelasMurid).filter(
                    models.KelasMurid.kelas_id == kelas_tujuan.id,
                    models.KelasMurid.murid_id == murid.id
                ).first()
                if not sudah_ada:
                    db.add(models.KelasMurid(
                        kelas_id=kelas_tujuan.id,
                        murid_id=murid.id
                    ))
            else:
                # Kelas tujuan belum dibuat admin → catat di log, skip dulu
                print(f"[RESET] Kelas tujuan tidak ditemukan untuk murid {murid.nama} "
                      f"({'tinggal' if punya_nilai_e else 'naik'} ke tingkat "
                      f"{'sama' if punya_nilai_e else tingkat+1} {kelas.jurusan} {kelas.nama_kelas})")

        # Bersihkan assign lama dari kelas ini
        db.query(models.KelasMurid).filter(
            models.KelasMurid.kelas_id == kelas.id
        ).delete(synchronize_session=False)

        db.query(models.GuruMengajar).filter(
            models.GuruMengajar.kelas_mapel_id.in_(
                [km.id for km in kelas.kelas_mapel]
            )
        ).delete(synchronize_session=False)

        kelas.wali_kelas_id = None

    db.commit()


@app.get("/dashboard/admin/cek-reset")
def cek_reset(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    hari_ini = date.today()
    schedules = db.query(models.ResetSchedule).filter(
        models.ResetSchedule.tanggal_reset <= hari_ini,
        models.ResetSchedule.sudah_dijalankan == False
    ).all()

    for s in schedules:
        jalankan_reset(s.kurikulum_id, db)
        s.sudah_dijalankan = True

    db.commit()
    return {"reset_dijalankan": len(schedules)}

@app.post("/dashboard/admin/nilai/hapus-reset/{schedule_id}")
def hapus_reset_schedule(
    request:     Request,
    schedule_id: int,
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    s = db.query(models.ResetSchedule).get(schedule_id)
    if s and not s.sudah_dijalankan:
        db.delete(s)
        db.commit()
    return RedirectResponse(url="/dashboard/admin/nilai", status_code=303)

@app.post("/dashboard/admin/nilai/jalankan-reset/{schedule_id}")
def jalankan_reset_manual(
    request:     Request,
    schedule_id: int,
    db:          Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    s = db.query(models.ResetSchedule).get(schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule tidak ditemukan")

    if s.sudah_dijalankan:
        return RedirectResponse(
            url="/dashboard/admin/nilai?error=Reset+sudah+pernah+dijalankan",
            status_code=303
        )

    if s.tipe_reset == "ganti_semester":
        jalankan_ganti_semester(s.kurikulum_id, db)
    else:
        jalankan_reset(s.kurikulum_id, db)

    s.sudah_dijalankan = True
    s.dijalankan_at    = date.today()
    db.commit()

    return RedirectResponse(
        url="/dashboard/admin/nilai?success=Reset+berhasil+dijalankan",
        status_code=303
    )
# ===================== GURU: PRESENSI & EKSKUL =====================

@app.get("/dashboard/guru/presensi/{kelas_id}", response_class=HTMLResponse)
def guru_halaman_presensi(
    request:  Request,
    kelas_id: int,
    db:       Session = Depends(get_db)
):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]

    # Pastikan guru ini adalah wali kelas dari kelas tersebut
    kelas = db.query(models.Kelas).filter(
        models.Kelas.id == kelas_id,
        models.Kelas.wali_kelas_id == user_id
    ).options(
        joinedload(models.Kelas.murid),
        joinedload(models.Kelas.kurikulum),
    ).first()

    if not kelas:
        raise HTTPException(status_code=403, detail="Kamu bukan wali kelas ini")

    kurikulum = kelas.kurikulum
    murid_list = kelas.murid

    # Ambil presensi yang sudah ada
    presensi_existing = {
        p.murid_id: p
        for p in db.query(models.Presensi).filter(
            models.Presensi.kelas_id     == kelas_id,
            models.Presensi.kurikulum_id == kurikulum.id
        ).all()
    }

    # Ambil semua ekskul
    ekskul_list = db.query(models.Ekstrakurikuler).all()

    # Ambil nilai ekskul yang sudah ada
    nilai_ekskul_existing = {}
    for m in murid_list:
        nilai_ekskul_existing[m.id] = {
            ne.ekskul_id: ne
            for ne in db.query(models.NilaiEkstrakurikuler).filter(
                models.NilaiEkstrakurikuler.murid_id     == m.id,
                models.NilaiEkstrakurikuler.kurikulum_id == kurikulum.id
            ).all()
        }

    return templates.TemplateResponse("guru_presensi.html", {
        "request":              request,
        "nama":                 request.session["user_name"],
        "kelas":                kelas,
        "kurikulum":            kurikulum,
        "murid_list":           murid_list,
        "presensi_existing":    presensi_existing,
        "ekskul_list":          ekskul_list,
        "nilai_ekskul_existing": nilai_ekskul_existing,
        "saved":                request.query_params.get("saved"),
    })


@app.post("/dashboard/guru/presensi/{kelas_id}/simpan")
async def guru_simpan_presensi(
    request:  Request,
    kelas_id: int,
    db:       Session = Depends(get_db)
):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]
    kelas = db.query(models.Kelas).filter(
        models.Kelas.id            == kelas_id,
        models.Kelas.wali_kelas_id == user_id
    ).options(joinedload(models.Kelas.murid)).first()

    if not kelas:
        raise HTTPException(status_code=403)

    form         = await request.form()
    kurikulum_id = kelas.kurikulum_id

    for murid in kelas.murid:
        mid   = murid.id
        sakit = int(form.get(f"sakit_{mid}", 0) or 0)
        izin  = int(form.get(f"izin_{mid}",  0) or 0)
        alpha = int(form.get(f"alpha_{mid}", 0) or 0)

        p = db.query(models.Presensi).filter(
            models.Presensi.murid_id     == mid,
            models.Presensi.kelas_id     == kelas_id,
            models.Presensi.kurikulum_id == kurikulum_id
        ).first()

        if p:
            p.sakit = sakit
            p.izin  = izin
            p.alpha = alpha
        else:
            db.add(models.Presensi(
                murid_id=mid, kelas_id=kelas_id,
                kurikulum_id=kurikulum_id,
                sakit=sakit, izin=izin, alpha=alpha
            ))

    db.commit()
    # ✅ redirect ke dashboard dengan notif
    return RedirectResponse(
        url="/dashboard/guru?notif=presensi_tersimpan",
        status_code=303
    )


@app.post("/dashboard/guru/presensi/{kelas_id}/simpan-ekskul")
async def guru_simpan_ekskul(
    request:  Request,
    kelas_id: int,
    db:       Session = Depends(get_db)
):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]
    kelas = db.query(models.Kelas).filter(
        models.Kelas.id            == kelas_id,
        models.Kelas.wali_kelas_id == user_id
    ).options(joinedload(models.Kelas.murid)).first()

    if not kelas:
        raise HTTPException(status_code=403)

    form         = await request.form()
    kurikulum_id = kelas.kurikulum_id
    ekskul_list  = db.query(models.Ekstrakurikuler).all()

    for murid in kelas.murid:
        mid = murid.id
        ekskul_dipilih = []
        for ekskul in ekskul_list:
            if form.get(f"ekskul_ikut_{mid}_{ekskul.id}"):
                ekskul_dipilih.append(ekskul.id)

        if len(ekskul_dipilih) > 2:
            ekskul_dipilih = ekskul_dipilih[:2]

        db.query(models.NilaiEkstrakurikuler).filter(
            models.NilaiEkstrakurikuler.murid_id     == mid,
            models.NilaiEkstrakurikuler.kurikulum_id == kurikulum_id
        ).delete(synchronize_session=False)

        for eid in ekskul_dipilih:
            nilai = form.get(f"ekskul_{mid}_{eid}", "").strip()
            desk  = form.get(f"ekskul_desk_{mid}_{eid}", "").strip()
            db.add(models.NilaiEkstrakurikuler(
                murid_id=mid, ekskul_id=eid,
                kurikulum_id=kurikulum_id,
                nilai=nilai or None,
                deskripsi=desk or None
            ))

    db.commit()
    # ✅ redirect ke dashboard dengan notif
    return RedirectResponse(
        url="/dashboard/guru?notif=ekskul_tersimpan",
        status_code=303
    )


# ===================== ADMIN: KELOLA EKSKUL =====================
@app.post("/dashboard/admin/ekskul/create")
def admin_create_ekskul(
    request:    Request,
    nama_ekskul: str = Form(...),
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    existing = db.query(models.Ekstrakurikuler).filter(
        models.Ekstrakurikuler.nama_ekskul == nama_ekskul
    ).first()
    if not existing:
        db.add(models.Ekstrakurikuler(nama_ekskul=nama_ekskul))
        db.commit()
    return RedirectResponse(url="/dashboard/admin/ekskul", status_code=303)


@app.get("/dashboard/admin/ekskul", response_class=HTMLResponse)
def admin_ekskul(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    ekskul_list = db.query(models.Ekstrakurikuler).all()
    return templates.TemplateResponse("dashboard_admin_ekskul.html", {
        "request":     request,
        "nama":        request.session["user_name"],
        "ekskul_list": ekskul_list,
    })


@app.post("/dashboard/admin/ekskul/delete/{ekskul_id}")
def admin_delete_ekskul(
    request:   Request,
    ekskul_id: int,
    db: Session = Depends(get_db)
):
    guard = require_role(request, "admin")
    if guard: return guard

    e = db.query(models.Ekstrakurikuler).get(ekskul_id)
    if e:
        db.delete(e)
        db.commit()
    return RedirectResponse(url="/dashboard/admin/ekskul", status_code=303)


@app.get("/dashboard/admin/rekap-kelas", response_class=HTMLResponse)
def admin_rekap_kelas(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    kurikulum_aktif = db.query(models.Kurikulum).filter(
        models.Kurikulum.is_active == True
    ).first()

    kurikulum_id = request.query_params.get("kurikulum_id")
    if kurikulum_id:
        kurikulum_id      = int(kurikulum_id)
        kurikulum_dipilih = db.query(models.Kurikulum).get(kurikulum_id)
    else:
        kurikulum_dipilih = kurikulum_aktif
        kurikulum_id      = kurikulum_dipilih.id if kurikulum_dipilih else None

    kelas_list    = []
    kurikulum_list = db.query(models.Kurikulum).order_by(
        models.Kurikulum.tahun_ajaran.desc()
    ).all()

    if kurikulum_id:
        kelas_list = db.query(models.Kelas).filter(
            models.Kelas.kurikulum_id == kurikulum_id
        ).options(
            joinedload(models.Kelas.wali_kelas),
            joinedload(models.Kelas.murid),
            joinedload(models.Kelas.kelas_mapel)
                .joinedload(models.KelasMapel.mapel),
            joinedload(models.Kelas.kelas_mapel)
                .joinedload(models.KelasMapel.guru_mengajar)
                .joinedload(models.GuruMengajar.guru),
        ).order_by(
            models.Kelas.tingkat,
            models.Kelas.jurusan,
            models.Kelas.nama_kelas
        ).all()

    return templates.TemplateResponse("dashboard_admin_rekap_kelas.html", {
        "request":          request,
        "nama":             request.session["user_name"],
        "kelas_list":       kelas_list,
        "kurikulum_list":   kurikulum_list,
        "kurikulum_dipilih": kurikulum_dipilih,
        "kurikulum_id":     kurikulum_id,
    })


@app.get("/dashboard/admin/rekap-raport", response_class=HTMLResponse)
def admin_rekap_raport(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "admin")
    if guard: return guard

    kurikulum_id = request.query_params.get("kurikulum_id")
    kelas_id     = request.query_params.get("kelas_id")

    kurikulum_list = db.query(models.Kurikulum).order_by(
        models.Kurikulum.tahun_ajaran.desc()
    ).all()

    kurikulum_dipilih = None
    kelas_list        = []
    kelas_dipilih     = None
    rekap             = []

    if kurikulum_id:
        kurikulum_id      = int(kurikulum_id)
        kurikulum_dipilih = db.query(models.Kurikulum).get(kurikulum_id)
        kelas_list = db.query(models.Kelas).filter(
            models.Kelas.kurikulum_id == kurikulum_id
        ).order_by(
            models.Kelas.tingkat,
            models.Kelas.jurusan,
            models.Kelas.nama_kelas
        ).all()

    if kelas_id:
        kelas_id      = int(kelas_id)
        kelas_dipilih = db.query(models.Kelas).get(kelas_id)
        murid_list    = kelas_dipilih.murid if kelas_dipilih else []

        for murid in murid_list:
            raports = db.query(models.Raport).filter(
                models.Raport.murid_id == murid.id,
                models.Raport.kelas_id == kelas_id,
            ).options(
                joinedload(models.Raport.kelas_mapel)
                    .joinedload(models.KelasMapel.mapel)
            ).all()

            presensi = db.query(models.Presensi).filter(
                models.Presensi.murid_id == murid.id,
                models.Presensi.kelas_id == kelas_id,
            ).first()

            nilai_ekskul = db.query(models.NilaiEkstrakurikuler).filter(
                models.NilaiEkstrakurikuler.murid_id     == murid.id,
                models.NilaiEkstrakurikuler.kurikulum_id == kurikulum_id,
            ).options(
                joinedload(models.NilaiEkstrakurikuler.ekskul)
            ).all()

            nilai_list  = [r.nilai_akhir for r in raports if r.nilai_akhir]
            rata        = round(sum(nilai_list) / len(nilai_list), 1) if nilai_list else 0
            jumlah_e    = sum(1 for r in raports if r.predikat == "E")
            ada_draft   = any(r.status.value == "draft" for r in raports)
            ada_submit  = any(r.status.value == "submitted" for r in raports)
            semua_pub   = all(r.status.value == "published" for r in raports) and len(raports) > 0

            rekap.append({
                "murid":       murid,
                "raports":     raports,
                "presensi":    presensi,
                "nilai_ekskul": nilai_ekskul,
                "rata":        rata,
                "jumlah_e":    jumlah_e,
                "ada_draft":   ada_draft,
                "ada_submit":  ada_submit,
                "semua_pub":   semua_pub,
                "naik":        jumlah_e == 0 and semua_pub,
            })

    return templates.TemplateResponse("dashboard_admin_rekap_raport.html", {
        "request":          request,
        "nama":             request.session["user_name"],
        "kurikulum_list":   kurikulum_list,
        "kurikulum_dipilih": kurikulum_dipilih,
        "kurikulum_id":     kurikulum_id,
        "kelas_list":       kelas_list,
        "kelas_dipilih":    kelas_dipilih,
        "kelas_id":         kelas_id,
        "rekap":            rekap,
    })

# ========================== GURU ====================================
@app.get("/dashboard/guru", response_class=HTMLResponse)
def dashboard_guru(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]

    mengajar = (
        db.query(models.GuruMengajar)
        .filter(models.GuruMengajar.guru_id == user_id)
        .options(
            joinedload(models.GuruMengajar.kelas_mapel)
                .joinedload(models.KelasMapel.kelas)
                .joinedload(models.Kelas.kurikulum),
            joinedload(models.GuruMengajar.kelas_mapel)
                .joinedload(models.KelasMapel.mapel),
            joinedload(models.GuruMengajar.raports),
        )
        .all()
    )

    # Cari kelas yang guru ini jadi wali kelas
    wali_kelas_list = db.query(models.Kelas).filter(
        models.Kelas.wali_kelas_id == user_id
    ).options(
        joinedload(models.Kelas.murid),
        joinedload(models.Kelas.kurikulum),
    ).all()

    # Cek per kelas: sudah ada presensi atau belum
    presensi_status = {}
    for k in wali_kelas_list:
        jumlah_murid     = len(k.murid)
        jumlah_presensi  = db.query(models.Presensi).filter(
            models.Presensi.kelas_id     == k.id,
            models.Presensi.kurikulum_id == k.kurikulum_id
        ).count()
        jumlah_ekskul = db.query(models.NilaiEkstrakurikuler).join(
            models.User,
            models.NilaiEkstrakurikuler.murid_id == models.User.id
        ).filter(
            models.NilaiEkstrakurikuler.kurikulum_id == k.kurikulum_id,
            models.User.id.in_([m.id for m in k.murid])
        ).count()

        presensi_status[k.id] = {
            "sudah_presensi": jumlah_presensi >= jumlah_murid and jumlah_murid > 0,
            "jumlah_presensi": jumlah_presensi,
            "jumlah_murid":    jumlah_murid,
            "ada_ekskul":      jumlah_ekskul > 0,
        }

    return templates.TemplateResponse("dashboard_guru.html", {
        "request":          request,
        "nama":             request.session["user_name"],
        "mengajar":         mengajar,
        "wali_kelas_list":  wali_kelas_list,
        "presensi_status":  presensi_status,
    })


@app.get("/dashboard/guru/input/{kelas_mapel_id}", response_class=HTMLResponse)
def guru_input_nilai(
    request: Request,
    kelas_mapel_id: int,
    mode: str = "per_mapel",   # per_mapel atau per_murid
    db: Session = Depends(get_db)
):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]

    gm = (
        db.query(models.GuruMengajar)
        .filter(
            models.GuruMengajar.guru_id == user_id,
            models.GuruMengajar.kelas_mapel_id == kelas_mapel_id
        )
        .options(
            joinedload(models.GuruMengajar.kelas_mapel)
                .joinedload(models.KelasMapel.kelas)
                .joinedload(models.Kelas.murid),
            joinedload(models.GuruMengajar.kelas_mapel)
                .joinedload(models.KelasMapel.mapel),
        )
        .first()
    )

    if not gm:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    kelas  = gm.kelas_mapel.kelas
    mapel  = gm.kelas_mapel.mapel
    murid_list = kelas.murid

    existing_raports = {
        r.murid_id: r
        for r in db.query(models.Raport).filter(
            models.Raport.kelas_mapel_id == kelas_mapel_id
        ).all()
    }

    return templates.TemplateResponse("guru_input_nilai.html", {
        "request":          request,
        "nama":             request.session["user_name"],
        "gm":               gm,
        "kelas":            kelas,
        "mapel":            mapel,
        "murid_list":       murid_list,
        "existing_raports": existing_raports,
        "mode":             mode,
    })


@app.post("/dashboard/guru/simpan-nilai/{kelas_mapel_id}")
def guru_simpan_nilai(
    request:        Request,
    kelas_mapel_id: int,
    db:             Session = Depends(get_db),
    # nilai dikirim sebagai murid_id[]:nilai_pengetahuan, dll
    # FastAPI tidak bisa terima dynamic keys langsung, pakai raw form
):
    guard = require_role(request, "guru")
    if guard: return guard
    raise HTTPException(status_code=400, detail="Gunakan endpoint async")


@app.post("/dashboard/guru/simpan-nilai-async/{kelas_mapel_id}")
async def guru_simpan_nilai_async(
    request:        Request,
    kelas_mapel_id: int,
    db:             Session = Depends(get_db)
):
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]

    gm = db.query(models.GuruMengajar).filter(
        models.GuruMengajar.guru_id == user_id,
        models.GuruMengajar.kelas_mapel_id == kelas_mapel_id
    ).first()
    if not gm:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    form = await request.form()
    kelas_id = gm.kelas_mapel.kelas_id

    # Ambil semua murid di kelas ini
    murid_ids = [
        km.murid_id for km in
        db.query(models.KelasMurid).filter(
            models.KelasMurid.kelas_id == kelas_id
        ).all()
    ]

    for murid_id in murid_ids:
        nilai_p = form.get(f"pengetahuan_{murid_id}")
        nilai_k = form.get(f"keterampilan_{murid_id}")
        deskripsi = form.get(f"deskripsi_{murid_id}", "")

        if nilai_p is None and nilai_k is None:
            continue

        nilai_p = float(nilai_p) if nilai_p else None
        nilai_k = float(nilai_k) if nilai_k else None

        # Hitung nilai akhir dan predikat
        nilai_akhir = None
        predikat    = None
        if nilai_p is not None and nilai_k is not None:
            nilai_akhir = round((nilai_p + nilai_k) / 2, 1)
            kkm = gm.kelas_mapel.mapel.kkm
            if nilai_akhir >= 90:   predikat = "A"
            elif nilai_akhir >= 80: predikat = "B"
            elif nilai_akhir >= 70: predikat = "C"
            elif nilai_akhir >= kkm: predikat = "D"
            else:                   predikat = "E"

        raport = db.query(models.Raport).filter(
            models.Raport.murid_id == murid_id,
            models.Raport.kelas_mapel_id == kelas_mapel_id
        ).first()

        if raport:
            # Jangan update kalau sudah submitted/published
            if raport.status == models.StatusRaport.draft:
                raport.nilai_pengetahuan  = nilai_p
                raport.nilai_keterampilan = nilai_k
                raport.nilai_akhir        = nilai_akhir
                raport.predikat           = predikat
                raport.deskripsi          = deskripsi or None
                raport.guru_mengajar_id   = gm.id
        else:
            raport = models.Raport(
                murid_id          = murid_id,
                kelas_id          = kelas_id,
                kelas_mapel_id    = kelas_mapel_id,
                guru_mengajar_id  = gm.id,
                nilai_pengetahuan = nilai_p,
                nilai_keterampilan= nilai_k,
                nilai_akhir       = nilai_akhir,
                predikat          = predikat,
                deskripsi         = deskripsi or None,
                status            = models.StatusRaport.draft,
            )
            db.add(raport)

    db.commit()
    return RedirectResponse(
        url=f"/dashboard/guru/input/{kelas_mapel_id}?saved=1",
        status_code=303
    )


@app.post("/dashboard/guru/submit-nilai/{kelas_mapel_id}")
def guru_submit_nilai(
    request:        Request,
    kelas_mapel_id: int,
    db:             Session = Depends(get_db)
):
    """Ubah semua draft → submitted untuk kelas_mapel ini."""
    guard = require_role(request, "guru")
    if guard: return guard

    user_id = request.session["user_id"]
    gm = db.query(models.GuruMengajar).filter(
        models.GuruMengajar.guru_id == user_id,
        models.GuruMengajar.kelas_mapel_id == kelas_mapel_id
    ).first()
    if not gm:
        raise HTTPException(status_code=403)

    db.query(models.Raport).filter(
        models.Raport.kelas_mapel_id == kelas_mapel_id,
        models.Raport.status == models.StatusRaport.draft
    ).update({"status": models.StatusRaport.submitted})
    db.commit()

    return RedirectResponse(url="/dashboard/guru", status_code=303)


# ========================== MURID ====================================
@app.get("/dashboard/murid", response_class=HTMLResponse)
def dashboard_murid(request: Request, db: Session = Depends(get_db)):
    guard = require_role(request, "murid")
    if guard: return guard

    user_id = request.session["user_id"]

    raports = (
        db.query(models.Raport)
        .filter(
            models.Raport.murid_id == user_id,
            models.Raport.status   == models.StatusRaport.published
        )
        .options(
            joinedload(models.Raport.kelas_mapel)
                .joinedload(models.KelasMapel.mapel),
            joinedload(models.Raport.kelas_mapel)
                .joinedload(models.KelasMapel.kelas)
                .joinedload(models.Kelas.kurikulum),
            joinedload(models.Raport.kelas),
        )
        .order_by(models.Raport.tanggal_input)
        .all()
    )

    # Kelompokkan: {tahun_ajaran: {semester: [raport, ...]}}
    histori = {}
    ada_nilai = False

    for r in raports:
        ada_nilai = True
        kurikulum = r.kelas_mapel.kelas.kurikulum
        tahun     = kurikulum.tahun_ajaran
        semester  = kurikulum.semester

        histori.setdefault(tahun, {})
        histori[tahun].setdefault(semester, [])
        histori[tahun][semester].append(r)

    return templates.TemplateResponse("dashboard_murid.html", {
        "request":   request,
        "nama":      request.session["user_name"],
        "histori":   histori,
        "ada_nilai": ada_nilai,
    })


def render_raport_html(nama, murid, kelas, kurikulum, raports,
                       rata_rata, jumlah_e, naik_kelas, tahun, semester,
                       presensi=None, nilai_ekskul=None):
 
    rows = ""
    for nomor, r in enumerate(sorted(raports, key=lambda x: x.kelas_mapel.mapel.kategori or ""), 1):
        mapel = r.kelas_mapel.mapel
        row_bg = "#fff5f5" if r.predikat == "E" else "#ffffff"
 
        if mapel.kategori == "Wajib Nasional":
            kat_label, kat_color, kat_bg = "Wajib", "#1d4ed8", "#dbeafe"
        elif mapel.kategori == "Muatan Lokal":
            kat_label, kat_color, kat_bg = "Mulok", "#6d28d9", "#ede9fe"
        elif mapel.kategori and "Produktif" in mapel.kategori:
            kat_label, kat_color, kat_bg = "Produktif", "#b45309", "#fef3c7"
        else:
            kat_label, kat_color, kat_bg = "Lainnya", "#6b7280", "#f3f4f6"
 
        pred_styles = {
            "A": ("#065f46", "#d1fae5"),
            "B": ("#1e40af", "#dbeafe"),
            "C": ("#92400e", "#fef3c7"),
            "D": ("#9a3412", "#fee2e2"),
            "E": ("#991b1b", "#fee2e2"),
        }
        pc, pb = pred_styles.get(r.predikat or "", ("#6b7280", "#f3f4f6"))
        bawah_kkm = r.nilai_akhir is not None and r.nilai_akhir < mapel.kkm
 
        rows += f"""
        <tr class="row {'row-danger' if r.predikat == 'E' else ''}">
        <td class="center no">{nomor}</td>
        <td class="mapel">
            <div class="mapel-nama">{mapel.nama_mapel}</div>
            <div class="mapel-kode">{mapel.kode_mapel}</div>
        </td>
        <td class="center">
            <span class="badge kategori">{kat_label}</span>
        </td>
        <td class="center muted">{mapel.kkm}</td>
        <td class="center nilai">{r.nilai_pengetahuan or '—'}</td>
        <td class="center nilai">{r.nilai_keterampilan or '—'}</td>
        <td class="center nilai-akhir {'danger' if bawah_kkm else ''}">
            {r.nilai_akhir or '—'}
        </td>
        <td class="center">
            <span class="badge predikat">{r.predikat or '—'}</span>
        </td>
        <td class="deskripsi">{r.deskripsi or '—'}</td>
        </tr>
        """
 
    # Presensi
    s_val = presensi.sakit if presensi else 0
    i_val = presensi.izin if presensi else 0
    a_val = presensi.alpha if presensi else 0
    t_val = s_val + i_val + a_val
 
    # Ekskul rows
    ekskul_rows = ""
    if nilai_ekskul:
        for ne in nilai_ekskul:
            pred_e = ne.nilai or "—"
            ekskul_rows += f"""
            <tr>
              <td style="font-weight:500;font-size:10px;padding:6px 8px">{ne.ekskul.nama_ekskul}</td>
              <td class="center" style="font-weight:700;font-size:11px;width:60px">{pred_e}</td>
              <td style="font-size:10px;color:#6b7280;padding:6px 8px">{ne.deskripsi or '—'}</td>
            </tr>"""
    else:
        ekskul_rows = '<tr><td colspan="3" style="text-align:center;color:#9ca3af;font-size:10px;padding:16px">Tidak mengikuti ekstrakulikuler</td></tr>'
 
    wali_nama = kelas.wali_kelas.nama if kelas.wali_kelas else "_________________________"
    wali_nip = f"NIP. {kelas.wali_kelas.nip_nis}" if kelas.wali_kelas and kelas.wali_kelas.nip_nis else ""
 
    status_class = "status-naik" if naik_kelas else "status-tinggal"
    status_text = "✓ NAIK KELAS" if naik_kelas else "✗ TIDAK NAIK KELAS"
    e_color = "#dc2626" if jumlah_e > 0 else "#059669"
 
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Rapor {nama} — {tahun} {semester}</title>
<style>
  @page {{
    size: A4;
    margin: 1.2cm;
  }}

  body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10.5px;
    color: #1f2937;
    line-height: 1.4;
  }}

  .center {{ text-align: center; }}
  .muted {{ color: #6b7280; }}

  /* KOP */
  .kop {{
    text-align: center;
    border-bottom: 2px solid #f97316;
    margin-bottom: 10px;
    padding-bottom: 6px;
  }}
  .kop h1 {{ font-size: 16px; margin: 0; }}
  .kop h2 {{ font-size: 12px; margin: 0; }}
  .kop .alamat {{ font-size: 9px; color: #6b7280; }}

  /* JUDUL */
  .judul {{
    text-align: center;
    margin: 10px 0;
  }}
  .badge-title {{
    background: #f97316;
    color: #fff;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 11px;
  }}
  .periode {{
    font-size: 9px;
    color: #6b7280;
    margin-top: 3px;
  }}

  /* INFO */
  .info-siswa {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 10px;
  }}
  .info-siswa td {{
    border: 1px solid #e5e7eb;
    padding: 4px 6px;
  }}
  .info-siswa .label {{
    width: 110px;
    background: #fef3c7;
    font-weight: 600;
  }}

  /* TABEL NILAI */
  .tabel-nilai {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }}
  .tabel-nilai th {{
    background: #f97316;
    color: #fff;
    padding: 5px;
    font-size: 10px;
    border: 1px solid #e5e7eb;
  }}
  .tabel-nilai td {{
    padding: 5px;
    border: 1px solid #e5e7eb;
    vertical-align: top;
  }}

  .tabel-nilai th:nth-child(1) {{ width: 30px; }}
  .tabel-nilai th:nth-child(3) {{ width: 60px; }}
  .tabel-nilai th:nth-child(4) {{ width: 40px; }}
  .tabel-nilai th:nth-child(5),
  .tabel-nilai th:nth-child(6),
  .tabel-nilai th:nth-child(7) {{ width: 65px; }}
  .tabel-nilai th:nth-child(8) {{ width: 50px; }}

  /* ROW */
  .row:nth-child(even) {{ background: #f9fafb; }}
  .row-danger {{ background: #fef2f2; }}

  /* MAPEL */
  .mapel-nama {{
    font-weight: 600;
    font-size: 10.5px;
  }}
  .mapel-kode {{
    font-size: 9px;
    color: #9ca3af;
  }}

  /* BADGE */
  .badge {{
    display: inline-block;
    padding: 2px 6px;
    border-radius: 10px;
    font-size: 9px;
    font-weight: bold;
    background: #e5e7eb;
  }}
  .predikat {{
    background: #dbeafe;
  }}

  /* NILAI */
  .nilai {{ font-weight: 600; }}
  .nilai-akhir {{ font-weight: bold; }}
  .danger {{ color: #dc2626; }}

  /* DESKRIPSI */
  .deskripsi {{
    font-size: 9.5px;
    color: #4b5563;
    line-height: 1.3;
  }}

  /* SECTION */
  .section-header {{
    background: #f97316;
    color: #fff;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: bold;
    margin-top: 10px;
  }}

  /* PRESENSI */
  .presensi-grid {{
    display: flex;
    gap: 6px;
    margin-top: 6px;
  }}
  .presensi-item {{
    flex: 1;
    text-align: center;
    padding: 6px;
    border: 1px solid #e5e7eb;
  }}
  .presensi-angka {{
    font-size: 18px;
    font-weight: bold;
  }}
  .presensi-label {{
    font-size: 9px;
  }}

  /* EKSKUL */
  .tabel-ekskul {{
    width: 100%;
    border-collapse: collapse;
  }}
  .tabel-ekskul th,
  .tabel-ekskul td {{
    border: 1px solid #e5e7eb;
    padding: 5px;
  }}

  /* TTD */
  .ttd-grid {{
    display: flex;
    justify-content: space-between;
    margin-top: 16px;
  }}
  .ttd-box {{
    width: 30%;
    text-align: center;
  }}
  .ttd-label {{
    font-size: 9px;
    margin-bottom: 30px;
  }}
  .ttd-garis {{
    border-top: 1px solid #000;
    padding-top: 4px;
    font-weight: bold;
  }}

  @media print {{
    body {{ margin: 0; }}
    .page-break {{ page-break-before: always; }}
  }}
</style>
</head>
<body>

<!-- HALAMAN 1 -->
<div class="kop">
  <h1>PEMERINTAH PROVINSI CONTOH</h1>
  <h2>DINAS PENDIDIKAN</h2>
  <h1>SMK NEGERI 1 CONTOH</h1>
  <div class="alamat">Jl. Pendidikan No. 1, Kota Contoh | Telp. (021) 1234567 | www.smkbinabangsa.sch.id</div>
</div>

<div class="judul">
  <div class="badge">LAPORAN HASIL BELAJAR SISWA (RAPOR)</div>
  <div class="periode">Tahun Ajaran {tahun} | Semester {semester}</div>
</div>

<table class="info-siswa">
  <tr>
    <td class="label">Nama Peserta Didik</td>
    <td><strong>{nama}</strong></td>
    <td class="label">NIS / NISN</td>
    <td>{murid.nip_nis or '—'}</td>
  </tr>
  <tr>
    <td class="label">Kelas</td>
    <td>{kelas.tingkat} — {kelas.jurusan} — {kelas.nama_kelas}</td>
    <td class="label">Kurikulum</td>
    <td>{kurikulum.nama_kurikulum}</td>
  </tr>
  <tr>
    <td class="label">Wali Kelas</td>
    <td>{wali_nama}</td>
    <td class="label">Tanggal Cetak</td>
    <td>{date.today().strftime('%d %B %Y')}</td>
  </tr>
</table>

<table class="tabel-nilai">
  <thead>
    <tr>
      <th>No</th>
      <th>Mata Pelajaran</th>
      <th style="width:55px">Kategori</th>
      <th style="width:32px">KKM</th>
      <th style="width:60px">Pengetahuan</th>
      <th style="width:65px">Keterampilan</th>
      <th style="width:55px">Nilai Akhir</th>
      <th style="width:45px">Predikat</th>
      <th>Deskripsi</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<!-- HALAMAN 2 -->
<div class="page-break"></div>

<div class="judul">
  <div class="badge">LAMPIRAN RAPORT</div>
  <div class="periode">{nama} | Tahun Ajaran {tahun} | Semester {semester}</div>
</div>

<div class="section-header">📊 REKAP KEHADIRAN</div>
<div class="presensi-grid">
  <div class="presensi-item presensi-sakit">
    <div class="presensi-angka">{s_val}</div>
    <div class="presensi-label">Sakit</div>
  </div>
  <div class="presensi-item presensi-izin">
    <div class="presensi-angka">{i_val}</div>
    <div class="presensi-label">Izin</div>
  </div>
  <div class="presensi-item presensi-alpha">
    <div class="presensi-angka">{a_val}</div>
    <div class="presensi-label">Alpha</div>
  </div>
  <div class="presensi-item presensi-total">
    <div class="presensi-angka">{t_val}</div>
    <div class="presensi-label">Total</div>
  </div>
</div>

<div class="section-header">🎯 EKSTRAKULIKULER</div>
<table class="tabel-ekskul">
  <thead>
    <tr>
      <th>Kegiatan</th>
      <th style="width:60px;text-align:center">Nilai</th>
      <th>Keterangan</th>
    </tr>
  </thead>
  <tbody>
    {ekskul_rows}
  </tbody>
</table>

<div class="section-header">📈 STATISTIK NILAI</div>
<div class="statistik-grid">
  <div class="stat-item">
    <div class="stat-angka">{rata_rata}</div>
    <div class="stat-label">Rata-rata</div>
  </div>
  <div class="stat-item">
    <div class="stat-angka" style="color:{e_color}">{jumlah_e}</div>
    <div class="stat-label">Nilai E</div>
  </div>
  <div class="stat-item">
    <div class="stat-angka">{len(raports)}</div>
    <div class="stat-label">Total Mapel</div>
  </div>
  <div class="stat-item">
    <div class="stat-angka">{t_val}</div>
    <div class="stat-label">Total Absen</div>
  </div>
</div>

<div class="{status_class}">
  {status_text}
</div>

<div class="catatan">
  <strong>📌 Keterangan Predikat:</strong><br>
  A = Sangat Baik (90-100) &nbsp;|&nbsp;
  B = Baik (80-89) &nbsp;|&nbsp;
  C = Cukup (70-79) &nbsp;|&nbsp;
  D = Kurang (KKM-69) &nbsp;|&nbsp;
  E = Sangat Kurang (&lt; KKM)<br>
  <strong>Catatan:</strong> Siswa dinyatakan naik kelas jika tidak memiliki nilai E pada seluruh mata pelajaran.
</div>

<div class="ttd-grid">
  <div class="ttd-box">
    <div class="ttd-label">Orang Tua / Wali Murid</div>
    <div class="ttd-garis">_________________________</div>
    <div class="ttd-nip">&nbsp;</div>
  </div>
  <div class="ttd-box">
    <div class="ttd-label">Wali Kelas</div>
    <div class="ttd-garis">{wali_nama}</div>
    <div class="ttd-nip">{wali_nip}</div>
  </div>
  <div class="ttd-box">
    <div class="ttd-label">Kepala Sekolah</div>
    <div class="ttd-garis">Drs. Ahmad Fauzi, M.Pd.</div>
    <div class="ttd-nip">NIP. 19651231 199103 1 001</div>
  </div>
</div>

<div class="footer">
  Dokumen resmi dicetak dari Sistem Informasi Raport | {date.today().strftime('%d %B %Y')}
</div>

</body>
</html>"""

@app.get("/dashboard/murid/export-pdf/{tahun}/{semester}")
def export_raport_pdf(
    request:  Request,
    tahun:    str,
    semester: str,
    db:       Session = Depends(get_db)
):
    guard = require_role(request, "murid")
    if guard: return guard

    user_id = request.session["user_id"]
    nama    = request.session["user_name"]

    tahun = tahun.replace("-", "/")

    # 1. Ambil semua raport dulu
    raports = (
        db.query(models.Raport)
        .filter(
            models.Raport.murid_id == user_id,
            models.Raport.status   == models.StatusRaport.published
        )
        .options(
            joinedload(models.Raport.kelas_mapel)
                .joinedload(models.KelasMapel.mapel),
            joinedload(models.Raport.kelas_mapel)
                .joinedload(models.KelasMapel.kelas)
                .joinedload(models.Kelas.kurikulum),
            joinedload(models.Raport.kelas),
        )
        .all()
    )

    # 2. Filter by tahun & semester — harus sebelum dipakai
    raports_filtered = [
        r for r in raports
        if r.kelas_mapel.kelas.kurikulum.tahun_ajaran == tahun
        and r.kelas_mapel.kelas.kurikulum.semester == semester
    ]

    if not raports_filtered:
        raise HTTPException(status_code=404, detail="Data raport tidak ditemukan")

    # 3. Baru ambil data lain yang butuh raports_filtered
    kurikulum_id = raports_filtered[0].kelas_mapel.kelas.kurikulum_id

    presensi = db.query(models.Presensi).filter(
        models.Presensi.murid_id     == user_id,
        models.Presensi.kurikulum_id == kurikulum_id
    ).first()

    nilai_ekskul = db.query(models.NilaiEkstrakurikuler).filter(
        models.NilaiEkstrakurikuler.murid_id     == user_id,
        models.NilaiEkstrakurikuler.kurikulum_id == kurikulum_id
    ).options(
        joinedload(models.NilaiEkstrakurikuler.ekskul)
    ).all()

    murid     = db.query(models.User).get(user_id)
    kelas     = raports_filtered[0].kelas
    kurikulum = raports_filtered[0].kelas_mapel.kelas.kurikulum

    nilai_list = [r.nilai_akhir for r in raports_filtered if r.nilai_akhir is not None]
    rata_rata  = round(sum(nilai_list) / len(nilai_list), 1) if nilai_list else 0
    jumlah_e   = sum(1 for r in raports_filtered if r.predikat == "E")
    naik_kelas = jumlah_e == 0

    html_string = render_raport_html(
        nama=nama,
        murid=murid,
        kelas=kelas,
        kurikulum=kurikulum,
        raports=raports_filtered,
        rata_rata=rata_rata,
        jumlah_e=jumlah_e,
        naik_kelas=naik_kelas,
        tahun=tahun,
        semester=semester,
        presensi=presensi,
        nilai_ekskul=nilai_ekskul,
    )

    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        src=html_string,
        dest=pdf_buffer,
        encoding='utf-8'
    )

    if pisa_status.err:
        raise HTTPException(status_code=500, detail="Gagal generate PDF")

    pdf_buffer.seek(0)
    filename = f"raport_{nama.replace(' ', '_')}_{tahun.replace('/', '-')}_{semester}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ======================== PASSWORD ========================================
@app.get("/ganti-password", response_class=HTMLResponse)
def halaman_ganti_password(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("ganti_password.html", {
        "request": request,
        "nama":    request.session["user_name"],
        "role":    request.session["user_role"],
        "error":   request.query_params.get("error"),
        "success": request.query_params.get("success"),
    })

@app.post("/ganti-password")
def post_ganti_password(
    request:         Request,
    password_lama:   str = Form(...),
    password_baru:   str = Form(...),
    password_konfirm: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db_user = db.query(models.User).get(user["id"])

    if not verify_password(db_user.password, password_lama):
        return RedirectResponse(
            url="/ganti-password?error=Password+lama+salah",
            status_code=303
        )
    if len(password_baru) < 6:
        return RedirectResponse(
            url="/ganti-password?error=Password+baru+minimal+6+karakter",
            status_code=303
        )
    if password_baru != password_konfirm:
        return RedirectResponse(
            url="/ganti-password?error=Konfirmasi+password+tidak+cocok",
            status_code=303
        )

    db_user.password = hash_password(password_baru)
    db.commit()
    return RedirectResponse(
        url="/ganti-password?success=Password+berhasil+diubah",
        status_code=303
    )

# ------------------------- Swagger ----------------------------------
@app.post("/admin/create", tags=["Admin"])
def create_admin(data: schemas.AdminCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    existing = db.query(models.User).filter(models.User.nama == data.nama).first()
    if existing:
        raise HTTPException(status_code=400, detail="nama sudah terdaftar")
    
    user = models.User(
        nama=data.nama,
        email=data.email,
        password=hash_password(data.password),
        role=data.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Admin berhasil dibuat", "id": user.id, "email": user.email}

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    return db.query(models.User).all()

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    data = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not data:
        return {"error": "data tidak ditemukan"}
    
    db.delete(data)
    db.commit()
    
    return{"message": "berhasil dihapus"}