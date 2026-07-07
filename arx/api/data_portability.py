"""Data Portability & Migration API — Section 74."""
import csv
import io
import json
import zipfile
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from arx.agents.data_portability import IMPORT_RESOURCE_TYPES
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.data_portability import export_org_data, import_csv

router = APIRouter(prefix="/api/v1", tags=["data-portability"])


@router.post("/import/{resource_type}")
async def import_resource(
    resource_type: str, file: UploadFile,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    if resource_type not in IMPORT_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown import resource_type {resource_type!r} — must be one of {IMPORT_RESOURCE_TYPES}",
        )
    csv_bytes = await file.read()
    csv_text = csv_bytes.decode("utf-8-sig")  # tolerate Excel's BOM-prefixed CSV export

    with db_session(claims_for(user)) as conn:
        report = import_csv(conn, org_id=user.org_id, resource_type=resource_type, csv_text=csv_text)

    return {"resource_type": resource_type, **report}


def _json_default(value):
    # Postgres date/datetime/Decimal come back through dict_row as non-JSON-native
    # types (numeric loads as float per _configure_connection, but date/timestamptz
    # and any remaining Decimal still need an explicit str() fallback here).
    return str(value)


@router.get("/export")
def export_data(
    format: Literal["json", "csv"] = "json",
    user: CurrentUser = Depends(require_role("admin")),
):
    """Section 74: "Full export available at any time to Admin role.\""""
    with db_session(claims_for(user)) as conn:
        data = export_org_data(conn, user.org_id)

    if format == "json":
        return Response(content=json.dumps(data, default=_json_default), media_type="application/json")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for table_name, rows in data.items():
            csv_buffer = io.StringIO()
            if rows:
                writer = csv.DictWriter(csv_buffer, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: _json_default(v) if v is not None else "" for k, v in row.items()})
            zf.writestr(f"{table_name}.csv", csv_buffer.getvalue())
    buffer.seek(0)

    return StreamingResponse(
        buffer, media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=arx_export.zip"},
    )
