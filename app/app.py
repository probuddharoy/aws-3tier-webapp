#!/bin/bash
set -xe
dnf install -y python3-pip
mkdir -p /opt/webapp
cat > /opt/webapp/app.py << 'EOF'
import urllib.request
import boto3
import pymysql
from flask import Flask, request, redirect, render_template_string

ssm = boto3.client("ssm", region_name="ap-south-1")

def param(name):
    return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]

DB_HOST = param("/webapp/db/host")
DB_PASS = param("/webapp/db/password")

def conn():
    return pymysql.connect(host=DB_HOST, user="admin", password=DB_PASS,
                           database="notesdb", connect_timeout=5)

def meta(path):
    try:
        r = urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        t = urllib.request.urlopen(r, timeout=2).read().decode()
        r2 = urllib.request.Request("http://169.254.169.254/latest/meta-data/" + path,
            headers={"X-aws-ec2-metadata-token": t})
        return urllib.request.urlopen(r2, timeout=2).read().decode()
    except Exception:
        return "unknown"

c = conn()
with c.cursor() as cur:
    cur.execute("CREATE TABLE IF NOT EXISTS notes (id INT AUTO_INCREMENT PRIMARY KEY, "
                "body VARCHAR(255) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
c.commit()
c.close()

app = Flask(__name__)

PAGE = """
<h2>Notes</h2>
<form method="post" action="/add"><input name="body" maxlength="255" required>
<button>Add</button></form>
<ul>{% for r in rows %}<li>{{ r[0] }}</li>{% endfor %}</ul>
<p><small>Served by {{ iid }} in {{ az }}</small></p>
"""

@app.route("/")
def index():
    c = conn()
    with c.cursor() as cur:
        cur.execute("SELECT body FROM notes ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
    c.close()
    return render_template_string(PAGE, rows=rows, iid=meta("instance-id"),
                                  az=meta("placement/availability-zone"))

@app.route("/add", methods=["POST"])
def add():
    body = request.form.get("body", "").strip()[:255]
    if body:
        c = conn()
        with c.cursor() as cur:
            cur.execute("INSERT INTO notes (body) VALUES (%s)", (body,))
        c.commit()
        c.close()
    return redirect("/")

@app.route("/health")
def health():
    return "ok", 200
EOF
pip3 install flask gunicorn pymysql boto3
useradd -r -s /sbin/nologin webapp
chown -R webapp /opt/webapp
cat > /etc/systemd/system/webapp.service << 'EOF'
[Unit]
Description=Notes web app
After=network-online.target
Wants=network-online.target
[Service]
User=webapp
WorkingDirectory=/opt/webapp
ExecStart=/usr/local/bin/gunicorn -w 2 -b 0.0.0.0:80 app:app
Restart=always
AmbientCapabilities=CAP_NET_BIND_SERVICE
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now webapp