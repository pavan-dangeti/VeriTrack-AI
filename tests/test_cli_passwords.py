"""The CLI never prints or logs a new account's password. It comes from an environment variable or, in a
terminal, a hidden prompt, never from a command-line argument.

The commands run as real processes so everything they write (stdout, stderr, structured logs) is checked.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import cli
from app.db.tenant import SYSTEM, tenant
from app.models.user import User
from tests.conftest import open_session
from tests.helpers import login

ROOT = Path(__file__).resolve().parents[1]
SECRET = "Unprinted-Pass-7f3a"


def _run(*args: str, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ("ADMIN_PASSWORD", "ORG_ADMIN_PASSWORD")}
    return subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=ROOT, env={**clean, **env},  # noqa: S603
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


async def test_create_master_admin_takes_the_password_from_the_environment_and_never_prints_it(client):
    out = _run("create-master-admin", "--email", "boot@veritrack.io", ADMIN_PASSWORD=SECRET)

    assert out.returncode == 0, out.stderr
    assert "Master Admin created: boot@veritrack.io" in out.stdout
    assert SECRET not in out.stdout + out.stderr
    await login(client, "boot@veritrack.io", SECRET)   # the account has exactly that password


async def test_create_organization_takes_the_password_from_the_environment_and_never_prints_it(client):
    out = _run("create-organization", "Gamma Org", "--admin-email", "admin@gamma.example", ORG_ADMIN_PASSWORD=SECRET)

    assert out.returncode == 0, out.stderr
    assert SECRET not in out.stdout + out.stderr
    await login(client, "admin@gamma.example", SECRET)


@pytest.mark.parametrize("args, env_var", [
    (("create-master-admin", "--email", "boot@veritrack.io"), "ADMIN_PASSWORD"),
    (("create-organization", "Delta Org", "--admin-email", "admin@delta.example"), "ORG_ADMIN_PASSWORD"),
])
async def test_without_a_password_or_a_terminal_nothing_is_created_or_printed(args, env_var):
    out = _run(*args)

    assert out.returncode == 2
    assert f"set {env_var}" in out.stderr
    assert "password (shown once)" not in out.stdout   # the old commands generated one and printed it
    with tenant(SYSTEM):   # every organisation's users
        async with open_session() as db:
            assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0


def test_the_hidden_prompt_asks_twice_and_never_echoes(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter([SECRET, SECRET, SECRET, "something-else", "short", "short"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))

    assert cli.read_password("ADMIN_PASSWORD", None) == SECRET
    assert cli.read_password("ADMIN_PASSWORD", None) is None        # the two entries differ
    assert cli.read_password("ADMIN_PASSWORD", None) is None        # too short
    assert cli.read_password("ADMIN_PASSWORD", "x" * 73) is None    # too long for bcrypt
    printed = capsys.readouterr()
    assert SECRET not in printed.out + printed.err
    assert "do not match" in printed.err and "8 to 72 characters" in printed.err
