import os
import tempfile
import csv
import io
import json
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

if sys.stdout is None:  # --noconsole build has no console
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

FROZEN = getattr(sys, "frozen", False)
BASE = Path(sys._MEIPASS) if FROZEN else Path(__file__).parent  # bundled files
DATA = Path(sys.executable).parent if FROZEN else BASE  # tasks.db sits next to the exe
DB = DATA / "tasks.db"
EXPORT = DATA / "powerbi"  # CSV files for Power BI
URL = "http://127.0.0.1:8000"
MORNING_HOUR = 9  # daily summary time (24h)
EVENING_HOUR = 18  # evening check-in for the day plan (24h)
EXPORT_ENABLED = False  # True = keep CSV copies of your data in the powerbi folder (off for privacy)


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, notes TEXT DEFAULT '', due TEXT,
            priority TEXT DEFAULT 'Medium', category TEXT DEFAULT '',
            done INTEGER DEFAULT 0, reminders TEXT DEFAULT '[60]',
            fired TEXT DEFAULT '[]', snooze_until TEXT,
            repeat TEXT DEFAULT '', created TEXT)""")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS plan_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, day TEXT NOT NULL,
            text TEXT NOT NULL, done INTEGER DEFAULT 0, done_on TEXT, orig_day TEXT,
            carried INTEGER DEFAULT 0, created TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, client TEXT DEFAULT '',
            status TEXT DEFAULT 'Active', due TEXT, notes TEXT DEFAULT '', created TEXT)""")
        have = [r["name"] for r in c.execute("PRAGMA table_info(tasks)")]
        for col, typ in (("project_id", "INTEGER"), ("completed_on", "TEXT"),
                         ("postponed", "INTEGER DEFAULT 0"), ("orig_due", "TEXT")):
            if col not in have:
                c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ}")  # keeps old tasks
        pcols = [r["name"] for r in c.execute("PRAGMA table_info(projects)")]
        for col, typ in (("start_date", "TEXT"), ("senior", "TEXT DEFAULT ''"), ("analyst", "TEXT DEFAULT ''"),
                         ("extra", "TEXT DEFAULT ''"), ("updates", "TEXT DEFAULT '[]'"),
                         ("calls", "TEXT DEFAULT '[]'"), ("reminders", "TEXT DEFAULT '[1440,120]'"),
                         ("pfired", "TEXT DEFAULT '[]'"), ("hold_log", "TEXT DEFAULT '[]'"), ("completed_on", "TEXT"), ("fb_next", "TEXT"),
                         ("feedback", "TEXT DEFAULT ''"), ("feedback_on", "TEXT")):
            if col not in pcols:
                c.execute(f"ALTER TABLE projects ADD COLUMN {col} {typ}")


def notify(title, msg):
    print(f"[ALERT] {title}: {msg}")
    try:
        from winotify import Notification, audio
        n = Notification(app_id="Task Manager", title=title, msg=msg, launch=URL)
        n.set_audio(audio.Default, loop=False)
        n.add_actions(label="Open tasks", launch=URL)
        n.show()
    except Exception as e:  # not on Windows or winotify missing
        print("  (desktop notification unavailable:", e, ")")


def human(delta):
    m = int(abs(delta.total_seconds()) // 60)
    if m < 60:
        return f"{m} min"
    if m < 1440:
        return f"{m // 60} hr {m % 60} min" if m % 60 else f"{m // 60} hr"
    d = m // 1440
    return f"{d} day{'s' if d > 1 else ''}"


def roll_plan():
    """Plan items left unchecked on an earlier day move to today (only for Active projects)."""
    today = datetime.now().date().isoformat()
    with db() as c:
        c.execute("""UPDATE plan_items SET carried=carried+CAST(julianday(?)-julianday(day) AS INTEGER), day=?
                     WHERE done=0 AND day<? AND project_id IN (SELECT id FROM projects WHERE status='Active')""",
                  (today, today, today))


def prow(r):
    d = dict(r)
    for k in ("updates", "calls", "reminders", "pfired", "hold_log"):
        d[k] = json.loads(d.get(k) or "[]")
    return d


def p_events(d):
    ev = []
    for kind, items in (("Update", d["updates"]), ("Call", d["calls"])):
        for i in items:
            if i.get("when") and i.get("status", "pending") == "pending":  # done / not needed: no alerts
                ev.append((kind, i.get("label") or f"Project {kind.lower()}", datetime.fromisoformat(i["when"])))
    if d.get("due"):  # a due date counts as end of day (17:00)
        ev.append(("Due", "Project due date", datetime.fromisoformat(d["due"][:10]).replace(hour=17)))
    return ev


def triggers(d):
    for kind, label, when in p_events(d):
        for off in d["reminders"]:
            key = f"{kind}|{when.isoformat(timespec='minutes')}|{off}"
            yield key, kind, label, when, when - timedelta(minutes=off)


def check():
    now = datetime.now()
    with db() as c:
        for t in c.execute("SELECT * FROM tasks WHERE done=0").fetchall():
            # snoozed reminder
            if t["snooze_until"] and now >= datetime.fromisoformat(t["snooze_until"]):
                due = f" (due {t['due'].replace('T', ' ')})" if t["due"] else ""
                notify("Snoozed reminder", t["title"] + due)
                c.execute("UPDATE tasks SET snooze_until=NULL WHERE id=?", (t["id"],))
            if not t["due"]:
                continue
            due = datetime.fromisoformat(t["due"])
            fired = json.loads(t["fired"])
            hit = [o for o in json.loads(t["reminders"])
                   if o not in fired and now >= due - timedelta(minutes=o)]
            if hit:
                fired += hit
                c.execute("UPDATE tasks SET fired=? WHERE id=?", (json.dumps(fired), t["id"]))
                when = (f"Due in {human(due - now)}" if due > now
                        else f"Overdue by {human(now - due)}")
                notify(t["title"], when)
        # project updates, calls and due dates
        for r in c.execute("SELECT * FROM projects WHERE status='Active'").fetchall():
            d = prow(r)
            fired, hit = set(d["pfired"]), {}
            for k, kind, label, when, trig in triggers(d):
                if k not in fired and now >= trig:
                    fired.add(k)
                    if now <= when + timedelta(hours=24):  # skip long-past events
                        hit[(kind, label, when)] = 1
            if len(fired) != len(d["pfired"]):
                c.execute("UPDATE projects SET pfired=? WHERE id=?", (json.dumps(sorted(fired)), d["id"]))
            for kind, label, when in hit:
                gap = f"in {human(when - now)}" if when > now else f"{human(now - when)} ago"
                notify(f"{kind}: {label}", f"{d['name']} ({gap})")
        # client feedback reminders: every 5 days after completion until feedback is added
        for r in c.execute("SELECT id,name,fb_next FROM projects WHERE status='Completed' "
                           "AND fb_next IS NOT NULL").fetchall():
            nxt = datetime.fromisoformat(r["fb_next"])
            if now >= nxt:
                while nxt <= now:
                    nxt += timedelta(days=5)
                c.execute("UPDATE projects SET fb_next=? WHERE id=?",
                          (nxt.isoformat(timespec="minutes"), r["id"]))
                notify("Get client feedback", f"{r['name']}: add the client's feedback to stop these reminders")
        # morning summary
        today = now.strftime("%Y-%m-%d")
        last = c.execute("SELECT v FROM meta WHERE k='summary'").fetchone()
        if now.hour >= MORNING_HOUR and (not last or last["v"] != today):
            c.execute("INSERT OR REPLACE INTO meta VALUES('summary',?)", (today,))
            rows = c.execute("SELECT due FROM tasks WHERE done=0 AND due IS NOT NULL").fetchall()
            n_today = sum(1 for r in rows if r["due"][:10] == today)
            n_over = sum(1 for r in rows if datetime.fromisoformat(r["due"]) < now
                         and r["due"][:10] != today)
            n_plan = c.execute("SELECT COUNT(*) FROM plan_items i JOIN projects p ON p.id=i.project_id "
                               "WHERE p.status='Active' AND i.done=0 AND i.day=?", (today,)).fetchone()[0]
            if n_today or n_over or n_plan:
                notify("Good morning", f"{n_today} due today, {n_over} overdue, "
                                       f"{n_plan} plan item{'s' if n_plan != 1 else ''} for today")
        # evening check-in: tick off the day plan, the rest moves to tomorrow
        last_e = c.execute("SELECT v FROM meta WHERE k='evening'").fetchone()
        if now.hour >= EVENING_HOUR and (not last_e or last_e["v"] != today):
            c.execute("INSERT OR REPLACE INTO meta VALUES('evening',?)", (today,))
            n_open = c.execute("SELECT COUNT(*) FROM plan_items i JOIN projects p ON p.id=i.project_id "
                               "WHERE p.status='Active' AND i.done=0 AND i.day=?", (today,)).fetchone()[0]
            if n_open:
                notify("Evening check-in", f"{n_open} plan item{'s' if n_open != 1 else ''} still unchecked. "
                                           "Tick what you finished; the rest moves to tomorrow.")


TASKS_SQL = """SELECT t.id, t.title, COALESCE(p.name,'') AS project, COALESCE(p.client,'') AS client,
    t.category, t.priority, CASE WHEN t.done=1 THEN 'Done' ELSE 'Open' END AS status,
    COALESCE(t.due,'') AS due, COALESCE(t.created,'') AS created,
    COALESCE(t.completed_on,'') AS completed_on, t.repeat, t.notes
    FROM tasks t LEFT JOIN projects p ON p.id=t.project_id ORDER BY t.id"""
PROJ_SQL = ("SELECT id, name, client, status, COALESCE(due,'') AS due, "
            "COALESCE(created,'') AS created, notes FROM projects ORDER BY id")
_last = {}


def export_csv():
    """Keep tasks.csv and projects.csv up to date for Power BI (rewritten only on change)."""
    try:
        EXPORT.mkdir(exist_ok=True)
        with db() as c:
            for name, sql in (("tasks.csv", TASKS_SQL), ("projects.csv", PROJ_SQL)):
                cur = c.execute(sql)
                buf = io.StringIO(newline="")
                w = csv.writer(buf)
                w.writerow([d[0] for d in cur.description])
                w.writerows(cur.fetchall())
                text = buf.getvalue()
                if _last.get(name) == text and (EXPORT / name).exists():
                    continue
                tmp = EXPORT / (name + ".tmp")
                tmp.write_text(text, encoding="utf-8-sig", newline="")
                tmp.replace(EXPORT / name)
                _last[name] = text
    except Exception as e:  # e.g. file open in Power BI at that moment; retry next cycle
        print("export error:", e)


def loop():
    while True:
        try:
            roll_plan()
            check()
        except Exception as e:
            print("checker error:", e)
        if EXPORT_ENABLED:
            export_csv()
        time.sleep(30)


@asynccontextmanager
async def lifespan(_):
    init()
    threading.Thread(target=loop, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
# only answer requests addressed to this PC itself (blocks DNS-rebinding tricks from websites)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


class TaskIn(BaseModel):
    title: str
    notes: str = ""
    due: Optional[str] = None
    priority: str = "Medium"
    category: str = ""
    reminders: list[int] = [60]
    repeat: str = ""
    project_id: Optional[int] = None


def row(r):
    d = dict(r)
    d["reminders"] = json.loads(d["reminders"])
    d["done"] = bool(d["done"])
    d.pop("fired", None)
    return d


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.get("/api/tasks")
def list_tasks():
    with db() as c:
        return [row(r) for r in c.execute("SELECT * FROM tasks ORDER BY id DESC")]


@app.post("/api/tasks")
def add(t: TaskIn):
    with db() as c:
        cur = c.execute(
            "INSERT INTO tasks(title,notes,due,priority,category,reminders,repeat,project_id,created)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (t.title.strip(), t.notes, t.due or None, t.priority, t.category,
             json.dumps(sorted(set(t.reminders))), t.repeat, t.project_id, datetime.now().isoformat()))
        return {"id": cur.lastrowid}


@app.put("/api/tasks/{tid}")
def edit(tid: int, t: TaskIn):
    with db() as c:  # editing resets which reminders already fired
        c.execute(
            "UPDATE tasks SET title=?,notes=?,due=?,priority=?,category=?,reminders=?,"
            "repeat=?,project_id=?,fired='[]',snooze_until=NULL WHERE id=?",
            (t.title.strip(), t.notes, t.due or None, t.priority, t.category,
             json.dumps(sorted(set(t.reminders))), t.repeat, t.project_id, tid))
    return {"ok": True}


@app.delete("/api/tasks/{tid}")
def delete(tid: int):
    with db() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (tid,))
    return {"ok": True}


@app.post("/api/tasks/{tid}/toggle")
def toggle(tid: int):
    with db() as c:
        t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(404)
        if not t["done"] and t["repeat"] and t["due"]:  # repeating: roll forward
            step = timedelta(days=1 if t["repeat"] == "daily" else 7)
            nxt = datetime.fromisoformat(t["due"])
            while nxt <= datetime.now():
                nxt += step
            c.execute("UPDATE tasks SET due=?,fired='[]',snooze_until=NULL WHERE id=?",
                      (nxt.isoformat(timespec="minutes"), tid))
        else:
            c.execute("UPDATE tasks SET done=1-done, completed_on=CASE WHEN done=0 THEN ? ELSE NULL END WHERE id=?",
                      (datetime.now().isoformat(timespec="minutes"), tid))
    return {"ok": True}


class PostponeIn(BaseModel):
    days: Optional[int] = None
    due: Optional[str] = None


@app.post("/api/tasks/{tid}/postpone")
def postpone(tid: int, h: PostponeIn):
    with db() as c:
        t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(404)
        now = datetime.now()
        if h.due:
            try:
                new = datetime.fromisoformat(h.due)
            except ValueError:
                raise HTTPException(400, "Please give a valid date and time.")
        elif h.days and 0 < h.days <= 365:
            new = (datetime.fromisoformat(t["due"]) if t["due"]
                   else now.replace(hour=9, minute=0, second=0, microsecond=0))
            new += timedelta(days=h.days)
            while new <= now:  # never land in the past
                new += timedelta(days=1)
        else:
            raise HTTPException(400, "Please give a number of days or a date.")
        c.execute("UPDATE tasks SET due=?, orig_due=COALESCE(orig_due,?), postponed=postponed+1, "
                  "fired='[]', snooze_until=NULL WHERE id=?",
                  (new.isoformat(timespec="minutes"), t["due"], tid))
    return {"due": new.isoformat(timespec="minutes")}


@app.post("/api/tasks/{tid}/snooze")
def snooze(tid: int, minutes: int = 60):
    until = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with db() as c:
        c.execute("UPDATE tasks SET snooze_until=? WHERE id=?", (until, tid))
    return {"until": until}


class ProjectIn(BaseModel):
    name: str
    client: str = ""
    status: str = "Active"
    start_date: Optional[str] = None
    due: Optional[str] = None
    senior: str = ""
    analyst: str = ""
    extra: str = ""
    notes: str = ""
    updates: list[dict] = []
    calls: list[dict] = []
    reminders: list[int] = [1440, 120]  # 1 day and 2 hours before


def clean(items):
    return sorted(({"when": str(i["when"])[:16], "label": str(i.get("label", ""))[:200],
                    "status": i.get("status") if i.get("status") in ("done", "skipped") else "pending"}
                   for i in items if i.get("when")), key=lambda i: i["when"])


def passed_keys(d, now):
    """Reminder keys already in the past (not replayed), except one catch-up for an upcoming event."""
    passed = {}
    for k, kind, label, when, trig in triggers(d):
        if trig <= now:
            passed.setdefault((kind, when), []).append((trig, k))
    mark = []
    for (kind, when), lst in passed.items():
        lst.sort()
        mark += [k for _, k in (lst if when <= now else lst[:-1])]
    return mark


def fields(p, old_fired=()):
    d = {"updates": clean(p.updates), "calls": clean(p.calls), "due": p.due or None,
         "reminders": sorted(set(p.reminders))}
    mark = passed_keys(d, datetime.now())
    return (p.name.strip(), p.client, p.status, p.start_date or None, p.due or None,
            p.senior.strip(), p.analyst.strip(), p.extra, p.notes,
            json.dumps(d["updates"]), json.dumps(d["calls"]), json.dumps(d["reminders"]),
            json.dumps(sorted(set(old_fired) | set(mark))))


@app.get("/api/projects")
def list_projects():
    with db() as c:
        out = []
        for r in c.execute("SELECT * FROM projects ORDER BY id DESC"):
            d = prow(r)
            d.pop("pfired")
            out.append(d)
        return out


@app.post("/api/projects")
def add_project(p: ProjectIn):
    p.status = "Active"  # status only changes through the project buttons, so it is always logged
    with db() as c:
        cur = c.execute("""INSERT INTO projects(name,client,status,start_date,due,senior,analyst,extra,notes,
                           updates,calls,reminders,pfired,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        fields(p) + (datetime.now().isoformat(),))
        return {"id": cur.lastrowid}


@app.put("/api/projects/{pid}")
def edit_project(pid: int, p: ProjectIn):
    with db() as c:
        r = c.execute("SELECT pfired,status FROM projects WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        p.status = r["status"]  # status only changes through the project buttons (hold, done...)
        c.execute("""UPDATE projects SET name=?,client=?,status=?,start_date=?,due=?,senior=?,analyst=?,extra=?,
                     notes=?,updates=?,calls=?,reminders=?,pfired=? WHERE id=?""",
                  fields(p, json.loads(r["pfired"] or "[]")) + (pid,))
    return {"ok": True}


class ActionIn(BaseModel):
    action: str  # hold, resume, done, reopen, feedback
    date: str
    reason: str = ""


@app.post("/api/projects/{pid}/action")
def project_action(pid: int, h: ActionIn):
    note = h.reason.strip()
    if not note and h.action != "done":
        raise HTTPException(400, "Please fill in the reason / feedback.")
    try:
        day = datetime.fromisoformat(h.date[:10]).date()
    except ValueError:
        raise HTTPException(400, "Please give a valid date.")
    now = datetime.now()
    with db() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        d = prow(r)
        st, a, sets = d["status"], h.action, {}
        if a == "hold" and st == "Active":
            sets["status"], label = "On Hold", "Hold"
        elif a == "resume" and st == "On Hold":
            sets["status"], label = "Active", "Resume"
        elif a == "done" and st == "Active":
            first = datetime(day.year, day.month, day.day, 9) + timedelta(days=5)  # feedback reminder
            sets.update(status="Completed", completed_on=day.isoformat(), feedback="", feedback_on=None,
                        fb_next=first.isoformat(timespec="minutes"))
            label = "Done"
        elif a == "reopen" and st == "Completed":
            sets.update(status="Active", completed_on=None, fb_next=None)
            label = "Reopen"
        elif a == "feedback" and st == "Completed":
            sets.update(feedback=note[:2000], feedback_on=day.isoformat(), fb_next=None)
            label = "Feedback"
        else:
            raise HTTPException(400, "That change isn't possible for this project right now.")
        fired = set(d["pfired"])
        if a in ("resume", "reopen"):  # don't replay alerts that fell due meanwhile
            fired |= set(passed_keys(d, now))
        sets["hold_log"] = json.dumps(d["hold_log"] + [{"action": label, "date": day.isoformat(),
                                      "reason": note[:500], "logged": now.isoformat(timespec="minutes")}])
        sets["pfired"] = json.dumps(sorted(fired))
        c.execute("UPDATE projects SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?",
                  (*sets.values(), pid))  # column names above are fixed in code, never user input
    return {"status": sets.get("status", st)}


class PlanIn(BaseModel):
    items: list[dict]  # [{"day": "2026-10-20", "text": "Search CPC classes"}]


@app.get("/api/plan")
def list_plan():
    roll_plan()
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM plan_items ORDER BY day, id")]


@app.post("/api/projects/{pid}/plan")
def add_plan(pid: int, h: PlanIn):
    rows = []
    for i in h.items[:500]:
        text = str(i.get("text", "")).strip()[:300]
        try:
            day = datetime.fromisoformat(str(i.get("day", ""))[:10]).date().isoformat()
        except ValueError:
            continue
        if text:
            rows.append((pid, day, text, day, datetime.now().isoformat(timespec="minutes")))
    if not rows:
        raise HTTPException(400, "Add at least one task with a date.")
    with db() as c:
        if not c.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
            raise HTTPException(404)
        c.executemany("INSERT INTO plan_items(project_id,day,text,orig_day,created) VALUES(?,?,?,?,?)", rows)
    roll_plan()  # anything dated in the past starts today
    return {"added": len(rows)}


@app.post("/api/plan/{iid}/toggle")
def toggle_plan(iid: int):
    with db() as c:
        c.execute("UPDATE plan_items SET done=1-done, done_on=CASE WHEN done=0 THEN ? ELSE NULL END WHERE id=?",
                  (datetime.now().isoformat(timespec="minutes"), iid))
    return {"ok": True}


@app.delete("/api/plan/{iid}")
def delete_plan(iid: int):
    with db() as c:
        c.execute("DELETE FROM plan_items WHERE id=?", (iid,))
    return {"ok": True}


class ItemIn(BaseModel):
    kind: str  # "update" or "call"
    index: int
    status: str  # pending, done, skipped


@app.post("/api/projects/{pid}/item")
def project_item(pid: int, h: ItemIn):
    if h.kind not in ("update", "call") or h.status not in ("pending", "done", "skipped"):
        raise HTTPException(400, "Invalid request.")
    col = "updates" if h.kind == "update" else "calls"
    with db() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404)
        d = prow(r)
        if not 0 <= h.index < len(d[col]):
            raise HTTPException(400, "Item not found.")
        d[col][h.index]["status"] = h.status
        fired = set(d["pfired"]) | set(passed_keys(d, datetime.now()))
        c.execute(f"UPDATE projects SET {col}=?, pfired=? WHERE id=?",
                  (json.dumps(d[col]), json.dumps(sorted(fired)), pid))
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    with db() as c:  # tasks are kept, just unlinked
        c.execute("UPDATE tasks SET project_id=NULL WHERE project_id=?", (pid,))
        c.execute("DELETE FROM plan_items WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    return {"ok": True}


# ---------- Voice input (offline Whisper, runs only on this PC) ----------
VOICE_DIR = DATA / "models" / "small"
VOICE_REPO = "Systran/faster-whisper-small"
VOICE_PROMPT = ("Project name, client, due date kal, parso, shaam 5 baje, priority high, "
                "reminder 1 hour, notes, senior analyst, task.")
_vm = {"model": None, "busy": False, "error": ""}
_vlock = threading.Lock()


def voice_ready():
    return (VOICE_DIR / "ready.txt").exists() and (VOICE_DIR / "model.bin").exists()


def _download():
    try:
        from huggingface_hub import snapshot_download
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_download(VOICE_REPO, local_dir=str(VOICE_DIR))
        (VOICE_DIR / "ready.txt").write_text("ok")
        _vm["error"] = ""
    except Exception as e:
        _vm["error"] = str(e)[:300]
    finally:
        _vm["busy"] = False


def transcribe(data):
    with _vlock:
        if _vm["model"] is None:
            from faster_whisper import WhisperModel
            _vm["model"] = WhisperModel(str(VOICE_DIR), device="cpu", compute_type="int8")
        fd, name = tempfile.mkstemp(suffix=".webm")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            segs, info = _vm["model"].transcribe(
                name, beam_size=5, vad_filter=True, initial_prompt=VOICE_PROMPT,
                vad_parameters={"min_silence_duration_ms": 1500},
                condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs).strip()
        finally:
            try:
                os.remove(name)  # the audio is deleted right away
            except OSError:
                pass
    return {"text": text, "language": info.language}


@app.get("/voice.js")
def voice_js():
    return FileResponse(BASE / "voice.js", media_type="application/javascript")


@app.get("/api/voice/status")
def voice_status():
    return {"ready": voice_ready(), "downloading": _vm["busy"], "error": _vm["error"]}


@app.post("/api/voice/download")
def voice_download():
    if not voice_ready() and not _vm["busy"]:
        _vm["busy"], _vm["error"] = True, ""
        threading.Thread(target=_download, daemon=True).start()
    return voice_status()


@app.post("/api/voice")
async def voice(request: Request):
    if not voice_ready():
        raise HTTPException(409, "model_missing")
    data = await request.body()
    if len(data) < 1000:
        raise HTTPException(400, "Recording bahut chhoti hai. Dobara bolo.")
    if len(data) > 60_000_000:
        raise HTTPException(400, "Recording bahut lambi hai. Chhote hisson mein bolo.")
    try:
        return await run_in_threadpool(transcribe, data)
    except Exception as e:
        raise HTTPException(500, "Voice error: " + str(e)[:200])


if __name__ == "__main__":
    probe = socket.socket()
    running = probe.connect_ex(("127.0.0.1", 8000)) == 0
    probe.close()
    if "--silent" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    if not running:  # already running? just open the page
        uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
