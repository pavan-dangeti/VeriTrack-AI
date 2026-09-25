"""What each role should see; mirrors frontend/src/navigation/nav.ts.

(label, path, h1) per sidebar entry, in order; h1=None means the heading is data-dependent.
"""

SIDEBAR = {
    "MASTER_ADMIN": [
        ("Dashboard", "/dashboard", "Dashboard"),
        ("Analytics", "/analytics", "Analytics"),
        ("Manage Users", "/users", "Manage Users"),
        ("All GETS Uploads", "/all-uploads", "All GETS Uploads"),
        ("All Employee Repositories", "/all-employees", "All Employee Repositories"),
        ("Company Leave Register", "/leaves", "Company Leave Register"),
        ("All Reports", "/all-reports", "All Reports"),
        ("System Settings", "/settings", "System Settings"),
        ("Audit Logs", "/audit-logs", "Audit Logs"),
        ("Profile", "/profile", None),
        ("Account Settings", "/account", "Account Settings"),
    ],
    "MANAGER": [
        ("Dashboard", "/dashboard", "Dashboard"),
        ("Analytics", "/analytics", "Analytics"),
        ("Employee Repository", "/employees", "Employee Repository"),
        ("GETS Uploads", "/gets", "GETS Uploads"),
        ("Company Leave Register", "/leaves", "Company Leave Register"),
        ("Reports & History", "/reports", "Reports & History"),
        ("My HR Team", "/hr-team", "My HR Team"),
        ("Profile", "/profile", None),
        ("Account Settings", "/account", "Account Settings"),
    ],
    "HR": [
        ("Dashboard", "/dashboard", "Team Overview"),
        ("Analytics", "/analytics", "Analytics"),
        ("Company Leave Register", "/leaves", "Company Leave Register"),
        ("Employee Data", "/employee-data", "Employee Data"),
        ("Monthly GETS Sheets", "/gets-sheets", "Monthly GETS Sheets"),
        ("Profile", "/profile", None),
        ("Account Settings", "/account", "Account Settings"),
    ],
    "EXECUTIVE": [
        ("Dashboard", "/dashboard", "Dashboard"),
        ("Analytics", "/analytics", "Analytics"),
        ("All Employee Repositories", "/all-employees", "All Employee Repositories"),
        ("Company Leave Register", "/leaves", "Company Leave Register"),
        ("All Reports", "/all-reports", "All Reports"),
        ("Manager & HR Directory", "/directory", "Manager & HR Directory"),
        ("Profile", "/profile", None),
        ("Account Settings", "/account", "Account Settings"),
    ],
}

# URLs each role must NOT reach (typed straight into the address bar).
FORBIDDEN = {
    "MANAGER": [
        "/users",
        "/settings",
        "/audit-logs",
        "/all-uploads",
        "/all-reports",
        "/all-employees",
        "/directory",
        "/employee-data",
        "/gets-sheets",
    ],
    "HR": [
        "/users",
        "/gets",
        "/settings",
        "/audit-logs",
        "/employees",
        "/reports",
        "/hr-team",
        "/all-uploads",
        "/all-reports",
        "/all-employees",
        "/directory",
        "/people/00000000-0000-0000-0000-000000000000",
        "/analysis/whatever",
    ],
    "EXECUTIVE": [
        "/users",
        "/settings",
        "/gets",
        "/audit-logs",
        "/all-uploads",
        "/employees",
        "/reports",
        "/hr-team",
        "/employee-data",
        "/gets-sheets",
    ],
    "MASTER_ADMIN": ["/gets", "/employees", "/reports", "/hr-team", "/directory", "/employee-data", "/gets-sheets"],
}


def visit_every_sidebar_page(session, role: str, prefix: str = "page") -> None:
    from playwright.sync_api import expect

    labels = session.sidebar_labels()
    assert labels == [x[0] for x in SIDEBAR[role]], labels
    for i, (label, path, heading) in enumerate(SIDEBAR[role]):
        session.nav(label, path, heading)
        h1 = session.page.locator("main h1").first
        expect(h1).to_be_visible()
        assert h1.inner_text().strip(), f"{path} rendered an empty heading"
        session.shot(f"{prefix}-{i:02d}-{path.strip('/').replace('/', '_')}")
