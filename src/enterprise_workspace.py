"""Durable enterprise workflows for secure browser-agent operations."""

from __future__ import annotations

import html
import ipaddress
import json
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse


class PolicyDenied(RuntimeError):
    pass


def _id(p):
    return f"{p}_{uuid.uuid4().hex}"


def _redact(v):
    if isinstance(v, dict):
        return {
            k: (
                "[REDACTED]"
                if k.lower() in {"token", "password", "cookie", "authorization", "secret"}
                else _redact(x)
            )
            for k, x in v.items()
        }
    if isinstance(v, list):
        return [_redact(x) for x in v]
    return v


class EnterpriseWorkspace:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self.db() as d:
            d.executescript("""
CREATE TABLE IF NOT EXISTS policies(id TEXT PRIMARY KEY,tenant TEXT,origins TEXT,actions TEXT,state TEXT);
CREATE TABLE IF NOT EXISTS replays(id TEXT PRIMARY KEY,tenant TEXT,state TEXT,created REAL);
CREATE TABLE IF NOT EXISTS replay_events(id TEXT PRIMARY KEY,replay_id TEXT,kind TEXT,data TEXT,created REAL);
CREATE TABLE IF NOT EXISTS takeovers(id TEXT PRIMARY KEY,tenant TEXT,run_id TEXT,reason TEXT,state TEXT,claimant TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY,tenant TEXT,name TEXT,steps TEXT,version INTEGER,state TEXT);
CREATE TABLE IF NOT EXISTS quotas(tenant TEXT PRIMARY KEY,max_sessions INTEGER);
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,region TEXT,capacity INTEGER,state TEXT);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,tenant TEXT,node_id TEXT,checkpoint TEXT,state TEXT);
CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY,candidate TEXT,threshold REAL,state TEXT);
CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY,evaluation_id TEXT,success INTEGER,latency REAL,cost REAL);
""")

    def db(self):
        d = sqlite3.connect(self.path)
        d.row_factory = sqlite3.Row
        return d

    def create_policy(self, t, o, a):
        i = _id("pol")
        with self.db() as d:
            d.execute(
                "INSERT INTO policies VALUES (?,?,?,?, 'ACTIVE')",
                (i, t, json.dumps(o), json.dumps(a)),
            )
        return i

    def authorize(self, t, action, url):
        u = urlparse(url)
        host = u.hostname or ""
        try:
            for x in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(x[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise PolicyDenied("PRIVATE_NETWORK_DENIED")
        except socket.gaierror:
            raise PolicyDenied("HOST_RESOLUTION_FAILED")
        with self.db() as d:
            r = d.execute(
                "SELECT origins,actions FROM policies WHERE tenant=? AND state='ACTIVE'", (t,)
            ).fetchone()
        if (
            not r
            or action not in json.loads(r["actions"])
            or f"{u.scheme}://{u.netloc}" not in json.loads(r["origins"])
        ):
            raise PolicyDenied("POLICY_DENIED")
        return True

    def start_replay(self, t):
        i = _id("rep")
        with self.db() as d:
            d.execute("INSERT INTO replays VALUES (?,?, 'RECORDING',?)", (i, t, time.time()))
        return i

    def add_replay_event(self, r, k, data):
        with self.db() as d:
            d.execute(
                "INSERT INTO replay_events VALUES (?,?,?,?,?)",
                (_id("ev"), r, k, json.dumps(_redact(data), sort_keys=True), time.time()),
            )

    def replay(self, r):
        with self.db() as d:
            return {
                "id": r,
                "events": [
                    {"kind": x["kind"], "data": json.loads(x["data"])}
                    for x in d.execute(
                        "SELECT * FROM replay_events WHERE replay_id=? ORDER BY created", (r,)
                    )
                ],
            }

    def request_takeover(self, t, run, reason):
        i = _id("to")
        with self.db() as d:
            d.execute(
                "INSERT INTO takeovers VALUES (?,?,?,?, 'WAITING',NULL,NULL)", (i, t, run, reason)
            )
        return i

    def claim_takeover(self, i, user, expires_at):
        with self.db() as d:
            d.execute(
                "UPDATE takeovers SET state='CLAIMED',claimant=?,expires=? WHERE id=?",
                (user, expires_at, i),
            )

    def approve_takeover(self, i, user, now=None):
        now = time.time() if now is None else now
        with self.db() as d:
            r = d.execute("SELECT * FROM takeovers WHERE id=?", (i,)).fetchone()
            if not r or r["claimant"] != user:
                raise PolicyDenied("CLAIM_REQUIRED")
            if r["expires"] < now:
                raise PolicyDenied("LEASE_EXPIRED")
            d.execute("UPDATE takeovers SET state='APPROVED' WHERE id=?", (i,))

    def create_workflow(self, t, name, steps):
        if not name or not steps:
            raise ValueError("WORKFLOW_INVALID")
        i = _id("wf")
        with self.db() as d:
            d.execute(
                "INSERT INTO workflows VALUES (?,?,?,?,1,'READY')",
                (i, t, name, json.dumps(_redact(steps), sort_keys=True)),
            )
        return i

    def export_workflow(self, i):
        with self.db() as d:
            r = d.execute("SELECT name,steps,version FROM workflows WHERE id=?", (i,)).fetchone()
        return json.dumps(
            {
                "schema_version": 1,
                "name": r["name"],
                "version": r["version"],
                "steps": json.loads(r["steps"]),
            },
            sort_keys=True,
        )

    def set_quota(self, t, n):
        with self.db() as d:
            d.execute("INSERT OR REPLACE INTO quotas VALUES (?,?)", (t, n))

    def register_node(self, region, cap):
        i = _id("node")
        with self.db() as d:
            d.execute("INSERT INTO nodes VALUES (?,?,?,'READY')", (i, region, cap))
        return i

    def lease_session(self, t, node, checkpoint=None):
        with self.db() as d:
            q = d.execute("SELECT max_sessions FROM quotas WHERE tenant=?", (t,)).fetchone()
            n = d.execute(
                "SELECT COUNT(*) FROM sessions WHERE tenant=? AND state='ACTIVE'", (t,)
            ).fetchone()[0]
            if not q or n >= q[0]:
                raise PolicyDenied("TENANT_QUOTA_EXCEEDED")
            i = _id("sess")
            d.execute("INSERT INTO sessions VALUES (?,?,?,?, 'ACTIVE')", (i, t, node, checkpoint))
        return i

    def mark_node_lost(self, n):
        with self.db() as d:
            d.execute("UPDATE nodes SET state='LOST' WHERE id=?", (n,))
            d.execute(
                "UPDATE sessions SET state='RECOVERABLE' WHERE node_id=? AND checkpoint IS NOT NULL",
                (n,),
            )
            d.execute(
                "UPDATE sessions SET state='FAILED' WHERE node_id=? AND checkpoint IS NULL", (n,)
            )

    def recovery_sessions(self, t):
        with self.db() as d:
            return [
                x[0]
                for x in d.execute(
                    "SELECT id FROM sessions WHERE tenant=? AND state='RECOVERABLE' ORDER BY id",
                    (t,),
                )
            ]

    def create_evaluation(self, c, threshold):
        i = _id("eval")
        with self.db() as d:
            d.execute("INSERT INTO evaluations VALUES (?,?,?,'RUNNING')", (i, c, threshold))
        return i

    def record_trial(self, e, success, latency, cost):
        with self.db() as d:
            d.execute(
                "INSERT INTO trials VALUES (?,?,?,?,?)", (_id("tr"), e, int(success), latency, cost)
            )

    def evaluate(self, e):
        with self.db() as d:
            r = d.execute("SELECT threshold FROM evaluations WHERE id=?", (e,)).fetchone()
            a = d.execute(
                "SELECT AVG(success),AVG(latency),SUM(cost) FROM trials WHERE evaluation_id=?", (e,)
            ).fetchone()
            rate = float(a[0] or 0)
            state = "PASSED" if rate >= r[0] else "FAILED"
            d.execute("UPDATE evaluations SET state=? WHERE id=?", (state, e))
        return {"state": state, "success_rate": rate, "avg_latency": a[1], "cost": a[2]}


def render_console(page, w):
    titles = {
        "policy": "Policy gateway",
        "replay": "Session replay",
        "takeover": "Human takeover",
        "workflows": "Workflow studio",
        "fleet": "Fleet control",
        "evaluation": "Evaluation lab",
    }
    if page not in titles:
        raise KeyError(page)
    nav = "".join(f'<a href="/enterprise/{k}">{v}</a>' for k, v in titles.items())
    return f"""<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/static/enterprise.css"><title>{html.escape(titles[page])}</title></head><body><a class="skip" href="#main">Skip to content</a><header><strong>Browser Helper</strong><span>Enterprise operations</span></header><div class="shell"><nav>{nav}</nav><main id="main"><h1>{html.escape(titles[page])}</h1><p aria-live="polite">Workspace ready</p><section class="metrics"><article>Objects<br><strong>0</strong></article><article>Status<br><strong>Operational</strong></article></section><section class="empty"><h2>No items yet</h2><button>Create first item</button></section><section class="recovery"><h2>Recovery</h2><p>Completed work is preserved.</p><button>Try again</button></section></main></div></body></html>"""
