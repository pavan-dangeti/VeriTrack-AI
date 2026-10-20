import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB, require_role
from app.core.permissions import Permission
from app.models.audit_log import AuditLog, AuditResult
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogOut, AuditLogPage
from app.services import audit_chain, audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit"])

AuditViewer = Annotated[
    User,
    Depends(
        require_role(
            UserRole.MASTER_ADMIN,
            audit_permission=Permission.VIEW_AUDIT_LOGS,
        )
    ),
]


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    viewer: AuditViewer,
    db: DB,
    result_filter: AuditResult | None = Query(default=None, alias="result"),
    action: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    _ = viewer  # authorization happens in the dependency; identity not needed here
    base = select(AuditLog)
    if result_filter is not None:
        base = base.where(AuditLog.result == result_filter)
    if action is not None:
        base = base.where(AuditLog.action == action)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return AuditLogPage(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/verify")
async def verify_audit_log(
    viewer: AuditViewer,
    db: DB,
    expect_seq: int | None = Query(default=None, ge=1),
    expect_hash: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
):
    """Recomputes this organisation's audit chain. Pass a head recorded earlier (expect_seq, expect_hash) to
    also catch removal of the newest entries or a full rewrite. The check itself is audited."""
    if (expect_seq is None) != (expect_hash is None):
        raise HTTPException(422, detail={"code": "bad_anchor",
                                         "message": "Give both expect_seq and expect_hash, or neither"})
    anchors: dict[uuid.UUID | None, tuple[int, str]] | None = (
        {viewer.org_id: (expect_seq, expect_hash)} if expect_seq and expect_hash else None)
    reports = await audit_chain.verify(db, anchors)
    report = next((r for r in reports if r.org_id == viewer.org_id), audit_chain.ChainReport(viewer.org_id))
    await audit_service.record(
        db, action=audit_service.ACTION_AUDIT_VERIFIED,
        result=audit_service.AuditResult.SUCCESS if report.ok else audit_service.AuditResult.FAILURE,
        actor_user_id=viewer.id, target_entity="audit_log",
        metadata={"entries": report.entries, "head_seq": report.head_seq, "first_break": report.first_break},
    )
    return report.as_dict()


@router.get("/export.csv")
async def export_audit_csv(
    viewer: AuditViewer,
    db: DB,
    result_filter: AuditResult | None = Query(default=None, alias="result"),
    action: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=5000, ge=1, le=20000),
):
    import csv
    import io

    base = select(AuditLog)
    if result_filter is not None:
        base = base.where(AuditLog.result == result_filter)
    if action is not None:
        base = base.where(AuditLog.action == action)
    rows = (
        await db.execute(
            base.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)
        )
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "timestamp", "actor_user_id", "action", "target_entity",
                     "target_id", "result", "ip_address", "user_agent"])
    for r in rows:
        writer.writerow([r.id, r.timestamp.isoformat(), r.actor_user_id, r.action,
                         r.target_entity, r.target_id, r.result.value, r.ip_address,
                         (r.user_agent or "")[:120]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )
