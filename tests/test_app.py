import os
import re

os.environ["DATABASE_URL"] = "sqlite:///./test-api.db"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret"

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.extraction import ExtractionResult
from app.models import Batch, BatchJob, Friend, FriendJob, Job
from app.main import app, group_jobs_by_date
import app.main as main_module
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


def admin_csrf(client: TestClient) -> str:
    client.post("/admin/login", data={"password": "test-password"})
    page = client.get("/admin")
    csrf_match = re.search(r'window\.JOBSHARE=\{csrf:(.*?),baseUrl:', page.text)
    assert csrf_match is not None
    return csrf_match.group(1).strip('"')


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
        csrf = admin_csrf(client)
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
        csrf = admin_csrf(client)
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


def test_preview_does_not_save_until_explicit_save(monkeypatch):
    monkeypatch.setattr(main_module, "extract_metadata", lambda url: ExtractionResult(company="Acme", role="Engineer", location="Remote", source="Company Careers", confidence="HIGH"))
    with TestClient(app) as client:
        csrf = admin_csrf(client)
        preview = client.post("/api/admin/jobs/preview", json={"url": "https://example.com/preview-job"}, headers={"X-CSRF-Token": csrf})
        assert preview.status_code == 200
        assert TestingSession().scalar(__import__("sqlalchemy").select(Job).where(Job.url == "https://example.com/preview-job")) is None
        saved = client.post("/api/admin/jobs", json=preview.json(), headers={"X-CSRF-Token": csrf})
        assert saved.status_code == 200


def test_friend_copy_regenerate_and_deactivate_lifecycle():
    with TestClient(app) as client:
        csrf = admin_csrf(client)
        created = client.post("/api/admin/friends", json={"name": "Lifecycle"}, headers={"X-CSRF-Token": csrf}).json()
        token = created["token"]
        copied = client.post(f"/api/admin/friends/{created['id']}/link", headers={"X-CSRF-Token": csrf})
        assert copied.status_code == 200 and copied.json()["url"].endswith(token)
        assert client.get(f"/u/{token}", follow_redirects=False).status_code == 303
        regenerated = client.post(f"/api/admin/friends/{created['id']}/regenerate", headers={"X-CSRF-Token": csrf}).json()
        assert regenerated["token"] != token
        assert client.get(f"/u/{token}", follow_redirects=False).status_code == 404
        assert client.get(f"/u/{regenerated['token']}", follow_redirects=False).status_code == 303
        assert client.delete(f"/api/admin/friends/{created['id']}", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get(f"/u/{regenerated['token']}", follow_redirects=False).status_code == 404


def test_archived_job_is_retained_but_cannot_be_batched():
    db = TestingSession()
    job = Job(url="https://example.com/archive-job", source="Company Careers", role="Engineer")
    friend = Friend(name="History", token_hash=hash_token(new_token()))
    db.add_all([job, friend]); db.flush()
    db.add(FriendJob(friend_id=friend.id, job_id=job.id, status="APPLIED")); db.commit(); job_id = job.id; friend_id = friend.id; db.close()
    with TestClient(app) as client:
        csrf = admin_csrf(client)
        assert client.delete(f"/api/admin/jobs/{job_id}", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.post("/api/admin/batches", json={"name": "Archived", "job_ids": [job_id]}, headers={"X-CSRF-Token": csrf}).status_code == 400
    db = TestingSession()
    archived = db.get(Job, job_id)
    assert archived is not None and archived.archived_at is not None
    history = db.get(FriendJob, {"friend_id": friend_id, "job_id": job_id})
    assert history is not None and history.status == "APPLIED"
    db.close()


def test_group_jobs_by_date():
    now = datetime.now(timezone.utc)
    job_today_1 = Job(url="https://example.com/job1", source="Company Careers", role="Role 1", created_at=now)
    job_today_2 = Job(url="https://example.com/job2", source="Company Careers", role="Role 2", created_at=now - timedelta(hours=1))
    job_yesterday = Job(url="https://example.com/job3", source="Company Careers", role="Role 3", created_at=now - timedelta(days=1))
    job_older = Job(url="https://example.com/job4", source="Company Careers", role="Role 4", created_at=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc))

    groups = group_jobs_by_date([job_today_1, job_today_2, job_yesterday, job_older])
    assert len(groups) == 3
    assert groups[0]["title"].startswith("Today")
    assert len(groups[0]["jobs"]) == 2
    assert groups[1]["title"].startswith("Yesterday")
    assert len(groups[1]["jobs"]) == 1
    assert groups[2]["title"] == "January 15, 2025"
    assert len(groups[2]["jobs"]) == 1


def test_admin_page_renders_date_groups_and_select_all():
    db = TestingSession()
    now = datetime.now(timezone.utc)
    job1 = Job(url="https://example.com/date-job-1", source="Company Careers", role="Frontend Engineer", created_at=now)
    job2 = Job(url="https://example.com/date-job-2", source="Company Careers", role="Backend Engineer", created_at=now - timedelta(days=2))
    db.add_all([job1, job2])
    db.commit()
    db.close()

    with TestClient(app) as client:
        client.post("/admin/login", data={"password": "test-password"})
        response = client.get("/admin")
        assert response.status_code == 200
        assert "date-group" in response.text
        assert "date-separator" in response.text
        assert "date-select-all" in response.text
        assert "Frontend Engineer" in response.text
        assert "Backend Engineer" in response.text
        jobs_panel_start = response.text.find('data-panel="jobs"')
        add_panel_start = response.text.find('class="panel add-panel"')
        friends_panel_start = response.text.find('data-panel="friends"')
        assert jobs_panel_start < add_panel_start < friends_panel_start


def test_admin_job_card_shows_in_batch_badge():
    db = TestingSession()
    job = Job(url="https://example.com/batched-job-test", source="Company Careers", role="Staff Architect")
    db.add(job)
    db.flush()
    batch = Batch(name="Evening Batch Alpha", jobs=[job])
    db.add(batch)
    db.commit()
    db.close()

    with TestClient(app) as client:
        client.post("/admin/login", data={"password": "test-password"})
        response = client.get("/admin")
        assert response.status_code == 200
        assert "batch-badge" in response.text
        assert "In batch" in response.text
        assert "Evening Batch Alpha" in response.text


def test_friend_feed_batch_groups_and_filter_pills():
    token = new_token()
    db = TestingSession()
    friend = Friend(name="FeedTester", token_hash=hash_token(token))
    job1 = Job(url="https://example.com/feed-job-1", source="Company Careers", role="Senior Dev")
    job2 = Job(url="https://example.com/feed-job-2", source="Company Careers", role="Junior Dev")
    db.add_all([friend, job1, job2])
    db.flush()
    batch1 = Batch(name="Batch 1", jobs=[job1])
    batch2 = Batch(name="Batch 2", jobs=[job2])
    db.add_all([batch1, batch2])
    db.commit()
    db.close()

    with TestClient(app) as client:
        client.get(f"/u/{token}", follow_redirects=False)
        response = client.get("/u")
        assert response.status_code == 200
        assert "filter-bar" in response.text
        assert "filter-pill" in response.text
        assert "Latest Batch" in response.text
        assert "Not applied" in response.text
        assert "batch-group" in response.text
        assert "Batch 1" in response.text
        assert "Batch 2" in response.text
        assert "Senior Dev" in response.text
        assert "Junior Dev" in response.text