import os

os.environ["DATABASE_URL"] = "sqlite:///./test-api.db"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import Batch, BatchJob, Friend, FriendJob, Job
from app.main import app
from app.security import hash_token, new_token

engine = create_engine("sqlite:///./test-api.db")
TestingSession = sessionmaker(bind=engine)
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


def test_admin_requires_login():
    with TestClient(app) as client:
        assert client.get("/admin").status_code == 401


def test_health_and_login():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post("/admin/login", data={"password": "test-password"}, follow_redirects=False)
        assert response.status_code == 303
        assert client.get("/admin").status_code == 200


def test_friend_status_is_private():
    token_a, token_b = new_token(), new_token()
    db = TestingSession()
    job = Job(url="https://example.com/private-job", source="Company Careers", role="Engineer")
    friend_a = Friend(name="A", token_hash=hash_token(token_a))
    friend_b = Friend(name="B", token_hash=hash_token(token_b))
    db.add_all([job, friend_a, friend_b]); db.flush()
    batch = Batch(name="Today", jobs=[job]); db.add(batch)
    db.add(FriendJob(friend_id=friend_a.id, job_id=job.id, status="APPLIED")); db.commit(); db.close()
    with TestClient(app) as client:
        assert client.get(f"/u/{token_b}", follow_redirects=False).status_code == 303
        page = client.get("/u")
        assert "Engineer" in page.text
        assert "Applied" not in page.text


def test_batch_deletion_preserves_job():
    db = TestingSession()
    job = Job(url="https://example.com/batch-job", source="Company Careers", role="Engineer")
    db.add(job); db.flush()
    batch = Batch(name="Today", jobs=[job]); db.add(batch); db.commit(); batch_id = batch.id; job_id = job.id; db.close()
    with TestClient(app) as client:
        client.post("/admin/login", data={"password": "test-password"})
        csrf = client.cookies.get("session")
        # The admin session's CSRF value is rendered in the page, not stored in a public cookie.
        page = client.get("/admin")
        import re
        csrf_match = re.search(r'window\.JOBSHARE=\{csrf:(.*?),baseUrl:', page.text)
        assert csrf_match is not None
        csrf = csrf_match.group(1).strip('"')
        response = client.delete(f"/api/admin/batches/{batch_id}", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200
    db = TestingSession()
    assert db.get(Batch, batch_id) is None
    assert db.get(Job, job_id) is not None
    db.close()


def test_friend_can_be_renamed_and_deactivated():
    token = new_token()
    db = TestingSession()
    friend = Friend(name="Old name", token_hash=hash_token(token))
    db.add(friend); db.commit(); friend_id = friend.id; db.close()
    with TestClient(app) as client:
        client.post("/admin/login", data={"password": "test-password"})
        page = client.get("/admin")
        import re
        csrf_match = re.search(r'window\.JOBSHARE=\{csrf:(.*?),baseUrl:', page.text)
        assert csrf_match is not None
        csrf = csrf_match.group(1).strip('"')
        renamed = client.patch(f"/api/admin/friends/{friend_id}", json={"name": "New name"}, headers={"X-CSRF-Token": csrf})
        assert renamed.status_code == 200
        revoked = client.delete(f"/api/admin/friends/{friend_id}", headers={"X-CSRF-Token": csrf})
        assert revoked.status_code == 200
    db = TestingSession()
    stored = db.get(Friend, friend_id)
    assert stored is not None
    assert stored.name == "New name"
    assert stored.active is False
    db.close()