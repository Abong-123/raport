from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Eksekusi kedua perintah sekaligus dengan text()
    conn.execute(text("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS jurusan VARCHAR(50);
        ALTER TABLE users ADD COLUMN IF NOT EXISTS angkatan INTEGER;
    """))
    conn.commit()
    print("Migrasi selesai.")