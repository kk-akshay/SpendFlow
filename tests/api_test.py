"""End-to-end API test using FastAPI's TestClient against a throwaway data dir."""
import os, sys, tempfile, json
from pathlib import Path
tmp = tempfile.mkdtemp()
# Never let a synthetic API test access Neon PostgreSQL or private S3 storage.
# SPENDFLOW_DATA takes precedence over the legacy TALLY_DATA setting.
for key in (
    "DATABASE_URL",
    "SPENDFLOW_S3_BUCKET", "SPENDFLOW_S3_ENDPOINT",
    "SPENDFLOW_S3_ACCESS_KEY", "SPENDFLOW_S3_SECRET_KEY",
    "SPENDFLOW_S3_REGION",
):
    os.environ.pop(key, None)
os.environ["SPENDFLOW_DATA"] = tmp
os.environ["TALLY_DATA"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from backend.main import app

H = {"x-requested-with": "tally"}
c = TestClient(app, headers=H)
S = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/samples")
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond: fails.append(name)

# auth
check("unauthenticated is 401", c.get("/api/dashboard").status_code == 401)
check("csrf header required", TestClient(app).post("/api/auth/login", json={"email":"a@b.co","password":"x"}).status_code == 403)
check("short password rejected", c.post("/api/auth/register", json={"email":"t@e.st","password":"123"}).status_code == 400)
r = c.post("/api/auth/register", json={"email":"t@e.st","password":"password123"}); check("register", r.status_code == 200)
check("duplicate email rejected", c.post("/api/auth/register", json={"email":"t@e.st","password":"password123"}).status_code == 409)
check("me", c.get("/api/auth/me").json()["email"] == "t@e.st")
cats = {x["name"]: x for x in c.get("/api/categories").json()}; check("16 default categories", len(cats) == 16)

def upload(name, **form):
    with open(S/name, "rb") as f:
        return c.post("/api/imports", files=[("files", (name, f, "application/pdf"))], data=form).json()["results"][0]

# bad uploads
bad = c.post("/api/imports", files=[("files", ("x.pdf", b"not a pdf at all", "application/pdf"))]).json()["results"][0]
check("fake pdf rejected by content sniffing", not bad["ok"] and "supported" in bad["error"])

# import HDFC statement
r = upload("hdfc_ruled.pdf"); check("import hdfc", r["ok"] and r["count"] == 45, r)
sid = r["statement_id"]
check("same file twice is refused", "already uploaded" in upload("hdfc_ruled.pdf").get("error", ""))
pv = c.get(f"/api/imports/{sid}").json()
check("preview has 45 rows", pv["summary"]["count"] == 45)
check("nothing counts before confirm", c.get("/api/dashboard").json()["empty"] is True)
check("review queue empty before confirm", c.get("/api/review/next").json()["item"] is None)
row = pv["rows"][0]
check("edit staged row", c.patch(f"/api/imports/rows/{row['id']}", json={"description":"CORRECTED SALARY NARRATION"}).status_code == 200)
cm = c.post(f"/api/imports/{sid}/commit").json(); check("commit", cm["imported"] == 45, cm)
check("cannot commit twice", c.post(f"/api/imports/{sid}/commit").status_code == 404)

# review flow
st = c.get("/api/review/next").json()
check("progress 0 of 45", st["progress"] == {"total":45,"reviewed":0,"skipped":0,"pending":45}, st["progress"])
first = st["item"]
newest = c.get("/api/transactions?sort=date_desc&limit=1").json()["items"][0]
oldest = c.get("/api/review/next?order=asc").json()["item"]["txn"]
check("review defaults to newest", first["txn"]["id"] == newest["id"])
check("ascending review starts oldest", oldest["date"] <= first["txn"]["date"])
check("corrected imported narration preserved", "CORRECTED" in c.get(f"/api/transactions/{row['id']}").json()["txn"]["description"])
check("review includes suggestion field", "suggestion" in first)
inc = cats["Income"]["id"]
r = c.post(f"/api/review/{first['txn']['id']}/categorize", json={"category_id": inc, "note":"august salary"}).json()
check("categorise advances", r["progress"]["reviewed"] == 1 and r["item"]["txn"]["id"] != first["txn"]["id"])
undo = r["undo"]
r = c.post("/api/review/restore", json={"undo": undo}).json()
check("undo restores the same card", r["item"]["txn"]["id"] == first["txn"]["id"] and r["progress"]["reviewed"] == 0)
c.post(f"/api/review/{first['txn']['id']}/categorize", json={"category_id": inc})

# skip then queue
n = c.get("/api/review/next").json()["item"]
r = c.post(f"/api/review/{n['txn']['id']}/skip").json()
check("skip moves on and counts", r["progress"]["skipped"] == 1 and r["item"]["txn"]["id"] != n["txn"]["id"])
sk = c.get("/api/review/next?scope=skipped").json()
check("skipped queue returns it", sk["item"]["txn"]["id"] == n["txn"]["id"])

# split validation
n2 = c.get("/api/review/next").json()["item"]["txn"]; amt = n2["amount_minor"]
bad = c.post(f"/api/review/{n2['id']}/categorize", json={"splits":[{"category_id":cats["Food"]["id"],"amount_minor":1},{"category_id":cats["Other"]["id"],"amount_minor":1}]})
check("split must sum to total", bad.status_code == 400, bad.text)
a = amt // 3; ok = c.post(f"/api/review/{n2['id']}/categorize", json={"splits":[{"category_id":cats["Food"]["id"],"amount_minor":a},{"category_id":cats["Groceries"]["id"],"amount_minor":amt-a}]})
check("valid split saved", ok.status_code == 200)
t = c.get(f"/api/transactions/{n2['id']}").json()["txn"]; check("split stored with 2 parts", len(t["splits"]) == 2 and t["status"] == "categorized")

# learn from history + apply similar
sw = [x for x in c.get("/api/transactions?q=swiggy&status=pending").json()["items"]]
if len(sw) >= 2:
    r = c.post(f"/api/review/{sw[0]['id']}/categorize", json={"category_id": cats["Food"]["id"], "apply_similar": True}).json()
    check("apply to similar", r["applied_similar"] == len(sw)-1, r["applied_similar"])

# dashboard
d = c.get("/api/dashboard").json()
check("dashboard has data", not d["empty"] and d["income_minor"] > 0 and d["expense_minor"] > 0)
check("uncategorized counted", d["uncategorized"]["count"] > 0)
check("insights present", len(d["insights"]) > 0)

# cross-account import: GPay overlaps -> suspected duplicates + transfer detection
g = upload("gpay.pdf"); check("import gpay", g["ok"] and g["count"] == 8, g)
gp = c.get(f"/api/imports/{g['statement_id']}").json()
check("gpay account auto-created", gp["statement"]["account_name"] == "Google Pay")
gcm = c.post(f"/api/imports/{g['statement_id']}/commit").json(); check("gpay commit", gcm["imported"] == 8, gcm)
accts = c.get("/api/accounts").json(); check("two accounts", len(accts) == 2)

# second statement overlapping first: Federal-format copy of same transactions in another account
p = upload("plain_dr_cr.pdf", new_account_name="Federal Bank")
check("overlapping statement imports", p["ok"], p)
pp = c.get(f"/api/imports/{p['statement_id']}").json()
check("overlap flagged as suspected duplicates (different account)", pp["summary"]["suspected_duplicates"] > 20, pp["summary"])
cm2 = c.post(f"/api/imports/{p['statement_id']}/commit").json()
dups = c.get("/api/duplicates").json(); check("duplicates list populated", len(dups) > 20, len(dups))
before = c.get("/api/dashboard").json()["expense_minor"]
res = c.post("/api/duplicates/resolve-all", json={"action":"delete"}).json()
check("resolve all", res["changed"] == len(dups))
check("totals unchanged after deleting duplicates", c.get("/api/dashboard").json()["expense_minor"] == before)

# budgets, goals, recurring
check("set budget", c.put("/api/budgets", json={"category_id": cats["Food"]["id"], "limit_minor": 500000}).status_code == 200)
check("set overall", c.put("/api/budgets", json={"category_id": None, "limit_minor": 5000000}).status_code == 200)
bd = c.get("/api/budgets").json(); check("budgets listed", len(bd["items"]) == 1 and bd["overall"])
gl = c.post("/api/goals", json={"name":"Laptop","target_minor":8000000}).json()
check("goal contribute", c.post(f"/api/goals/{gl['id']}/contribute", json={"amount_minor":1000000}).json()["saved_minor"] == 1000000)
rc = c.get("/api/recurring").json(); check("recurring endpoint", "items" in rc and "detected" in rc)

# custom category
cc = c.post("/api/categories", json={"name":"Pets","color":"#112233"}); check("custom category", cc.status_code == 200)
check("duplicate category name rejected", c.post("/api/categories", json={"name":"pets"}).status_code == 409)

# search / export
s = c.get("/api/transactions?q=bigbasket&sort=amount_desc").json(); check("search", s["total"] > 0)
check("export csv", c.get("/api/export.csv").text.startswith("date,account"))

# isolation between users
c2 = TestClient(app, headers=H); c2.post("/api/auth/register", json={"email":"other@e.st","password":"password123"})
check("other user sees nothing", c2.get("/api/dashboard").json()["empty"] is True)
check("other user can't read my txn", c2.get(f"/api/transactions/{n2['id']}").status_code == 404)
check("other user can't read my statement file", c2.get(f"/api/statements/{sid}/file").status_code == 404)
check("other user can't categorise my txn", c2.post(f"/api/review/{n2['id']}/categorize", json={"category_id": 1}).status_code in (400, 404))

# delete flows
files_before = len(list(Path(tmp, "uploads").rglob("*.*")))
check("delete statement + its transactions", c.delete(f"/api/statements/{sid}?transactions=true").status_code == 200)
check("file removed from disk", len(list(Path(tmp, "uploads").rglob("*.*"))) == files_before - 1)
check("wrong password blocks account deletion", c.post("/api/auth/delete-account", json={"password":"nope"}).status_code == 401)
check("account deletion", c.post("/api/auth/delete-account", json={"password":"password123"}).status_code == 200)
check("after deletion session is dead", c.get("/api/auth/me").status_code == 401)
check("login fails after deletion", c.post("/api/auth/login", json={"email":"t@e.st","password":"password123"}).status_code == 401)
print("\n%d failure(s)" % len(fails), fails)
