import io

from tests.conftest import MA_EMAIL, MA_PASSWORD


async def login(client, email: str, password: str) -> dict:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def admin(client) -> dict:
    return await login(client, MA_EMAIL, MA_PASSWORD)


async def create_user(client, creator: dict, email: str, role: str) -> tuple[str, dict]:
    r = await client.post("/api/v1/users", json={"email": email, "role": role}, headers=creator)
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user"]["id"], await login(client, email, body["initial_password"])


async def manager(client, tag: str) -> dict:
    _, headers = await create_user(client, await admin(client), f"{tag}@veritrack.io", "MANAGER")
    return headers


def csv_file(name: str, text: bytes | str):
    data = text.encode() if isinstance(text, str) else text
    return ("files", (name, io.BytesIO(data), "text/csv"))
