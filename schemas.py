from pydantic import BaseModel
from typing import Optional
from models import UserRole

class AdminCreate(BaseModel):
    nama: str
    email: str
    password: str
    role: UserRole = UserRole.admin

