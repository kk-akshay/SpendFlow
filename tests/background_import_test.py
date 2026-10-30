"""Regression: background PDF import does not keep HTTP request open."""
from __future__ import annotations
import os
import tempfile
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp = tempfile.TemporaryDirectory()
os.environ.pop("DATABASE_URL", None)
os.environ["SPENDFLOW_DATA"] = _tmp.name

from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app, headers={"x-requested-with": "spendflow"}) as client:
    r = client.post("/api/auth/register", json={"email": "jobs@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    sample = Path("tests/samples/hdfc_ruled.pdf").read_bytes()
    r = client.post("/api/imports/jobs", files={"files": ("statement.pdf", sample, "application/pdf")})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    status = None
    for _ in range(160):
        r = client.get(f"/api/imports/jobs/{job_id}")
        assert r.status_code == 200, r.text
        status = r.json()
        if status["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert status["status"] == "done", status
    result = status["results"][0]
    assert result["ok"] and result["count"] == 45, result
    preview = client.get(f"/api/imports/{result['statement_id']}")
    assert preview.status_code == 200 and preview.json()["summary"]["count"] == 45, preview.text
    # A different user must not be able to fetch job results or private file information.
    with TestClient(app, headers={"x-requested-with":"spendflow"}) as other:
        assert other.post("/api/auth/register", json={"email":"other@example.com","password":"password123"}).status_code == 200
        assert other.get(f"/api/imports/jobs/{job_id}").status_code == 404
    commit = client.post(f"/api/imports/{result['statement_id']}/commit-job")
    assert commit.status_code == 202, commit.text
    for _ in range(160):
        confirmed = client.get("/api/imports/jobs/" + commit.json()["job_id"]).json()
        if confirmed["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert confirmed["status"] == "done", confirmed
    assert confirmed["commit_result"]["imported"] == 45, confirmed
    assert client.get("/api/review/next").json()["progress"]["total"] == 45
print("Background import job regression checks passed")
