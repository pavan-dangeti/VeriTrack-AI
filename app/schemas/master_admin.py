from pydantic import BaseModel
from pydantic import EmailStr


class CreateManagerRequest(BaseModel):

    name: str

    email: EmailStr

    password: str


class CreateHRRequest(BaseModel):

    name: str

    email: EmailStr

    password: str


class AssignHRRequest(BaseModel):

    hr_id: str

    manager_id: str