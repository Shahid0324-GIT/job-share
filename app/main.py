from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, engine, get_db
from app.extraction import extract_metadata
from app.models import Batch, BatchJob, Friend, FriendJob, Job
from app.schemas import BatchInput, FriendInput, JobInput, JobPreviewInput, JobSaveInput, StatusInput
from app.security import decrypt_token, encrypt_token, hash_token, make_session, new_token, normalize_url, valid_session

app = FastAPI(title="JobShare")
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key, https_only=get_settings().secure_cookies, same_site="lax")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def admin_required(request: Request) -> None:
    if not valid_session(request.cookies.get("admin_session"), "admin"):
        raise HTTPException(status_code=401, detail="Unauthorized.")


def csrf_required(request: Request, token: str | None = None) -> None:
    expected = request.session.get("csrf")
    supplied = token or request.headers.get("X-CSRF-Token")
    if not expected or supplied != expected:
        raise HTTPException(status_code=403, detail="Invalid request.")


def public_friend(request: Request, db: Session) -> Friend:
    token = request.cookies.get("friend_token")
    if not token:
        raise HTTPException(status_code=401, detail="This JobShare link is invalid or has been revoked.")
    friend = db.scalar(select(Friend).where(Friend.active.is_(True), Friend.token_hash == hash_token(token)))
    if not friend:
        raise HTTPException(status_code=401, detail="This JobShare link is invalid or has been revoked.")
    return friend


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": None})


@app.post("/admin/login")
def login(request: Request, password: str = Form(...)):
    if not __import__("hmac").compare_digest(password, get_settings().admin_password):
        return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": "Unauthorized."}, status_code=401)
    request.session["csrf"] = new_token()
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("admin_session", make_session("admin"), httponly=True, secure=get_settings().secure_cookies, samesite="lax")
    return response


@app.post("/admin/logout")
def logout(request: Request, csrf: str = Form(...)):
    csrf_required(request, csrf)
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    request.session.clear()
    return response


def group_jobs_by_date(jobs: list[Job]) -> list[dict]:
    groups: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    today_date = now.date()
    yesterday_date = today_date - timedelta(days=1)

    for job in jobs:
        created = job.created_at
        if created is None:
            created = now
        elif created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        job_date = created.date()
        date_key = job_date.isoformat()

        if date_key not in groups:
            if job_date == today_date:
                title = f"Today · {created.strftime('%B %d, %Y')}"
            elif job_date == yesterday_date:
                title = f"Yesterday · {created.strftime('%B %d, %Y')}"
            else:
                title = created.strftime("%B %d, %Y")

            groups[date_key] = {
                "date_key": date_key,
                "title": title,
                "jobs": [],
            }
        groups[date_key]["jobs"].append(job)

    return list(groups.values())


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    jobs = db.scalars(select(Job).where(Job.archived_at.is_(None)).order_by(Job.created_at.desc()).limit(100)).all()
    job_groups = group_jobs_by_date(jobs)
    friends = db.scalars(select(Friend).order_by(Friend.name)).all()
    batches = db.scalars(select(Batch).options(joinedload(Batch.jobs)).order_by(Batch.created_at.desc())).unique().all()
    return templates.TemplateResponse(
        request=request,
        name="admin/index.html",
        context={
            "jobs": jobs,
            "job_groups": job_groups,
            "friends": friends,
            "batches": batches,
            "csrf": request.session.get("csrf"),
            "base_url": str(request.base_url).rstrip("/"),
        },
    )


@app.post("/api/admin/jobs/preview")
def preview_job(payload: JobPreviewInput, request: Request):
    admin_required(request)
    csrf_required(request)
    try:
        url = normalize_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    extracted = extract_metadata(url)
    return {"url": url, "company": extracted.company, "role": extracted.role, "location": extracted.location, "source": extracted.source, "description": extracted.description, "confidence": extracted.confidence, "warnings": extracted.warnings}


@app.post("/api/admin/jobs")
def add_job(payload: JobSaveInput, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    try:
        url = normalize_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if db.scalar(select(Job).where(Job.url == url)):
        raise HTTPException(409, "This job has already been added.")
    job = Job(url=url, source=payload.source, company=payload.company, role=payload.role, location=payload.location, description=payload.description)
    db.add(job)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This job has already been added.") from exc
    db.refresh(job)
    return {"job": job.id, "warnings": []}


@app.patch("/api/admin/jobs/{job_id}")
def edit_job(job_id: str, payload: JobSaveInput, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    job.url = normalize_url(str(payload.url))
    collision = db.scalar(select(Job).where(Job.url == job.url, Job.id != job_id))
    if collision:
        raise HTTPException(409, "This job has already been added.")
    for field in ("company", "role", "location", "source", "description"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(job, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This job has already been added.") from exc
    return {"status": "ok"}


@app.delete("/api/admin/jobs/{job_id}")
def archive_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    job.archived_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}


@app.post("/api/admin/jobs/{job_id}/restore")
def restore_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    job.archived_at = None
    db.commit()
    return {"status": "ok"}


@app.post("/api/admin/friends")
def add_friend(payload: FriendInput, request: Request, db: Session = Depends(get_db)):
    admin_required(request); csrf_required(request)
    token = new_token()
    friend = Friend(name=payload.name.strip(), token_hash=hash_token(token), token_encrypted=encrypt_token(token))
    db.add(friend); db.commit(); db.refresh(friend)
    return {"id": friend.id, "name": friend.name, "token": token}


@app.post("/api/admin/friends/{friend_id}/regenerate")
def regenerate_friend(friend_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request); csrf_required(request)
    friend = db.get(Friend, friend_id)
    if not friend: raise HTTPException(404, "Friend not found.")
    token = new_token(); friend.token_hash = hash_token(token); friend.token_encrypted = encrypt_token(token); friend.active = True
    db.commit()
    return {"token": token}


@app.post("/api/admin/friends/{friend_id}/link")
def copy_friend_link(friend_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    friend = db.get(Friend, friend_id)
    if not friend:
        raise HTTPException(404, "Friend not found.")
    token = decrypt_token(friend.token_encrypted) if friend.token_encrypted else None
    if not token:
        raise HTTPException(409, "This friend was created before recoverable links were enabled. Regenerate the link first.")
    return {"url": f"{str(request.base_url).rstrip('/')}/u/{token}"}


@app.patch("/api/admin/friends/{friend_id}")
def edit_friend(friend_id: str, payload: FriendInput, request: Request, db: Session = Depends(get_db)):
    admin_required(request); csrf_required(request)
    friend = db.get(Friend, friend_id)
    if not friend: raise HTTPException(404, "Friend not found.")
    friend.name = payload.name.strip(); db.commit()
    return {"status": "ok"}


@app.delete("/api/admin/friends/{friend_id}")
def deactivate_friend(friend_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request); csrf_required(request)
    friend = db.get(Friend, friend_id)
    if not friend: raise HTTPException(404, "Friend not found.")
    friend.active = False; db.commit()
    return {"status": "ok"}


@app.post("/api/admin/batches")
def add_batch(payload: BatchInput, request: Request, db: Session = Depends(get_db)):
    admin_required(request); csrf_required(request)
    jobs = db.scalars(select(Job).where(Job.id.in_(payload.job_ids), Job.archived_at.is_(None))).all()
    if len(jobs) != len(set(payload.job_ids)): raise HTTPException(400, "Select valid jobs.")
    today = datetime.now(timezone.utc)
    batch = Batch(name=payload.name or f"{today.strftime('%B')} {today.day} Jobs")
    batch.jobs = jobs
    db.add(batch)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(400, "A job was selected more than once.")
    return {"id": batch.id}


@app.delete("/api/admin/batches/{batch_id}")
def delete_batch(batch_id: str, request: Request, db: Session = Depends(get_db)):
    admin_required(request)
    csrf_required(request)
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found.")
    db.query(BatchJob).filter(BatchJob.batch_id == batch_id).delete(synchronize_session=False)
    db.delete(batch)
    db.commit()
    return {"status": "ok"}


@app.get("/u/{token}", response_class=HTMLResponse)
def friend_link(token: str, request: Request, db: Session = Depends(get_db)):
    friend = db.scalar(select(Friend).where(Friend.active.is_(True), Friend.token_hash == hash_token(token)))
    if not friend: raise HTTPException(404, "This JobShare link is invalid or has been revoked.")
    response = RedirectResponse("/u", status_code=303)
    response.set_cookie("friend_token", token, httponly=True, secure=get_settings().secure_cookies, samesite="lax", max_age=60 * 60 * 24 * 365)
    return response


@app.get("/u", response_class=HTMLResponse)
def friend_page(request: Request, db: Session = Depends(get_db)):
    friend = public_friend(request, db)
    jobs = db.scalars(select(Job).join(BatchJob).join(Batch).where(BatchJob.job_id == Job.id, Job.archived_at.is_(None)).order_by(BatchJob.added_at.desc())).unique().all()
    statuses = {item.job_id: item.status for item in db.scalars(select(FriendJob).where(FriendJob.friend_id == friend.id)).all()}
    return templates.TemplateResponse(request=request, name="public/jobs.html", context={"friend": friend, "jobs": jobs, "statuses": statuses})


@app.patch("/api/public/jobs/{job_id}/status")
def update_status(job_id: str, payload: StatusInput, request: Request, db: Session = Depends(get_db)):
    friend = public_friend(request, db)
    job = db.scalar(select(Job).join(BatchJob).where(Job.id == job_id, Job.archived_at.is_(None)))
    if not job: raise HTTPException(404, "Job not found.")
    item = db.get(FriendJob, {"friend_id": friend.id, "job_id": job_id})
    if not item:
        item = FriendJob(friend_id=friend.id, job_id=job_id)
        db.add(item)
    item.status = payload.status; item.updated_at = datetime.now(timezone.utc); db.commit()
    return {"status": item.status}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)
