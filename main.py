# main.py  – login + mounted ABET app
"""
Run:
    pip install flask werkzeug
    python main.py
Open http://127.0.0.1:5000/login
"""
# ─── top of each file (after imports) ───────────────────────────────
import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib.pyplot as plt
import os, sqlite3, pathlib

IS_PROD = os.getenv("FLASK_ENV") == "production"     # set on Render
DB_PATH = os.getenv("ABET_DB_PATH") or (
          "/data/abet_data.db" if IS_PROD            # Render disk
          else os.path.join(os.path.dirname(__file__), "abet_data.db"))

# make sure the containing folder exists (but ignore "/" on macOS)
folder = pathlib.Path(DB_PATH).parent
if str(folder) not in ("/", ""):
    folder.mkdir(parents=True, exist_ok=True)

# optional back-compat alias until you delete every DB_NAME reference

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# ---- separate database for Graduate Survey ----
SURVEY_DB_PATH = os.getenv("ABET_SURVEY_DB_PATH") or (
    "/data/graduate_survey.db" if IS_PROD
    else os.path.join(os.path.dirname(__file__), "graduate_survey.db")
)

# make sure the folder exists (mirrors your main DB setup)
survey_folder = pathlib.Path(SURVEY_DB_PATH).parent
if str(survey_folder) not in ("/", ""):
    survey_folder.mkdir(parents=True, exist_ok=True)

def get_survey_conn():
    return sqlite3.connect(SURVEY_DB_PATH, check_same_thread=False)

# --- Graduate Survey table bootstrap ---------------------------------
def init_survey_db():
    with get_survey_conn() as conn:   # ← use the SURVEY DB here
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graduate_survey_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT,
                year_graduated TEXT,
                job_plan TEXT,
                answers_json TEXT,
                submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
init_survey_db()

from flask import (
    Flask, render_template_string, request,
    redirect, url_for, session
)
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import importlib
import statsmodels.formula.api as smf
abet_mod = importlib.import_module("ABET_Data_Rev1")   # or Rev2
abet_app = abet_mod.app
import sqlite3
import os
from werkzeug.serving import run_simple
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from scipy.stats import norm
from matplotlib import colors

import matplotlib.pyplot as plt


from functools import wraps
from urllib.parse import quote_plus

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper

# ------------------------------------------------------------------ #
# parameters
# ------------------------------------------------------------------ #
USERS = {
    "MECE Admin"      : "admin230",
    "Lawrence Cano"     : "HHP1",
    "Yingchen Yang" : "2FVM",
    "Eleazar Marquez" : "MBRH",
    "Misael Martinez" : "AUBY",
    "Robert Jones"    : "BABR",
    "Jose Sanchez"    : "TY3I",
    "Nadim Zgheib"    : "1R6N",
    "Constantine T"   : "65YJ",
    "Robert Freeman"  : "XB7U",
    "Isaac Choutapalli"     : "4EMV",
    "Caruntu D"       : "PUHL",
    "Javier Ortega"   : "A3Q0",
    "Noe Vargas"      : "GWSW",
    "Kamal Sarkar"    : "1YEQ",
    "Mataz Alcoutlabi": "7ICU",
    "Super User": "LAMR",
    "Capstone Exit Survey": "SURVEY",  # simple passcode; change anytime
}
SECRET_KEY = "CHANGE-ME"

import os

IS_DEV = os.environ.get("FLASK_ENV") != "production"
COOKIE_SECURE = not IS_DEV          # False on your laptop, True on Render


# ------------------------------------------------------------------ #
# import the existing ABET app
# ------------------------------------------------------------------ #
abet_mod = importlib.import_module("ABET_Data_Rev1")   # same directory
abet_app = abet_mod.app                                # Flask instance in that file
abet_app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_SECURE=COOKIE_SECURE,   # ← changed line
    SESSION_COOKIE_SAMESITE="Lax",
)


# ------------------------------------------------------------------ #
# tiny login page
# ------------------------------------------------------------------ #
LOGIN_HTML = """
<!doctype html><html><head>
<meta charset=utf-8><title>ABET login</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@800;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;font-family:Poppins,sans-serif}

.site-hdr{
  width:100%;
  background:linear-gradient(90deg,#003638 0%,#005158 50%,#00736f 100%);
  box-shadow:0 4px 12px rgba(0,0,0,.08);
  padding:2.2rem 1rem 2rem;
  display:flex;justify-content:center;
  border-top-left-radius:12px;border-top-right-radius:12px;
}
.hdr-inner{text-align:center;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.35)}
.hdr-title{
  font-size:1.9rem;font-weight:700;letter-spacing:.02rem;
  margin-bottom:.65rem;
}
.hdr-subtitle{
  font-size:1.15rem;font-weight:500;letter-spacing:.03rem;
  opacity:.93;
}

body{
  background:
      linear-gradient(rgba(247,249,252,.9), rgba(247,249,252,.9)),
      url("/static/turbine.png") center/cover no-repeat;
}

/* ---------- footer ---------- */
footer.copyright{
  width:100%;margin-top:2.5rem;padding:.9rem 0;
  background:linear-gradient(90deg,#003638 0%,#005158 100%);
  color:#fff;font-size:.9rem;font-weight:600;letter-spacing:.03rem;text-align:center;
  box-shadow:0 -4px 10px rgba(0,0,0,.05);
  border-bottom-left-radius:12px;border-bottom-right-radius:12px;
}

/* ---------- login card ---------- */
.card{
  width:360px;                     /* a bit wider */
  background:#ffffff;
  padding:2.2rem 2.4rem 2.5rem;
  border-radius:16px;
  box-shadow:0 10px 22px rgba(0,0,0,.12);
  position:relative;
  overflow:hidden;
}

/* subtle accent bar across the top */
.card::before{
  content:"";
  position:absolute;top:0;left:0;height:6px;width:100%;
  background:linear-gradient(90deg,#ee7f2f 0%,#f29c4b 100%);
  border-top-left-radius:16px;
  border-top-right-radius:16px;
}

/* --------- heading / error --------- */
h1{
  font-size:1.45rem;
  margin:0 0 1.1rem;
  text-align:center;
  color:#003638;
}
#error{
  color:#c62828;
  font-size:.9rem;
  text-align:center;
  margin-bottom:.65rem;
}

/* --------- labels & controls --------- */
label{
  font-size:1rem;
  font-weight:600;
  color:#003638;
  display:block;
  margin-bottom:.35rem;
}
select,input{
  width:100%;
  padding:.65rem .7rem;
  margin-bottom:1.05rem;
  border:1px solid #bdbdbd;
  border-radius:8px;
  font-size:1rem;
  font-weight:600;
  background:#fafafa;
  color:#37474f;
}

/* --------- button --------- */
button{
  width:100%;
  padding:.7rem 0;
  border:none;
  border-radius:8px;
  background:#ee7f2f;
  color:#ffffff;
  font-size:1.05rem;
  font-weight:600;
  cursor:pointer;
  transition:transform .05s, box-shadow .15s;
}
button:hover{box-shadow:0 4px 10px rgba(0,0,0,.1)}
button:active{transform:translateY(2px)}

.pwd-toggle{
  font-size:.85rem;
  font-weight:600;
  color:#00736f;
  cursor:pointer;              /* ← pointer on hover */
  user-select:none;
  transition:color .2s, opacity .2s;
}
.pwd-toggle:hover{
  color:#004b4c;
  opacity:.8;
  text-decoration:underline;
}

.pwd-wrapper{
  position:relative;
}
.pwd-wrapper input{
  padding-right:2.5rem;          /* room for icon */
}
.eye{
  position:absolute;top:50%;right:.7rem;
  transform:translateY(-50%);
  cursor:pointer;
  color:#888;transition:color .2s;
}
.eye:hover{color:#004b4c}

.admin-main{
  flex:1;display:flex;justify-content:center;align-items:center;
  padding:3rem 1rem;
}

.admin-card{
  background:#ffffff;width:100%;max-width:960px;
  border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.10);
  padding:2.5rem 2rem;display:flex;flex-direction:column;gap:1.6rem;
}

/* ---------- orange portal buttons ---------- */
.portal-btn{
background:#ee7f2f;
  width:100%;border:none;border-radius:12px;cursor:pointer;
  background:#ee7f2f;color:#ffffff;text-align:left;
  padding:1.3rem 1.4rem;box-shadow:0 6px 16px rgba(0,0,0,.12);
  transition:transform .06s, box-shadow .18s;
}
.portal-btn:hover{box-shadow:0 8px 18px rgba(0,0,0,.16)}
.portal-btn:active{transform:translateY(3px)}

.btn-title{
  font-size:1.2rem;font-weight:700;margin-bottom:.35rem;
}
.btn-desc{
  font-size:.93rem;font-weight:400;line-height:1.35rem;opacity:.94;
}

/* prevent content from hugging the left edge on very wide screens */
body{padding-left:.5rem;padding-right:.5rem}

</style>

<body>

  <!-- fancy header -->
  <header class="site-hdr">
    <div class="hdr-inner">
      <div class="hdr-title">UTRGV Department of Mechanical Engineering</div>
      <div class="hdr-subtitle">ABET Data Collection Portal</div>
    </div>
  </header>

  <!-- login card (unchanged) -->
  <main style="display:flex;justify-content:center;align-items:center;padding:3rem 0">
    <div class="card">
      <h1>ABET Login</h1>
      {% if error %}<div id="error">{{ error }}</div>{% endif %}
      <form method="post">
        <label>User</label>
        <select name="user" required>
  <option value="" disabled selected>Select user</option>
  <option>Lawrence Cano</option>
  <option>Yingchen Yang</option>
  <option>Misael Martinez</option>
  <option>Eleazar Marquez</option>
  <option>Robert Jones</option>
  <option>Jose Sanchez</option>
  <option>Nadim Zgheib</option>
  <option>Constantine T</option>
  <option>Robert Freeman</option>
  <option>Isaac Choutapalli</option>
  <option>Caruntu D</option>
  <option>Javier Ortega</option>
  <option>Noe Vargas</option>
  <option>Kamal Sarkar</option>
  <option>Mataz Alcoutlabi</option>
  <option>Super User</option>
  <option>MECE Admin</option>
  <option>Capstone Exit Survey</option>
</select>

        <label>Password</label>
<div class="pwd-wrapper">
  <input id="pwd" type="password" name="password" required>
  <span id="eye" class="eye" onclick="toggle()">
    <!-- open-eye SVG -->
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </span>
</div>
        <button type="submit">Login</button>
      </form>
    </div>
  </main>

  <!-- fancy footer -->
  <footer class="copyright">
    ©2025 Center for Aerospace Research
  </footer>

<script>
const EYE_OPEN = `
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12"/>
  <circle cx="12" cy="12" r="3"/>
</svg>`;
const EYE_CLOSED = `
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M17 17L1 1m22 22L7 7"/>
  <path d="M10.58 10.59a3 3 0 004.24 4.24"/>
  <path d="M1 12s4-7 11-7a10.9 10.9 0 016.29 2.11"/>
  <path d="M23 12s-4 7-11 7a10.9 10.9 0 01-6.29-2.11"/>
</svg>`;

function toggle(){
  const inp = document.getElementById('pwd');
  const eye = document.getElementById('eye');
  const show = inp.type === 'password';
  inp.type  = show ? 'text' : 'password';
  eye.innerHTML = show ? EYE_CLOSED : EYE_OPEN;
}
</script>
</body></html>
"""

ADMIN_HTML = """
<!DOCTYPE html><html><head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <title>ABET Analysis Portal</title>

  <!-- fonts + icons -->
  <link href='https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap' rel='stylesheet'>
  <link href='https://unpkg.com/lucide-static@latest/font/lucide.css' rel='stylesheet'>

  <style>
  /* ------- base ----------------------------------------------------- */
  *{box-sizing:border-box;font-family:Poppins,sans-serif}

.site-hdr{
  width:100%;
  background:linear-gradient(90deg,#003638 0%,#005158 50%,#00736f 100%);
  box-shadow:0 4px 12px rgba(0,0,0,.08);
  padding:2.2rem 1rem 2rem;
  display:flex;justify-content:center;
  border-top-left-radius:12px;border-top-right-radius:12px;
}
.hdr-inner{text-align:center;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.35)}
.hdr-title{
  font-size:1.9rem;font-weight:700;letter-spacing:.02rem;
  margin-bottom:.65rem;
}
.hdr-subtitle{
  font-size:1.15rem;font-weight:500;letter-spacing:.03rem;
  opacity:.93;
}

/* ---------- footer ---------- */
footer.copyright{
  width:100%;margin-top:2.5rem;padding:.9rem 0;
  background:linear-gradient(90deg,#003638 0%,#005158 100%);
  color:#fff;font-size:.9rem;font-weight:600;letter-spacing:.03rem;text-align:center;
  box-shadow:0 -4px 10px rgba(0,0,0,.05);
  border-bottom-left-radius:12px;border-bottom-right-radius:12px;
}
  
  

  /* logout btn just under header ------------------------------------ */
  .logout-bar{display:flex;justify-content:flex-end;padding:.45rem 1.4rem;background:inherit}
  .logout-btn{display:inline-flex;align-items:center;gap:.5rem;padding:.45rem 1.1rem;border:none;border-radius:10px;background:#ee7f2f;color:#fff;font-size:.95rem;font-weight:600;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.1);transition:transform .06s,box-shadow .2s}
  .logout-btn:hover{box-shadow:0 6px 14px rgba(0,0,0,.14)}
  .logout-btn:active{transform:translateY(2px)}

  /* container -------------------------------------------------------- */
  .wrap{max-width:960px;margin:2.2rem auto;padding:0 1rem;display:flex;flex-direction:column;gap:2.2rem}
  .section{background:#fff;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.10);padding:2rem 1.6rem}
  .section-hdr{font-size:1.25rem;font-weight:600;color:#003638;margin:0 0 1rem;position:relative;padding-left:.4rem}
  .section-hdr::before{content:"";position:absolute;left:0;top:0;height:100%;width:4px;background:#ee7f2f;border-radius:3px}

  /* control rows ----------------------------------------------------- */
  .row{display:flex;flex-wrap:wrap;gap:1rem;align-items:center}
  select{min-width:170px;padding:.6rem;border-radius:8px;font-weight:600}
  .btn{padding:.65rem 1.3rem;border:none;border-radius:14px;background:#ee7f2f;color:#fff;font-size:1.05rem;font-weight:600;cursor:pointer;box-shadow:0 6px 16px rgba(0,0,0,.12);transition:transform .06s,box-shadow .2s}
  .btn:hover{box-shadow:0 8px 18px rgba(0,0,0,.16)}
  .btn:active{transform:translateY(3px)}
  .btn:disabled{opacity:.5;cursor:not-allowed}
  
  </style>
</head><body>

<header class='site-hdr'>
  <div class='hdr-inner'>
    <div class='hdr-title'>UTRGV Department of Mechanical Engineering</div>
    <div class='hdr-subtitle'>ABET Analysis Portal</div>
  </div>
</header>

<!-- logout bar -->
<div class='logout-bar'>
  <button class='logout-btn' onclick="location.href='/logout'">
    <i class='lucide-power'></i> Logout
  </button>
</div>

<div class='wrap'>

  <!-- 1 ░░░ Database Record Preview ░░░ -->
  <section class='section'>
    <h2 class='section-hdr'>Database Record Preview</h2>
    <div class='row'>
      <select id='recCourse'>
        <option value='ALL'>All Data</option>
        {% for c in [
          'MECE 1101','MECE 1221','MECE 2140','MECE 2302','MECE 2340','MECE 3170',
          'MECE 3315','MECE 3320','MECE 3336','MECE 3360','MECE 3380','MECE 3450',
          'MECE 4350','MECE 4361','MECE 4362','PHIL 2393'] %}
          <option>{{ c }}</option>
        {% endfor %}
      </select>
      <button class='btn' onclick='displayRecords()'>Display Database Records</button>
    </div>
  </section>
  
  <!-- 1b ░░░ Capstone Exit Survey – Record Preview ░░░ -->
<section class='section'>
  <h2 class='section-hdr'>Capstone Exit Survey – Record Preview</h2>
  <div class='row' style="gap:.8rem">
    <button class='btn' onclick='displaySurvey()'>Display Capstone Exit Survey Data</button>
    <button class='btn' onclick='analyzeSurvey()'>Analyze Data</button>
  </div>
</section>

  <!-- 2 ░░░ Course‑Level Analysis ░░░ -->
  <section class='section'>
    <h2 class='section-hdr'>Course‑Level Analysis</h2>
    <div class='row'>
      <select id='courseSel' required>
        <option value='' disabled selected>Select course</option>
        {% for c in [
          'MECE 1101','MECE 1221','MECE 2140','MECE 2302','MECE 2340','MECE 3170',
          'MECE 3315','MECE 3320','MECE 3336','MECE 3360','MECE 3380','MECE 3450',
          'MECE 4350','MECE 4361','MECE 4362','PHIL 2393'] %}
          <option>{{ c }}</option>
        {% endfor %}
      </select>
      <button id='sloBtn' class='btn' onclick='openSloChooser()'>Select SLO</button>
      <button id='analyzeBtn' class='btn' onclick='analyze()' disabled>Analyze Course</button>
      <select id='sloSel' style='display:none;min-width:140px;padding:.6rem;border-radius:8px;font-weight:600'>
        <option value='' disabled selected>Select SLO</option>
        <option>SLO1</option><option>SLO2</option><option>SLO3</option>
        <option>SLO4</option><option>SLO5</option><option>SLO6</option><option>SLO7</option>
      </select>
    </div>
  </section>

  <!-- 3 ░░░ SLO‑Level Analysis ░░░ -->
  <section class='section'>
    <h2 class='section-hdr'>SLO‑Level Analysis</h2>
    <div class='row'>
      <select id='sloOnlySel' required>
        <option value='' disabled selected>Select SLO</option>
        <option>SLO1</option><option>SLO2</option><option>SLO3</option>
        <option>SLO4</option><option>SLO5</option><option>SLO6</option><option>SLO7</option>
      </select>
      <button id='analyzeSloBtn' class='btn' disabled>Analyze SLO</button>
    </div>
  </section>

</div>

<footer class="copyright">
  © 2025 Center for Aerospace Research
</footer>

<script>
// ─── record preview ──────────────────────────────────────────────
function displayRecords(){
  const course = document.getElementById('recCourse').value;
  const url    = course === 'ALL'
               ? '/download'
               : '/download?course=' + encodeURIComponent(course.replace(/\u00A0/g,' '));
  window.open(url, '_blank','width=1100,height=800,resizable=yes');
}

// ─── Course‑level logic (existing) ──────────────────────────────
function checkReady(){
  const ok = document.getElementById('courseSel').value && document.getElementById('sloSel').value;
  document.getElementById('analyzeBtn').disabled = !ok;
}
function openSloChooser(){
  const sel = document.getElementById('sloSel');
  sel.style.display = 'inline-block';
  sel.onchange = checkReady;
  sel.focus();
}
function analyze(){
  const course = document.getElementById('courseSel').value;
  const slo    = document.getElementById('sloSel').value;
  window.open(`/analyze_course?course=${encodeURIComponent(course)}&slo=${encodeURIComponent(slo)}`,
              '_blank','width=1100,height=800,resizable=yes');
}

function analyzeSlo(){
  const slo = document.getElementById('sloOnlySel').value;
  window.open(`/analyze_slo?slo=${encodeURIComponent(slo)}`,
              '_blank','width=1100,height=800,resizable=yes');
}
document.getElementById('analyzeSloBtn').onclick = analyzeSlo;

// ─── enable Analyze SLO btn when dropdown chosen ────────────────
document.getElementById('sloOnlySel').addEventListener('change',e=>{
  document.getElementById('analyzeSloBtn').disabled = !e.target.value;
});

function displaySurvey(){
  window.open('/survey/download','_blank','width=1100,height=800,resizable=yes');
}
function analyzeSurvey(){
  window.open('/survey/analyze','_blank','width=1300,height=900,resizable=yes');
}
</script>

</body></html>
"""


DATA_HTML = """
<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>ABET Data</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;font-family:Poppins,sans-serif}
body{margin:0;background:#f7f9fc;color:#252525}
table{width:96%;margin:2rem auto;border-collapse:collapse;background:#fff;
      box-shadow:0 4px 10px rgba(0,0,0,.08);border-radius:12px;overflow:hidden}
th,td{padding:.6rem .5rem;border-bottom:1px solid #e0e0e0;text-align:left}
th{background:#003638;color:#fff;font-weight:600}
tr:nth-child(even){background:#f2f8f8}
caption{margin:2.5rem auto 1.2rem;font-size:1.6rem;font-weight:700;color:#003638}
</style>
</head><body>
<caption>ABET Data (entries: {{ rows|length }})</caption>
<table>
  <thead>
    <tr>{% for col in columns %}<th>{{ col }}</th>{% endfor %}</tr>
  </thead>
  <tbody>
    {% for row in rows %}
      <tr>{% for col in columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>
    {% endfor %}
  </tbody>
</table>
</body></html>
"""

# ------------------------------------------------------------------ #
# parent Flask app – handles login / logout
# ------------------------------------------------------------------ #
parent = Flask(__name__)
parent.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_SECURE=COOKIE_SECURE,   # ← changed line
    SESSION_COOKIE_SAMESITE="Lax",
)

@parent.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("user", "")
        pw   = request.form.get("password", "")
        if USERS.get(user) == pw:
            session["user"] = user
            # Graduate Survey flow
            if user == "Capstone Exit Survey":
                return redirect("/survey/form")

            # ───── redirect faculty straight to the mounted app ─────
            if user != "MECE Admin":                       # faculty
                encoded = quote_plus(user)                 # spaces → +
                return redirect(f"/abet/?user={encoded}")  # <- key change

            # admin keeps the existing portal
            return redirect(url_for("admin_portal"))

        return render_template_string(LOGIN_HTML, error="Invalid credentials")

    return render_template_string(LOGIN_HTML, error=None)

@parent.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@parent.route("/")
def root():
    return redirect("/login")

# ------------------------------------------------------------------ #
# protect every /abet* URL
# ------------------------------------------------------------------ #
@parent.before_request
def guard():
    if request.path.startswith("/abet") and "user" not in session:
        return redirect(url_for("login"))

# ------------------------------------------------------------------ #
# mount the original ABET app at /abet
# ------------------------------------------------------------------ #
application = DispatcherMiddleware(parent.wsgi_app, {
    "/abet": abet_app   # all of your existing routes/assets now live under /abet
})

@parent.route("/abet", endpoint="abet")
@login_required
def abet_root():
    """
    Redirect to the ABET data‑entry app and pass the logged‑in user
    in the query string.  Admins keep full access; everyone else gets
    their own user name so the data‑entry page can lock courses.
    """
    user = session.get("user")

    if user != "MECE Admin":                 # faculty
        return redirect("/abet/")
    # admin
    return redirect(f"/abet/?user={quote_plus('MECE Admin')}")

@parent.route("/admin")
@login_required
def admin_portal():
    if session.get("user") != "MECE Admin":
        return redirect(url_for("abet"))   # non-admin users go to /abet
    return render_template_string(ADMIN_HTML)

@parent.route("/download")
@login_required
def download():
    if session.get("user") != "MECE Admin":
        return redirect(url_for("abet"))

    course = request.args.get("course")        # may be None
    with get_conn() as conn:

        if course:
            df = pd.read_sql_query(
                "SELECT * FROM abet_entries WHERE course = ?",
                conn, params=(course.replace("\u00A0"," "),)
            )
        else:
            df = pd.read_sql_query("SELECT * FROM abet_entries", conn)

    return render_template_string(
        DATA_HTML,
        columns=df.columns,
        rows=df.to_dict(orient="records")
    )
# ------------------------------------------------------------------ #
# run
# ------------------------------------------------------------------ #

from io import BytesIO
import base64, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

@parent.route("/analyze_course")
@login_required
def analyze_course():
    """Return either an alert (if no rows) or an HTML page with a bar‑plot."""
    course = (request.args.get("course", "")  # existing line
              .replace("\u00A0", " ")  # NBSP → normal space
              .strip())
    slo = request.args.get("slo", "").strip()
    if not course or not slo:
        return "<script>alert('Missing course/SLO');window.close();</script>"


    with get_conn() as conn:

        q = """
                SELECT pi,
                       semester,
                       blooms_level,          
                       expert,
                       practitioner,
                       apprentice,
                       novice
                  FROM abet_entries
                 WHERE course=? AND slo=?
            """
        df = pd.read_sql_query(q, conn, params=(course, slo))

    if df.empty:
        return "<script>alert('This course does not have this SLO data');window.close();</script>"

    def short_sem(sem: str) -> str:
        try:
            season, yr = sem.split()
            return ("F" if season.lower().startswith("f") else "Sp") + yr[-2:]
        except ValueError:
            return sem

    df["sem_short"] = df["semester"].apply(short_sem)

    df["semester_idx"] = (
            df["sem_short"]
            .rank(method="dense")  # 1,2,3… in chronological order
            .astype(int) - 1
    )

    #   combine Expert + Practitioner as a single attainment metric
    df['attain'] = df['expert'] + df['practitioner']

    df["pi"] = df["pi"].astype(str).str.strip()  # NEW ↓ normalise text
    df = df[df["pi"] != ""]
    # ─── bail-out if the filtered dataframe is now empty ────────────
    if df.empty:
        return "<script>alert('No usable PI / Bloom data for this course–SLO');" \
               "window.close();</script>"

    pis = sorted(df["pi"].unique())
    if not pis:  # no PI left  → nothing to plot
        return "<script>alert('No PI records after cleaning');window.close();</script>"
    pis = sorted(df["pi"].unique())  # NEW ↓ dynamic PI list
    n_pi = len(pis)  # NEW ↓ use everywhere

    # ── NEW: normalise Bloom text and build a PI-Bloom combo label ─────────
    df["blooms_level"] = df["blooms_level"].astype(str).str.strip()

    # helper: "PI-1: Able to …"  →  "PI-1"
    def short_pi(txt: str) -> str:
        return txt.split(":")[0].strip()

    # composite label stored in the dataframe
    df["pi_bl"] = df["pi"].apply(short_pi) + " (" + df["blooms_level"] + ")"

    #print(model.summary())  # slope β₁ & its p-value

    # ---- build the ordered list of rows for pivot-2 ----------------------
    combo_order = []
    for pi_full in pis:  # pis still has the *long* strings
        pi_tag = short_pi(pi_full)  # ← convert once here
        seen = set()
        for lvl in df.loc[df.pi == pi_full, "blooms_level"]:
            if lvl not in seen:
                combo_order.append(f"{pi_tag} ({lvl})")  # ← short tag
                seen.add(lvl)
    n_combo = len(combo_order)

    # ───────────────────────  TWO‑PLOT LAYOUT  ──────────────────────────
    import numpy as np, matplotlib.patches as mpatches
    from matplotlib import ticker

    # --------------------- helpers for semester -------------------------
    def short_sem(sem: str) -> str:
        try:
            season, yr = sem.split()
            tag = "F" if season.lower().startswith("f") else "Sp"
            return f"{tag}{yr[-2:]}"
        except ValueError:
            return sem

    def sem_key(sem: str) -> int:  # chronological sort key
        if sem.startswith("F"):
            return int("20" + sem[1:]) * 2 + 1
        elif sem.startswith("Sp"):
            return int("20" + sem[2:]) * 2
        return 10 ** 9

    df["sem_short"] = df["semester"].apply(short_sem)
    sem_order = sorted(df["sem_short"].unique(), key=sem_key)  # e.g. ['F20','Sp21','F21', …]
    sem_to_idx = {s: i for i, s in enumerate(sem_order)}

    df["semester_idx"] = df["sem_short"].map(sem_to_idx)

    bloom_for_pi = (
        df.groupby("pi")["blooms_level"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "")
    )

    # ─── 3.  fit mixed-effects model  (NEW)  ────────────────────────────
    # ─── 3.  fit mixed-effects model  ───────────────────────────────
    try:  # NEW ◀
        lmm = smf.mixedlm(
            "attain ~ semester_idx",
            data=df,
            groups="sem_short"
        ).fit(method="lbfgs")
    except (np.linalg.LinAlgError, ValueError):  # NEW ◀
        # fallback when matrix is singular (e.g. only one semester)
        X = sm.add_constant(df["semester_idx"])
        lmm = sm.OLS(df["attain"], X).fit()
        lmm.random_effects = {}  # no baselines

    # ─── coloured (or grey) dots for Plot 4 ─────────────────────────────
    if lmm.random_effects:
        u = pd.Series({k: v.values[0] for k, v in lmm.random_effects.items()}) \
            .sort_index()
        lo, hi = u.min(), u.max()

        # 1 ▸ identical baselines  → grey
        if np.isclose(lo, hi, atol=1e-9, rtol=1e-6):
            colour_fn = lambda s: "#7f7f7f"

        else:
            # 2 ▸ get candidate vmin / vcenter / vmax
            if lo < 0 < hi:
                vmin, vcenter, vmax = lo, 0.0, hi
            else:  # all positive OR all negative
                vmin, vmax = lo, hi
                vcenter = 0.5 * (vmin + vmax)

            # 3 ▸ final monotonicity check
            if not (vmin < vcenter < vmax):
                colour_fn = lambda s: "#7f7f7f"  # fallback to grey
            else:
                divnorm = colors.TwoSlopeNorm(vcenter=vcenter,
                                              vmin=vmin, vmax=vmax)
                cmap = plt.cm.RdYlGn
                colour_fn = lambda s: cmap(divnorm(u.get(s, 0)))
    else:
        colour_fn = lambda s: "#7f7f7f"  # OLS-only fallback

    # ─── 4.  build g = tidy table for plotting  (NEW)  ──────────────────
    g = (df.groupby(['sem_short', 'semester_idx'])
         .agg(mean_attain=('attain', 'mean'))
         .reset_index())

    g = g.sort_values('semester_idx')  # ensure ascending x
    # ---- design matrix for any model (const + semester_idx) --------------
    X = pd.DataFrame({
        "Intercept" if "Intercept" in lmm.params.index else "const": 1.0,
        "semester_idx": g.semester_idx
    })

    # fitted mean and standard error
    g["fit"] = lmm.predict(X)  # works for both MixedLM and OLS

    V = lmm.cov_params().loc[X.columns, X.columns]  # 2×2 covariance
    se = np.sqrt((X @ V * X).sum(axis=1))

    from scipy.stats import t
    crit = t.ppf(0.975, df=lmm.df_resid)
    g["low"] = g["fit"] - crit * se
    g["high"] = g["fit"] + crit * se

    # -----------------  PIVOT #1 : rows = semester ----------------------
    # -----------------  PIVOT #1 : rows = semester --------------------
    pivot1 = (df.groupby(["sem_short", "pi"])["attain"]
              .mean()  # averages that really exist
              .unstack()  # *no* fill_value
              .sort_index(key=lambda idx: idx.map(sem_key)))

    semesters = pivot1.index.tolist()
    pis = pivot1.columns.tolist()
    pi_index = {short_pi(p): i for i, p in enumerate(pis)}  # ← add this
    n_sem, n_pi = len(semesters), len(pis)

    # -----------------  PIVOT #2 : rows = PI + Bloom ------------------
    # -----------------  PIVOT 2 : rows = PI + Bloom -----------------
    pivot2 = (df.groupby(["pi_bl", "sem_short"])["attain"]
              .mean()
              .unstack())  # no re-index, no fill_value

    pivot2 = pivot2.dropna(how="all")  # toss rows that are all-NaN
    combo_order = pivot2.index.tolist()  # what’s left is what we plot
    n_combo = len(combo_order)

    pi_tag_for_combo = [lbl.split(" (")[0] for lbl in combo_order]
    pi_index = {short_pi(p): i for i, p in enumerate(pis) if p.strip()}

    # colour palettes – distinct-but-subtle shades per PI
    greens = plt.cm.Greens(np.linspace(0.45, 0.85, n_pi))
    reds = plt.cm.Reds(np.linspace(0.45, 0.85, n_pi))

    # -------------------  figure & axes ---------------------------------
    plt.close("all")
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(
        nrows=4,
        figsize=(8.5, 16),  # a bit more total height
        dpi=150,
        gridspec_kw=dict(
            hspace=0.8,
            height_ratios=[1, 1, 1.25, 1.6]  # ax4 is 35 % taller
        )
    )
    fig.subplots_adjust(right=0.85)

    # ===============  PLOT 1 : grouped by semester  =====================
    x1 = np.arange(n_sem)
    bar_w1 = 0.8 / n_pi
    legend_handles = []

    if n_pi:
        for i, pi in enumerate(pis):
            vals = pivot1[pi].values
            pos = x1 - 0.4 + (i + .5) * bar_w1

            # mask out semesters that have no data for this PI
            mask = ~np.isnan(vals)
            colours = [greens[i] if v >= 70 else reds[i] for v in vals[mask]]

            bars = ax1.bar(pos[mask], vals[mask],
                           width=bar_w1, color=colours,
                           edgecolor="#333", linewidth=.5)
            ax1.bar_label(bars, fmt="%.0f", padding=2, fontsize=9, color="#222")

            legend_handles.append(mpatches.Patch(color=greens[i], label=pi))

    ax1.set_ylim(0, 110)
    ax1.set_xticks(x1)
    ax1.set_xticklabels(semesters, fontsize=10)
    ax1.set_ylabel("% Expert + Practitioner", fontsize=10)
    ax1.set_title(f"{course} – {slo} (by Semester)", fontsize=11, weight="bold")
    ax1.tick_params(axis="y", labelsize=10)
    ax1.yaxis.set_major_locator(ticker.MultipleLocator(20))
    ax1.yaxis.set_minor_locator(ticker.NullLocator())
    ax1.yaxis.grid(True, linestyle="--", alpha=.35)
    ax1.spines[["right", "top"]].set_visible(False)
    ax1.set_axisbelow(True)

  #  ax1.legend(legend_handles, pis, title="PI", frameon=False,
  #             bbox_to_anchor=(1.01, 1), loc="upper left",
   #            fontsize=6, title_fontsize=7)

    # ===============  PLOT 2 : grouped by PI + Bloom  ======================
    x2 = np.arange(n_combo)
    bar_w2 = 0.8 / n_sem

    pi_tag_for_combo = [c.split(" (")[0] for c in combo_order]  # ← add this

    if n_combo:
        for j, sem in enumerate(semesters):
            vals = pivot2[sem].values
            pos = x2 - 0.4 + (j + .5) * bar_w2

            mask = ~np.isnan(vals)
            colours = [
                greens[pi_index.get(tag, 0)] if v >= 70  # safe default
                else reds[pi_index.get(tag, 0)]
                for tag, v in zip(pi_tag_for_combo, vals) if not np.isnan(v)
            ]

            bars = ax2.bar(pos[mask], vals[mask],
                           width=bar_w2, color=colours,
                           edgecolor="#333", linewidth=.5)

            for x, y in zip(pos[mask], vals[mask]):
                ax2.text(x, y + 1.2, f"{y:.0f}", ha="center",
                         va="bottom", fontsize=9, color="#222")

    # axis cosmetics
    ax2.set_ylim(0, 95)
    ax2.set_xticks(x2)
    ax2.set_xticklabels([lbl.replace(" (", "\n(") for lbl in combo_order],
                        fontsize=9)  # two-line labels
    ax2.set_ylabel("% Expert + Practitioner", fontsize=10)
    ax2.set_title(f"{course} – {slo} (by PI and Bloom)", fontsize=11,
                  weight="bold", pad=14)
    ax2.tick_params(axis="y", labelsize=10)
    ax2.yaxis.set_major_locator(ticker.MultipleLocator(20))
    ax2.yaxis.set_minor_locator(ticker.NullLocator())
    ax2.yaxis.grid(True, linestyle="--", alpha=.35)
    ax2.spines[["right", "top"]].set_visible(False)
    ax2.set_axisbelow(True)

    # ===============  PLOT 3 : Bloom‑level difficulty  ==================
    import scipy.stats as ss

    # --- gather data ---
    order = ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"]
    df["blooms_level"] = pd.Categorical(df["blooms_level"], categories=order, ordered=True)
    grouped = [g["attain"].values for _, g in df.groupby("blooms_level") if len(g)]

    # --- Kruskal‑Wallis across all Bloom levels ---
    kw_p = ss.kruskal(*grouped).pvalue if len(grouped) > 1 else None

    # --- Cliff’s Δ (rank‑biserial) : Analyze vs all others ---
    analyze = df[df.blooms_level == "Analyze"]["attain"].values
    others = df[df.blooms_level != "Analyze"]["attain"].values
    if len(analyze) and len(others):
        U = ss.mannwhitneyu(analyze, others, alternative="two-sided").statistic
        delta = (2 * U) / (len(analyze) * len(others)) - 1  # <-- correct sign
    else:
        delta = None

    # --- draw a box‑plot ---
    ax3.boxplot(
        grouped,
        tick_labels=[lvl for lvl in order  # ← rename keyword
                     if lvl in df.blooms_level.unique()],
        patch_artist=True,
        boxprops=dict(facecolor="#8DB9CA", alpha=.75),
        medianprops=dict(color="firebrick", lw=1)
    )

    ax3.axhline(70, ls="--", color="red", lw=.8)
    ax3.set_ylabel("% E + P", fontsize=10)
    ax3.set_title("Bloom‑level attainment", fontsize=11, pad=6, weight="bold")
    ax3.tick_params(axis="x", labelsize=10)
    ax3.tick_params(axis="y", labelsize=10)
    ax3.set_ylim(0, 105)
    ax3.spines[["right", "top"]].set_visible(False)

    # --- annotate p‑value and effect size ---
    txt = ""
    if kw_p is not None:
        txt += f"Kruskal‑Wallis p = {kw_p:.3f}\n"
    if delta is not None:
        txt += f"Cliff's Δ (Analyze vs others) = {delta:+.2f}"
    ax3.text(0.02, 0.06, txt, transform=ax3.transAxes,  # 6 % above bottom
             ha="left", va="bottom",
             fontsize=9, fontstyle="italic",
             bbox=dict(boxstyle="round,pad=0.3",
                       fc="#f5f5f5", ec="none", alpha=.85))

    # ── inset: normal curve visualising the p‑value ─────────────────────
    # only if we actually computed kw_p earlier
    anchor_x, anchor_y = 0.34, 0.34  # 0‑1 fraction of ax3 (x‑ and y‑position)

    # ------------------------------------------------------------
    # AFTER drawing the box‑plot & text annotation on ax3:
    # ------------------------------------------------------------
    if False and kw_p is not None:
        inset = inset_axes(
            ax3,
            width=1.3, height=1,  # 30 % of ax3 (not a string)
            bbox_to_anchor=(0.5, 0.3),  # x0, y0 in ax3 fraction units
            bbox_transform=ax3.transAxes,
            loc="center", borderpad=0
        )

        # --- bell curve drawing ---
        x = np.linspace(-4, 4, 800)
        inset.plot(x, norm.pdf(x), lw=1, color="black")

        crit = norm.ppf(0.975)  # ±1.96
        inset.fill_between(x, 0, norm.pdf(x), where=(x <= -crit) | (x >= crit),
                           color="red", alpha=.25)
        inset.fill_between(x, 0, norm.pdf(x), where=(x > -crit) & (x < crit),
                           color="green", alpha=.25)

        inset.axvline(norm.ppf(1 - kw_p / 2), color="blue", lw=1.4)
        inset.set_xticks([]);
        inset.set_yticks([])
        inset.set_xlim(-4, 4);
        inset.set_ylim(0, 0.45)
        inset.set_title(f"p = {kw_p:.3f}", fontsize=8, pad=2)

    # ------------------------------------------------------------
    # Run tight_layout AFTER the inset so it isn't clipped
    # ------------------------------------------------------------
   # fig.tight_layout(rect=[0, 0, 1, 1])  # leave 20 % for legend

    # inside the loop that scatters the dots on ax4  (replace the old line)
    colours = [colour_fn(s) for s in g.semester_idx.map(lambda i: sem_order[i])]
    ax4.scatter(g.semester_idx, g.mean_attain,
                s=80, c=colours, edgecolor="#333", label="Observed")

    ax4.plot(g.semester_idx, g.fit, lw=2.2, label='Model trend')
    ax4.fill_between(g.semester_idx, g.low, g.high, alpha=.18)
    ax4.axhline(70, ls='--', color='red', lw=.9, label='ABET 70 % target')

    ax4.set_xticks(range(len(sem_order)))
    ax4.set_xticklabels(sem_order, rotation=0, fontsize=9)
    ax4.set_ylabel('% Expert + Practitioner', fontsize=10)
    ax4.set_title(f'{course} – {slo}: mixed-effects trend',
                  fontsize=11, weight='bold')
    # ------------------- annotate β₁ and p-value ----------------------------
    slope = lmm.params['semester_idx']  # β₁
    pval = lmm.pvalues['semester_idx']  # two-sided p

    label = (
        f"$\\beta_1$ = {slope:+.2f}\n"  # newline now works
        f"$p$ = {pval:.3f}"
    )

    ax4.text(0.02, 0.94, label,
             transform=ax4.transAxes,
             ha='left', va='top', fontsize=9,
             bbox=dict(boxstyle='round,pad=0.3',
                       fc='#f5f5f5', ec='none', alpha=0.85))
    ax4.legend(
        fontsize=8,
        loc='lower right',  # always bottom-right of the axes
        frameon=False  # optional – removes the legend box border
    )
    ax4.spines[['right', 'top']].set_visible(False)

    fig.tight_layout()

    # ----------------  export figure to base‑64  -------------------------
    buf = BytesIO()
    fig.savefig(buf, format="png")  # ← saves the right figure
    img64 = base64.b64encode(buf.getvalue()).decode()

    # ───────────────────────────  END PLOT  ------------------------------

    html_main = f"""
    <!doctype html><html><head><title>{course} {slo}</title></head>
    <body style="margin:0;display:flex;justify-content:center;align-items:center;height:100vh;background:#f7f9fc">
      <img src="data:image/png;base64,{img64}"
           style="max-width:38%;height:auto;box-shadow:0 4px 18px rgba(0,0,0,.15);border-radius:8px">
    </body></html>
    """

    # open 2nd window via JS, then replace current document with html_main
    return f"""
    <!doctype html>
    <html>
    <head><title>{course} {slo}</title></head>

    <body style="margin:0;display:flex;justify-content:center;align-items:center;
                 height:100vh;background:#f7f9fc">

      <!-- main 5-panel figure -->
      <img src="data:image/png;base64,{img64}"
           style="max-width:38%;height:auto;
                  box-shadow:0 4px 18px rgba(0,0,0,.15);border-radius:8px">

      <!-- when this page finishes loading, pop the control chart -->

    </body>
    </html>
    """

@parent.route("/analyze_slo")
@login_required
def analyze_slo():
    # ── ensure NLTK data (punkt + punkt_tab + stopwords) is present ──────────
    # ── make sure the 3 tiny NLTK datasets rake-nltk needs are present ─────────
    import pathlib, nltk

    for pkg, res in [
        ("punkt", "tokenizers/punkt"),  # sentence tokenizer
        ("punkt_tab", "tokenizers/punkt_tab"),  # …its tables
        ("stopwords", "corpora/stopwords")]:  # RAKE’s stop-word list
        try:
            nltk.data.find(res)  # already on disk?
        except LookupError:
            nltk.download(pkg, quiet=True,  # grab it once
                          download_dir=str(pathlib.Path.home() / "nltk_data"))

    from ABET_Data_Rev1 import get_conn
    slo = request.args.get("slo","").strip()
    if not slo:
        return "<script>alert('Select an SLO first');window.close();</script>"

    with get_conn() as conn:
        # ─── grab the numeric data that drives the plots ─────────────────
        q_num = """
                SELECT course, pi, blooms_level, semester,
                       expert + practitioner AS attain
                  FROM abet_entries
                 WHERE slo = ?
        """
        df = pd.read_sql_query(q_num, conn, params=(slo,))

        # ─── NEW: grab the two narrative columns too ─────────────────────
        q_nar = """
                SELECT course, semester, pi, blooms_level,
                       explanation AS "Why this tool & Bloom level?",
                       observations AS "Instructor observations"
                  FROM abet_entries
                 WHERE slo = ?
                ORDER BY course, semester, pi
        """
        nar_df = pd.read_sql_query(q_nar, conn, params=(slo,))
        nar_table = nar_df.copy()  # <- keep an unfiltered copy for the HTML table


    if df.empty:
        return "<script>alert('No data for this SLO');window.close();</script>"

    from rake_nltk import Rake
    _rake = Rake(max_length=3)  # up to 3-word key-phrases

    def ai_tag(text: str) -> str | None:
        """
        Return the highest-scoring RAKE key-phrase (≤ 3 words, Title-case).
        Fallback: None if nothing found.
        """
        if not text or len(text) < 12:  # too short
            return None
        _rake.extract_keywords_from_text(text)
        phrases = _rake.get_ranked_phrases()
        if not phrases:
            return None
        tag = phrases[0].title()  # best phrase
        if len(tag.split()) == 1:  # ← NEW: verb alone? skip it
            return None
        return tag[:35]  # truncate long ones

    # ─────────────────────  DATA CLEAN-UP  ──────────────────────────────
    df["pi"] = df["pi"].astype(str).str.strip()
    df = df[df["pi"] != ""]                      # drop blank PI rows

    # map Bloom and semester helpers re-use your earlier functions
    orderB = ["Remember","Understand","Apply","Analyze","Evaluate","Create"]
    df["blooms_level"] = pd.Categorical(df["blooms_level"],
                                        categories=orderB, ordered=True)

    # helper: "PI-1: Able to …" → "PI-1"
    def short_pi(txt: str) -> str:
        return txt.split(":")[0].strip()

    df["pi_bl"] = (
            df["pi"].apply(short_pi) +
            " (" + df["blooms_level"].astype(str) + ")"  # ← cast to str
    )

    # semester label helpers ── reuse the course-level versions
    def short_sem(sem: str) -> str:
        try:
            season, yr = sem.split()
            tag = "F" if season.lower().startswith("f") else "Sp"
            return f"{tag}{yr[-2:]}"
        except ValueError:
            return sem

    def sem_key(tag: str) -> int:  # F20 → 40201, Sp21 → 40202 …
        if tag.startswith("F"):
            return int("20" + tag[1:]) * 2 + 1
        elif tag.startswith("Sp"):
            return int("20" + tag[2:]) * 2
        return 10 ** 9

    df["sem_short"] = df["semester"].apply(short_sem)

    # ─────────────────────  FIGURE  ─────────────────────────────────────
    # ─────────────────────  FIGURE  (4 panels)  ────────────────────────
    plt.close("all")
    fig, (axA, axB, axC, axD) = plt.subplots(
        nrows=4,
        figsize=(9.5, 14.8),  # a bit taller for the 4th plot
        dpi=150,
        gridspec_kw=dict(
            hspace=0.72,
            height_ratios=[1.05, 1.05, 1.3, 1.6]
        )
    )

    # === A ░░ Course-wise attainment bar-chart ░░ ======================
    # === A ░░ Course-wise attainment bar-chart ░░ ======================
    crit95 = 1.96  # two-sided 95 % z
    course_stats = (
        df.groupby("course")["attain"]
        .agg(mean="mean", std="std", n="count")
    )
    course_stats["se"] = course_stats["std"] / np.sqrt(course_stats["n"])
    course_stats["hi"] = course_stats["mean"] + crit95 * course_stats["se"]

    # sort by mean descending so best course on top
    course_stats = course_stats.sort_values("mean", ascending=False)

    # colour logic
    def pick_colour(row):
        good = (row["mean"] >= 70) or (row["hi"] >= 70)
        return "#4d9078" if good else "#c62828"  # green / red

    #colours = course_stats.apply(pick_colour, axis=1)
    # colour logic  (mean ≥ 70 → green, else red)
    colours = np.where(course_stats["mean"] >= 70, "#4d9078", "#c62828")

    ypos = np.arange(len(course_stats))  # 0,1,2,…

    axA.barh(
        ypos, course_stats["mean"],
        xerr=crit95 * course_stats["se"],
        color=colours, height=0.6,
        edgecolor="#333", linewidth=.6, capsize=4
    )

    axA.axvline(70, ls="--", color="red", lw=1)
    axA.set_yticks(ypos)
    axA.set_yticklabels(course_stats.index)
    axA.set_xlabel("% Expert + Practitioner")
    axA.set_title(f"{slo} – average attainment per course",
                  weight="bold", fontsize=12)

    for y, v in zip(ypos, course_stats["mean"]):
        axA.text(v + 1.5, y, f"{v:.0f}", va="center", fontsize=9)

    axA.invert_yaxis()  # best course on top
    axA.spines[["right", "top"]].set_visible(False)

    # === B ░░ Bloom-level box-plot across ALL courses ░░ ===============
    # === B ░░ Bloom-level box-plot across ALL courses ░░ ===============
    # NOTE: pass observed=False to silence the pandas FutureWarning
    grouped = [g["attain"].values for _, g in
               df.groupby("blooms_level", observed=False) if len(g)]
    ticks = [lvl for lvl in orderB if lvl in df.blooms_level.unique()]
    axB.boxplot(grouped, patch_artist=True,
                boxprops=dict(facecolor="#8DB9CA", alpha=.75),
                medianprops=dict(color="firebrick", lw=1))
    axB.axhline(70, ls="--", color="red", lw=.9)
    axB.set_xticklabels(ticks, rotation=0, fontsize=9)
    axB.set_ylabel("% Expert + Practitioner")
    axB.set_title(f"SLO {slo} – Bloom-level distribution (all courses)",
                  weight="bold", fontsize=12)
    axB.spines[["right", "top"]].set_visible(False)

    # --- Kruskal–Wallis (all Bloom levels) + Cliff’s Δ (Analyze vs others) ---
    import scipy.stats as ss

    def safe_kruskal(groups):
        """Return p-value or None if groups are insufficient or constant."""
        vals = [np.asarray(g, float) for g in groups if len(g)]
        if len(vals) < 2:
            return None
        allv = np.concatenate(vals)
        # if every number is identical → KW is undefined in SciPy
        if allv.size and np.allclose(allv, allv[0]):
            return None
        try:
            return ss.kruskal(*vals).pvalue
        except ValueError:
            return None

    def safe_cliffs_delta(a, b):
        """Rank-biserial effect size via Mann–Whitney U; None if not computable."""
        a = np.asarray(a, float);
        b = np.asarray(b, float)
        if a.size == 0 or b.size == 0:
            return None
        # if all values identical in both samples, Δ = 0 (no dominance)
        if np.allclose(a, a[0]) and np.allclose(b, b[0]) and np.isclose(a[0], b[0]):
            return 0.0
        try:
            U = ss.mannwhitneyu(a, b, alternative="two-sided").statistic
            return (2 * U) / (a.size * b.size) - 1
        except ValueError:
            return None

    present = [lvl for lvl in orderB if lvl in df.blooms_level.unique()]
    grouped_vals = [df.loc[df.blooms_level == lvl, "attain"].values
                    for lvl in present]
    kw_p = safe_kruskal(grouped_vals)

    analyze = df.loc[df.blooms_level == "Analyze", "attain"].values
    others = df.loc[df.blooms_level != "Analyze", "attain"].values
    delta = safe_cliffs_delta(analyze, others)

    # --- annotate (show 'n/a' for constant/insufficient cases) ---
    lines = []
    lines.append(f"Kruskal-Wallis p = {kw_p:.3f}" if kw_p is not None else "Kruskal-Wallis: n/a")
    lines.append(f"Cliff's Δ (Analyze vs others) = {delta:+.2f}"
                 if delta is not None else "Cliff's Δ: n/a")
    axB.text(0.02, 0.06, "\n".join(lines),
             transform=axB.transAxes,
             ha="left", va="bottom",
             fontsize=9, fontstyle="italic",
             bbox=dict(boxstyle="round,pad=0.30", fc="#f5f5f5", ec="none", alpha=.85))

    # === C ░░ semester trend across ALL courses ░░ ======================
    sem_mean = (df.groupby("sem_short")["attain"]
                .mean()
                .sort_index(key=lambda s: s.map(sem_key)))

    # ─── intervention arrows with distilled tag ─────────────────────────
    import re, string
    STOP = {"a", "an", "the", "of", "to", "for", "on", "in", "with", "by", "and",
            "all", "every", "each", "this", "that", "those", "these", "have", "has"}
    VERBS = ("added|implemented|introduced|redesigned|revised|flipped|"
             "launched|adopted|created|deployed|removed|expanded|updated")
    # list of words that signal a course intervention
    KEYWORDS = {
        "added", "introduced", "implemented", "redesigned", "revised",
        "flipped", "created", "launched", "updated", "expanded",
        "removed", "action plan", "curriculum change", "intervention"
    }
    KEYWORDS |= {"lecture", "quiz", "rubric", "worksheet", "project",
                 "quizlet", "video", "tutorial"}
    verb_pat = re.compile(rf"\b({VERBS})\b", flags=re.I)

    def tag_clear(text: str) -> str | None:
        if not text:
            return None
        m = verb_pat.search(text.lower())
        if not m:
            return None

        verb = m.group(1).capitalize()
        tail = re.split(r"[.;:\n]", text[m.end():], maxsplit=1)[0]

        words = [w.strip(string.punctuation) for w in tail.split()]
        keep = [w.title() for w in words
                if w.lower() not in STOP and len(w) > 2][:2]

        return f"{verb} {' '.join(keep)}" if keep else verb

    import re, string

    VERBS = ("added|introduced|implemented|redesigned|revised|flipped|"
             "created|adopted|launched|updated|expanded|removed|deployed")
    verb_re = re.compile(rf"\b({VERBS})\b", re.I)

    STOP = {"a", "an", "the", "of", "to", "for", "in", "on", "with", "by", "and",
            "all", "each", "every", "this", "that", "these", "those",
            "have", "has", "was", "were", "is", "are", "be", "been"}

    FILLER = {"lecture", "lectures", "step", "steps", "material", "materials",
              "content", "activity", "activities", "worksheet", "worksheets",
              "lab", "labs", "rubric", "rubrics", "project", "projects",
              "assignment", "assignments", "quiz", "quizzes", "homework", "hw"}

    def short_tag(txt: str) -> str | None:
        """
        Return 'Verb Word Word' (≤ 3 words) or None if nothing descriptive.
        """
        if not txt:
            return None

        m = verb_re.search(txt.lower())
        if not m:
            return None

        verb = m.group(1).capitalize()
        tail = txt[m.end():]

        def pick(max_keep: int) -> list[str]:
            words = [w.strip(string.punctuation) for w in tail.split()]
            return [w.title() for w in words
                    if w.lower() not in STOP and len(w) > 2][:max_keep]

        keep = pick(3)  # try up to 3 words first
        if not keep:  # if all were filler…
            keep = [w.title() for w in tail.split()  # keep *any* word
                    if w.lower() not in STOP][:2]

        if not keep:
            return None  # nothing useful → skip

        return " ".join([verb] + keep)

    # --------------------------------------------------------------------
    # ---- build tags ONLY for arrows; do not mutate nar_table ----
    nar_arrows = nar_df.copy()
    nar_arrows["sem_short"] = nar_arrows["semester"].apply(short_sem)
    nar_arrows["tag"] = (
            nar_arrows["Instructor observations"].fillna("") + " " +
            nar_arrows["Why this tool & Bloom level?"].fillna("")
    ).apply(ai_tag)

    ACTION_VERBS = """
        Added Introduced Required Mandated Repeated Warned Assigned Allowed
        Recorded Documented Planned Will plan Encouraged Improved Enhanced
        Strengthened Exported Shared Aligned Standardized Calibrated Expanded
        Embedded Integrated Piloted Monitored Tracked Institutionalized
        Implemented Refined Revised Modified Hosted Discussed Measured Collected
        Surveyed Practiced
    """.lower().split()
    base = {v.rstrip("ed").rstrip("d") for v in ACTION_VERBS}
    GOOD_VERBS = set(ACTION_VERBS) | base

    first = nar_arrows["tag"].str.split().str[0].str.lower()
    mask = nar_arrows["tag"].notna() & first.isin(GOOD_VERBS)
    nar_arrows = nar_arrows[mask]

    tags_by_sem = (nar_arrows[nar_arrows["tag"].notna()]
                   .groupby("sem_short")["tag"]
                   .apply(list)
                   .to_dict())

    xpos = {s: i for i, s in enumerate(sem_mean.index)}

    for sem, tags in tags_by_sem.items():
        if sem not in xpos:
            continue
        x, y = xpos[sem], sem_mean[sem]

        # arrow
        axC.annotate("", xy=(x, y), xytext=(x, y - 6),
                     arrowprops=dict(arrowstyle="->", lw=1.1,
                                     color="#9146ff", shrinkA=0, shrinkB=0))

        # label: no wrap; show up to two tags on separate micro-lines
        label = "\n".join(tags[:2])
        #axC.text(x + 0.15, y - 6.1, label,
        #         fontsize=6, color="#9146ff",
        #         ha="left", va="top", linespacing=0.9)

    sem_idx = np.arange(len(sem_mean))  # 0,1,2,… in chronological order

    # ─── fit simple OLS:  y = β0 + β1·semester_idx  ──────────────────────
    X = sm.add_constant(sem_idx)  # adds the intercept column
    ols = sm.OLS(sem_mean.values, X).fit()
    slope = float(ols.params[1]) if len(ols.params) > 1 else 0.0  # NEW
    pval = float(ols.pvalues[1]) if len(ols.params) > 1 else 1.0  # NEW

    pred = ols.get_prediction(X)
    low95, high95 = pred.conf_int().T  # two 1-D arrays

    # ─── plot ────────────────────────────────────────────────────────────
    axC.plot(sem_mean.index, sem_mean.values,
             marker='o', lw=1.5, color="#005158", label="Observed")
    axC.plot(sem_mean.index, ols.fittedvalues,
             lw=2.2, color="#2d7b82", label="Trend line")
    axC.fill_between(sem_mean.index, low95, high95,
                     color="#2d7b82", alpha=.15, label="95 % CI")
    axC.legend(fontsize=8, loc="upper left")
    axC.axhline(70, ls="--", color="red", lw=1, label="ABET 70 %")

    # numeric labels on the dots
    for x, y in zip(sem_mean.index, sem_mean.values):
        axC.text(x, y + 1.2, f"{y:.0f}", ha="center", fontsize=9)

    axC.set_ylabel("% Expert + Practitioner")
    axC.set_title(f"{slo} – overall attainment per semester",
                  weight="bold", fontsize=12)
    axC.set_xticks(range(len(sem_mean)))
    axC.set_xticklabels(sem_mean.index, rotation=0, ha="right", fontsize=9)

    axC.spines[["right", "top"]].set_visible(False)

    # slope + p-value annotation (optional but handy)
    #slope, pval = ols.params[1], ols.pvalues[1]
    axC.text(0.02, 0.07,
             f"$\\beta_1$ = {slope:+.2f} pp/term\n$p$ = {pval:.3f}",
             transform=axC.transAxes, ha="left", va="bottom", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.3", fc="#f5f5f5", ec="none", alpha=.85))

    axC.legend(fontsize=8, loc="lower right")

    # annotate each point
    for x, y in zip(sem_mean.index, sem_mean.values):
        axC.text(x, y + 1.2, f"{y:.0f}", ha="center", fontsize=9)

    # === D ░░ PI-wise semester trend (NEW) ░░ =========================
    # 1  pivot to get a matrix   rows = PI-tag,  cols = semester
    # ---- PI-wise semester trend ------------------------------------------
    # === D ░░ PI-wise semester trend  (with mixed-effects lines) ░░ ========
    # === D ░░ PI-wise mixed-effects trends – separated clusters ░░ ========
    df["pi_tag"] = df["pi"].apply(short_pi)
    sem_cols = sem_mean.index  # ordered semesters

    pivot_pi = (df.groupby(["pi_tag", "sem_short"])["attain"]
                .mean()
                .unstack()) \
        .reindex(columns=sem_cols, fill_value=np.nan) \
        .sort_index()

    n_pi = len(pivot_pi)
    n_sem = len(sem_cols)
    gap = 1  # blank column between clusters
    cmap = plt.colormaps.get_cmap("tab20").resampled(n_pi)

    # helper to centre the PI label
    cluster_center = lambda i: i * (n_sem + gap) + 0.5 * (n_sem - 1)

    for i, (pi, _) in enumerate(pivot_pi.iterrows()):

        sub = df[df["pi_tag"] == pi].copy()
        # map semester → 0…n_sem-1 inside its own cluster
        sub["intra_idx"] = sub["sem_short"].map({s: j for j, s in enumerate(sem_cols)})
        sub["x"] = sub["intra_idx"] + i * (n_sem + gap)

        # ── model fit (same fallback logic) ──────────────────────────────
        try:
            # ── Mixed-effects: works if ≥ 2 semesters ──────────────────────
            mdl = smf.mixedlm("attain ~ intra_idx", data=sub, groups="sem_short") \
                .fit(method="lbfgs")
            fe = mdl.fe_params  # β₀, β₁
            cov = mdl.cov_params().loc[["Intercept", "intra_idx"],  # 2×2
            ["Intercept", "intra_idx"]]

        except Exception:  # singular, 1-semester PI, etc. → fall back to OLS
            mdl = sm.OLS(sub["attain"], sm.add_constant(sub["intra_idx"])).fit()

            # normalise names so the rest of the code is agnostic
            fe = mdl.params.rename({"const": "Intercept"})
            cov = mdl.cov_params()
            cov.index = cov.index.str.replace("const", "Intercept")
            cov.columns = cov.columns.str.replace("const", "Intercept")
            cov = cov.loc[["Intercept", "intra_idx"], ["Intercept", "intra_idx"]]

        # common helper for the 95 % CI
        seX = lambda x: np.sqrt([1, x] @ cov @ [1, x])

        x_rel = np.arange(n_sem)
        x_abs = x_rel + i * (n_sem + gap)
        fit = fe["Intercept"] + fe["intra_idx"] * x_rel
        ci95 = 1.96 * np.vectorize(seX)(x_rel)

        # raw means per semester
        axD.plot(x_abs, pivot_pi.loc[pi].values, "o",
                 ms=5, color=cmap(i), alpha=.8)

        # mixed-effects line + ribbon
        axD.plot(x_abs, fit, lw=2, color=cmap(i))
        axD.fill_between(x_abs, fit - ci95, fit + ci95, color=cmap(i), alpha=.10)

        # PI label centred over its cluster
        axD.text(cluster_center(i), axD.get_ylim()[1] * 0.97, pi,
                 ha="center", va="top", fontsize=9, weight="bold")

    # cosmetics ---------------------------------------------------------------
    axD.axhline(70, ls="--", color="red", lw=1)
    axD.set_ylabel("% Expert + Practitioner")
    axD.set_title(f"SLO {slo} – PI-wise mixed-effects trends",
                  weight="bold", fontsize=12)

    # hide x-tick labels; show generic “semester” under each cluster
    # ── x-axis: show real semester tags under every cluster  --------------
    xticks = []
    xlabels = []
    for i in range(n_pi):
        for j, sem in enumerate(sem_cols):
            xticks.append(j + i * (n_sem + gap))
            xlabels.append(sem)

    axD.set_xticks(xticks)
    axD.set_xticklabels(xlabels, rotation=30, ha="right", fontsize=8)
    axD.spines[["right", "top"]].set_visible(False)

    fig.tight_layout()

    # ---------- embed to HTML ------------------------------------------
    buf = BytesIO()
    fig.savefig(buf, format="png")
    img64 = base64.b64encode(buf.getvalue()).decode()

    # ----------------  HTML table for the narratives  -----------------
    table_css = (
        "border-collapse:collapse;margin:1.4rem auto;width:96%;"
        "font-family:Poppins,sans-serif;font-size:.9rem"
    )
    th_css = ("background:#003638;color:#fff;padding:.5rem .6rem;"
              "border:1px solid #ddd;")
    td_css = ("padding:.45rem .55rem;border:1px solid #ddd;")

    # Fill empties to keep the table readable
    nar_table = nar_table.fillna("—")

    html_table = nar_table.to_html(index=False, escape=False,
                                   classes="nar",
                                   table_id="nar",
                                   border=0)

    # patch in-line styles
    html_table = (
        html_table
        .replace('<table border="0" class="nar" id="nar">',
                 f'<table style="{table_css}">')
        .replace('<th>', f'<th style="{th_css}">')
        .replace('<td>', f'<td style="{td_css}">')
    )

    return f"""
    <!doctype html><html><head><title>SLO {slo} analysis</title></head>
    <body style="margin:0;background:#f7f9fc;font-family:Poppins,sans-serif">

    <div style="display:flex;flex-direction:column;align-items:center;padding:1.5rem">
      <img src="data:image/png;base64,{img64}"
           style="max-width:90%;height:auto;
                  box-shadow:0 4px 18px rgba(0,0,0,.15);border-radius:8px">
      {html_table}
    </div>

    </body></html>
    """
from flask import jsonify
import json

@parent.route("/survey/start", methods=["GET","POST"])
def survey_start():
    # No faculty login required; Grad Survey is separate from /abet
    if request.method == "POST":
        session["grad_student_name"] = request.form.get("student_name","").strip()
        session["grad_year"] = request.form.get("year_graduated","").strip()
        session["grad_job"]  = request.form.get("job_plan","").strip()
        if not session["grad_student_name"] or not session["grad_year"]:
            return render_template_string(SURVEY_START_HTML)
        return redirect("/survey/form")
    return render_template_string(SURVEY_START_HTML)

# ------------------ Page 2: the full survey ------------------
SURVEY_FORM_HTML = r"""
<!doctype html><html><head>
<meta charset="utf-8"><title>Capstone Exit Survey</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&family=Playfair+Display:wght@600&display=swap" rel="stylesheet">
<style>
/* --- header/footer --- */
.site-hdr{width:100%;background:linear-gradient(90deg,#003638 0%,#005158 50%,#00736f 100%);
  box-shadow:0 4px 12px rgba(0,0,0,.08);padding:2.2rem 1rem 2.4rem;display:flex;justify-content:center;
  border-top-left-radius:12px;border-top-right-radius:12px}
.hdr-inner{text-align:center;color:#fff;text-shadow:0 2px 4px rgba(0,0,0,.35);line-height:1.35}
.hdr-title{font-family:'Poppins',sans-serif;font-size:2rem;font-weight:800;letter-spacing:.5px;margin-bottom:.35rem}
.hdr-subtitle{font-family:'Playfair Display',serif;font-size:1.3rem;font-weight:600;font-style:italic;letter-spacing:.4px;opacity:.95}
footer.copyright{width:100%;margin-top:2.5rem;padding:.9rem 0;background:linear-gradient(90deg,#003638 0%,#005158 100%);
  color:#fff;font-size:.9rem;font-weight:600;text-align:center;box-shadow:0 -4px 10px rgba(0,0,0,.05)}

/* --- page shell --- */
*{box-sizing:border-box;font-family:Poppins,sans-serif}
body{margin:0;background:#f7f9fc;color:#252525}
.wrap{max-width:960px;margin:2rem auto;background:#fff;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.10);padding:1.2rem 1.2rem 1.6rem}
h1{font-size:1.35rem;margin:.3rem 0 1rem;color:#003638}
h2{font-size:1.05rem;margin:1.1rem 0 .6rem;color:#003638}

/* --- section cards with accent bar --- */
.card{position:relative;padding:1rem 1.1rem 1rem 1.5rem;border-radius:14px;border:1px solid #e8ecef;background:#ffffff;
  box-shadow:0 6px 18px rgba(0,0,0,.06);margin-bottom:1.2rem}
.card::before{content:"";position:absolute;left:10px;top:12px;bottom:12px;width:5px;border-radius:6px;
  background:linear-gradient(180deg,#ee7f2f 0%,#f3b079 100%)}
.wrap form > .card:nth-of-type(even){background:#f8fbfd}

/* --- question tiles --- */
.field{position:relative;margin:.65rem 0;padding:.8rem 1rem .8rem 1.2rem;border-radius:12px;background:#ffffff;
  border:1px solid #eef2f5;box-shadow:0 2px 8px rgba(0,0,0,.05)}
.field::before{content:"";position:absolute;left:.6rem;top:.7rem;bottom:.7rem;width:3px;border-radius:3px;background:#dfe9f2}
.field:nth-of-type(even){background:#f9fbff}

/* --- controls --- */
label.bold{font-weight:600}
/* --- radio/checkbox rows: tight grid so text wraps inside the tile --- */
label.block{
  display: grid;
  grid-template-columns: 20px 1fr;   /* dot | text */
  align-items: start;
  column-gap: .55rem;
  row-gap: 0;                         /* keep rows compact */
  padding: .25rem 0;
}

label.block input[type="radio"],
label.block input[type="checkbox"]{
  margin-top: .2rem;                 /* optically center the dot/box */
}

label.block .lbl{
  white-space: normal;               /* allow wrapping */
  word-break: break-word;            /* never overflow outside the card */
  line-height: 1.25;
}

input,textarea,select{width:100%;padding:.6rem .7rem;border:1px solid #ccc;border-radius:8px;background:#fafafa}
textarea{min-height:90px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
button{margin-top:1rem;width:100%;padding:.8rem 1rem;border:none;border-radius:10px;background:#ee7f2f;color:#fff;font-weight:700;cursor:pointer}

/* Likert table */
table.lik{border-collapse:collapse;width:100%;font-size:.92rem;background:#fff;border-radius:12px;box-shadow:0 3px 12px rgba(0,0,0,.05)}
table.lik th,table.lik td{border:1px solid #e0e0e0;padding:.45rem .5rem;text-align:center}
table.lik th:first-child,table.lik td:first-child{text-align:left;font-weight:600}
table.lik th{background:#f1f6f8}
table.lik tr:nth-child(even) td{background:#fbfdff}
small.hint{display:block;color:#666;margin-top:.15rem}
</style>
</head><body>
<header class="site-hdr">
  <div class="hdr-inner">
    <div class="hdr-title">UTRGV Department of Mechanical Engineering</div>
    <div class="hdr-subtitle">Center for Aerospace Research</div>
  </div>
</header>

<div class="wrap">
  <h1>Capstone Exit Survey</h1>
  <form method="post" id="capstoneForm">

    <!-- A. Capstone Project Experience (SOs 1–7) -->
    <div class="card">
      <h2>A. Capstone Project Experience</h2>
      <table class="lik">
        <thead>
          <tr>
            <th>Statement</th>
            <th>Strongly Disagree</th>
            <th>Disagree</th>
            <th>Agree</th>
            <th>Strongly Agree</th>
          </tr>
        </thead>
        <tbody>
          {% for key, text in [
            ("so1", "In our capstone project, I felt confident tackling open-ended engineering problems with no single correct solution."),
            ("so2", "Our team’s design work required balancing technical feasibility with safety, cost, sustainability, and societal impact."),
            ("so3", "Capstone improved my ability to present technical work clearly to both engineers and non-engineers (written, oral, graphical)."),
            ("so4", "During our project, we considered ethical, environmental, or societal impacts in making design decisions."),
            ("so5", "Our capstone team effectively shared leadership, delegated tasks, and held one another accountable."),
            ("so6", "I am confident designing tests, analyzing data, and drawing conclusions to support engineering decisions."),
            ("so7", "Capstone pushed me to independently learn new tools, skills, or knowledge that weren’t covered in class.")
          ] %}
          <tr>
            <td>{{ text }}</td>
            {% for opt in ["Strongly Disagree","Disagree","Agree","Strongly Agree"] %}
              <td><input type="radio" name="cap_{{key}}" value="{{opt}}" required></td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <!-- B. Program Readiness & Experience -->
    <div class="card">
      <h2>B. Program Readiness & Experience</h2>
      <table class="lik">
        <thead>
          <tr>
            <th>Statement</th>
            <th>Strongly Disagree</th>
            <th>Disagree</th>
            <th>Agree</th>
            <th>Strongly Agree</th>
          </tr>
        </thead>
        <tbody>
          {% for key, text in [
            ("ready1","Capstone helped me see how my coursework connects to professional engineering practice."),
            ("ready2","I feel prepared to succeed in my next step (engineering job or graduate program)."),
            ("ready3","Faculty guidance and feedback during capstone supported my learning and growth."),
            ("ready4","The program strengthened my ability to work across disciplines and with diverse perspectives.")
          ] %}
          <tr>
            <td>{{ text }}</td>
            {% for opt in ["Strongly Disagree","Disagree","Agree","Strongly Agree"] %}
              <td><input type="radio" name="cap_{{key}}" value="{{opt}}" required></td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <!-- C. Open-Ended Reflection -->
    <div class="card">
      <h2>C. Open-Ended Reflection</h2>
      <div class="field">
        <label class="bold">1) What aspect of capstone most helped you feel “career-ready”?</label>
        <textarea name="cap_open_best" required></textarea>
      </div>
      <div class="field">
        <label class="bold">2) What skill or topic do you wish the program had emphasized more before capstone?</label>
        <textarea name="cap_open_gap" required></textarea>
      </div>
      <div class="field">
        <label class="bold">3) Any additional comments or suggestions for improving capstone or the BSME program?</label>
        <textarea name="cap_open_more" required></textarea>
      </div>
    </div>

    <!-- D. Placement Information -->
    <div class="card">
      <h2>D. Placement Information</h2>
      <div class="grid2">
        <div class="field">
          <label class="bold">Year of graduation</label>
          <select name="cap_year" required>
            <option value="" disabled selected>Select year</option>
            {% for y in range(2018, 2033) %}
              <option>{{ y }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="field">
            <label class="bold">Current status</label>
            <label class="block"><input type="radio" name="cap_status" value="Employed as engineer" required> <span class="lbl">Employed as engineer</span></label>
            <label class="block"><input type="radio" name="cap_status" value="Employed outside engineering" required> <span class="lbl">Employed outside engineering</span></label>
            <label class="block"><input type="radio" name="cap_status" value="Accepted to graduate program" required> <span class="lbl">Accepted to graduate program</span></label>
            <label class="block"><input type="radio" name="cap_status" value="Planning to apply to graduate school" required> <span class="lbl">Planning to apply to graduate school</span></label>
            <label class="block"><input type="radio" name="cap_status" value="Seeking employment" required> <span class="lbl">Seeking employment</span></label>
            <label class="block"><input type="radio" name="cap_status" value="Other" required> <span class="lbl">Other</span></label>
        </div>
      </div>

      <div class="grid2">
        <div class="field">
          <label class="bold">If employed, Job title & Company</label>
          <input name="cap_job_info" placeholder="e.g., Design Engineer — Acme Corp">
          <small class="hint">Required if “Employed as engineer” or “Employed outside engineering”.</small>
        </div>
        <div class="field">
          <label class="bold">If in graduate school, Program & Institution</label>
          <input name="cap_grad_info" placeholder="e.g., MSME — UT Austin">
          <small class="hint">Required if “Accepted to graduate program”.</small>
        </div>
      </div>
    </div>

    <button type="submit">Submit Survey</button>
  </form>
</div>

<footer class="copyright">©2025 Center for Aerospace Research</footer>

<script>
/* Conditional requirements for placement fields */
document.getElementById('capstoneForm').addEventListener('submit', function(e){
  const status = document.querySelector("input[name='cap_status']:checked");
  const job    = document.querySelector("input[name='cap_job_info']");
  const grad   = document.querySelector("input[name='cap_grad_info']");
  if(status){
    if((status.value === "Employed as engineer" || status.value === "Employed outside engineering") && !job.value.trim()){
      alert("Please provide Job title & Company.");
      e.preventDefault(); return;
    }
    if(status.value === "Accepted to graduate program" && !grad.value.trim()){
      alert("Please provide Program & Institution.");
      e.preventDefault(); return;
    }
  }
});
</script>
</body></html>
"""

@parent.route("/survey/form", methods=["GET","POST"])
def survey_form():
    if request.method == "POST":
        form = request.form

        # ---- Capstone-specific validation (no old student-info fields) ----
        cap_year   = (form.get("cap_year") or "").strip()
        cap_status = (form.get("cap_status") or "").strip()
        if not cap_year or not cap_status:
            return "<script>alert('Please select Year of graduation and Current status.');history.back();</script>"

        # Conditional details
        job_info  = (form.get("cap_job_info")  or "").strip()
        grad_info = (form.get("cap_grad_info") or "").strip()
        if cap_status in ("Employed as engineer", "Employed outside engineering") and not job_info:
            return "<script>alert('Please provide Job title & Company.');history.back();</script>"
        if cap_status == "Accepted to graduate program" and not grad_info:
            return "<script>alert('Please provide Program & Institution.');history.back();</script>"

        # ---- capture everything they submitted (including checkbox/radio groups) ----
        answers = {}
        for k in form.keys():
            vals = form.getlist(k)
            answers[k] = vals if len(vals) > 1 else vals[0]

        # Tag this survey type so you can separate later in analysis (optional but useful)
        answers["_survey_type"] = "capstone_exit"

        # ---- columns used by your DB schema ----
        # You don't ask for name in the capstone survey, so store empty or derive later if needed.
        student_name   = ""
        year_graduated = cap_year
        # Store a compact "plan" string; you can reconstruct richer detail from answers_json later.
        job_plan = cap_status
        if job_info:
            job_plan += f" | {job_info}"
        if grad_info:
            job_plan += f" | {grad_info}"

        payload = (
            student_name,
            year_graduated,
            job_plan,
            json.dumps(answers, ensure_ascii=False),
        )

        with get_survey_conn() as conn:
            conn.execute("""
                INSERT INTO graduate_survey_responses
                    (student_name, year_graduated, job_plan, answers_json)
                VALUES (?, ?, ?, ?)
            """, payload)
            conn.commit()

        return redirect("/survey/thanks")

    return render_template_string(SURVEY_FORM_HTML)

@parent.route("/survey/thanks")
def survey_thanks():
    return """
    <!doctype html><html><head><meta charset="utf-8"><title>Thank you</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&family=Playfair+Display:wght@600&display=swap" rel="stylesheet">
    <style>
      *{box-sizing:border-box;font-family:Poppins,sans-serif}
      body{margin:0;background:#f7f9fc;color:#252525;display:flex;flex-direction:column;min-height:100vh}
      .site-hdr{
        width:100%;
        background:linear-gradient(90deg,#003638 0%,#005158 50%,#00736f 100%);
        box-shadow:0 4px 12px rgba(0,0,0,.08);
        padding:2.2rem 1rem 2.4rem;
        display:flex;justify-content:center;
      }
      .hdr-inner{text-align:center;color:#fff;text-shadow:0 2px 4px rgba(0,0,0,.35);line-height:1.35}
      .hdr-title{font-family:'Poppins',sans-serif;font-size:2rem;font-weight:800;letter-spacing:.5px;margin-bottom:.35rem}
      .hdr-subtitle{font-family:'Playfair Display',serif;font-size:1.3rem;font-weight:600;font-style:italic;letter-spacing:.4px;opacity:.95}
      main{flex:1;display:flex;justify-content:center;align-items:center;padding:2rem}
      .card{background:#fff;padding:1.6rem 2rem;border-radius:16px;
            box-shadow:0 10px 22px rgba(0,0,0,.12);text-align:center;max-width:520px}
      .card h1{margin-top:0;color:#003638;font-size:1.4rem;font-weight:600}
      .btn-home{
        margin-top:1.4rem;padding:.7rem 1.4rem;border:none;border-radius:10px;
        background:#ee7f2f;color:#fff;font-weight:700;cursor:pointer;
        font-size:1rem;box-shadow:0 4px 10px rgba(0,0,0,.1);
      }
      .btn-home:hover{box-shadow:0 6px 14px rgba(0,0,0,.14)}
      footer.copyright{
        width:100%;margin-top:auto;padding:.9rem 0;
        background:linear-gradient(90deg,#003638 0%,#005158 100%);
        color:#fff;font-size:.9rem;font-weight:600;text-align:center;
        box-shadow:0 -4px 10px rgba(0,0,0,.05);
      }
    </style>
    </head><body>
      <header class="site-hdr">
        <div class="hdr-inner">
          <div class="hdr-title">UTRGV Department of Mechanical Engineering</div>
          <div class="hdr-subtitle">Center for Aerospace Research</div>
        </div>
      </header>
      <main>
        <div class="card">
          <h1>Thank you for completing the Capstone Exit Survey!</h1>
          <p>Your responses have been recorded.</p>
          <button class="btn-home" onclick="location.href='/login'">🏠 Home</button>
        </div>
      </main>
      <footer class="copyright">©2025 Center for Aerospace Research</footer>
    </body></html>
    """

@parent.route("/survey/download")
@login_required
def survey_download():
    # only admins should see this
    if session.get("user") != "MECE Admin":
        return redirect(url_for("abet"))

    # optional: CSV export ?format=csv
    as_csv = (request.args.get("format", "").lower() == "csv")

    import pandas as pd
    with get_survey_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT id, submitted_at, student_name, year_graduated, job_plan, answers_json
              FROM graduate_survey_responses
             ORDER BY submitted_at DESC
            """,
            conn
        )

    if as_csv:
        csv = df.to_csv(index=False)
        return (csv, 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=graduate_survey.csv",
        })

    # reuse your existing DATA_HTML table template
    return render_template_string(
        DATA_HTML,
        columns=df.columns,
        rows=df.to_dict(orient="records")
    )

@parent.route("/survey/analyze")
@login_required
def survey_analyze():
    # Only MECE Admin should access
    if session.get("user") != "MECE Admin":
        return redirect(url_for("abet"))

    import pandas as pd, numpy as np, json
    from io import BytesIO
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ---- 1) Load + denormalize answers --------------------------------
    with get_survey_conn() as conn:
        df = pd.read_sql_query(
            "SELECT submitted_at, student_name, year_graduated, job_plan, answers_json "
            "FROM graduate_survey_responses ORDER BY submitted_at DESC",
            conn
        )

    if df.empty:
        return "<script>alert('No Graduate Survey submissions yet.');window.close();</script>"

    # Parse JSON answers -> flat columns q6_semesters, q7_gpa, q8_orgs_any, q10_orgs (list), …
    def parse_row(s):
        try:
            d = json.loads(s) if isinstance(s, str) else {}
        except Exception:
            d = {}
        return d

    answers = df["answers_json"].apply(parse_row)
    # Build a column-friendly dataframe (CTE: handle lists by keeping as lists for custom counts)
    # Extract the keys we chart
    keys_simple = [
        "q6_semesters","q7_gpa","q8_orgs_any","q9_orgs_count","q12_conf_any",
        "q14_intern_any","q17_coop_any","q20_research_any","q24_need_work","q32_plans"
    ]
    # Multi-select (list) keys
    keys_multi = ["q10_orgs"]

    # Create series for simple keys
    for k in keys_simple:
        df[k] = [a.get(k) for a in answers]

    # Ensure multi keys are lists
    for k in keys_multi:
        df[k] = [a.get(k) if isinstance(a.get(k), list) else
                 ([a.get(k)] if a.get(k) not in (None, "", []) else []) for a in answers]

    # ---- 2) Tall dashboard figure (stunning but readable) --------------
    plt.close("all")
    fig = plt.figure(figsize=(12, 22), dpi=130)
    gs = fig.add_gridspec(8, 2, height_ratios=[1.2,1,1,1.2,1,1,1,1.4], hspace=0.9, wspace=0.35)

    # Palette helpers
    bars = plt.cm.Blues
    piec = plt.cm.Set3

    # 2.1 Time to graduation (barh) – q6_semesters
    ax = fig.add_subplot(gs[0, :])
    order_sem = ["Less than 4","4","5","6","7","8","9","10","11","12","More than 12"]
    # The stored label is like "8", "9", "More than 12" with " semesters" in UI; normalise:
    def norm_sem(v):
        if v is None: return None
        txt = str(v).replace(" semesters","").replace(" semester","").strip()
        return "Less than 4" if "Less than" in txt else ("More than 12" if "More than" in txt else txt)
    s = df["q6_semesters"].map(norm_sem)
    counts = s.value_counts().reindex(order_sem, fill_value=0)
    y = np.arange(len(counts))
    ax.barh(y, counts.values, color=bars(np.linspace(0.55, 0.9, len(counts))))
    for yi, val in zip(y, counts.values):
        ax.text(val + 0.5, yi, f"{val}", va="center", fontsize=10)
    ax.set_yticks(y); ax.set_yticklabels([f"{lbl} semesters" if lbl.isdigit() else lbl for lbl in counts.index])
    ax.set_xlabel("Number of Graduating Seniors")
    ax.set_title("How many semesters (not including summers) did it take you to graduate?")

    # 2.2 GPA – pie(s) or simple bar by band – q7_gpa
    ax = fig.add_subplot(gs[1, 0])
    order_gpa = ["3.5 or higher","3.0–3.5","2.7–3.0","2.5–2.7","Less than 2.5"]
    gpa = df["q7_gpa"].value_counts().reindex(order_gpa, fill_value=0)
    ax.pie(gpa.values, labels=gpa.index, autopct="%d", startangle=90, pctdistance=0.85, textprops={"fontsize":9})
    ax.set_title("UTRGV GPA bands")

    # 2.3 Org involvement – q8_orgs_any
    ax = fig.add_subplot(gs[1, 1])
    inv = df["q8_orgs_any"].value_counts().reindex(["Yes","No"], fill_value=0)
    ax.pie(inv.values, labels=inv.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("Were you involved in any CECS student organizations?")

    # 2.4 Org count – q9_orgs_count (pie)
    ax = fig.add_subplot(gs[2, 0])
    order_orgcnt = ["0","1","2","3","4","More than 4"]
    oc = df["q9_orgs_count"].value_counts().reindex(order_orgcnt, fill_value=0)
    ax.pie(oc.values, labels=oc.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("How many CECS orgs have you been involved in?")

    # 2.5 Org names – q10_orgs (stacked counts bar)
    ax = fig.add_subplot(gs[2, 1])
    all_orgs = sorted({x for row in df["q10_orgs"] for x in (row or [])})
    org_counts = pd.Series({org: sum(org in (row or []) for row in df["q10_orgs"]) for org in all_orgs})
    org_counts = org_counts.sort_values(ascending=True)
    ax.barh(np.arange(len(org_counts)), org_counts.values, color=plt.cm.tab20(np.linspace(0,1,len(org_counts))))
    ax.set_yticks(np.arange(len(org_counts))); ax.set_yticklabels(org_counts.index, fontsize=8)
    ax.set_xlabel("Graduating Seniors"); ax.set_title("Participation by organization")

    # 2.6 Conferences – q12_conf_any
    ax = fig.add_subplot(gs[3, 0])
    conf = df["q12_conf_any"].value_counts().reindex(["Yes","No"], fill_value=0)
    ax.pie(conf.values, labels=conf.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("Attended conferences in search of internships/co-ops?")

    # 2.7 Internships – q14_intern_any
    ax = fig.add_subplot(gs[3, 1])
    intern = df["q14_intern_any"].value_counts().reindex(["Yes","No"], fill_value=0)
    ax.pie(intern.values, labels=intern.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("Attended summer industry internships?")

    # 2.8 Co-ops – q17_coop_any
    ax = fig.add_subplot(gs[4, 0])
    coop = df["q17_coop_any"].value_counts().reindex(["Yes","No"], fill_value=0)
    ax.pie(coop.values, labels=coop.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("Attended fall/spring industry co-ops?")

    # 2.9 Research – q20_research_any (Yes/Yes outside/No)
    ax = fig.add_subplot(gs[4, 1])
    order_res = ["Yes (MECE)","Yes (outside MECE)","No"]
    research = df["q20_research_any"].value_counts().reindex(order_res, fill_value=0)
    ax.pie(research.values, labels=research.index, autopct="%d", startangle=90, textprops={"fontsize":9})
    ax.set_title("Undergraduate research participation")

    # 2.10 Worked while studying – q24_need_work
    ax = fig.add_subplot(gs[5, 0])
    work = df["q24_need_work"].value_counts().reindex(["Yes","No"], fill_value=0)
    ax.pie(work.values, labels=work.index, autopct="%d", startangle=90, textprops={"fontsize":10})
    ax.set_title("During your time at UTRGV, did you work?")

    # 2.11 Plans after graduation – q32_plans
    ax = fig.add_subplot(gs[5:, :])
    # Keep a friendly order similar to your sample
    order_plans = [
        "Already have engineer job offer",
        "Plan to work as engineer (no offers yet)",
        "Have job offer not as an engineer",
        "Do not plan to work as an engineer",
        "Accepted into graduate program",
        "Plan to apply to graduate school",
        "Other",
    ]
    plans = df["q32_plans"].value_counts()
    # Bring any unseen label to end
    for k in order_plans:
        if k not in plans.index:
            plans.loc[k] = 0
    plans = plans.reindex(order_plans, fill_value=0)

    # Big pie with counts as labels
    wedges, texts, autotexts = ax.pie(plans.values, startangle=90, autopct="%d",
                                      textprops={"fontsize":11})
    ax.legend(wedges, plans.index, loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=10)
    ax.set_title("What are your plans after graduation?")

    # overall title
    fig.suptitle("Capstone Exit Survey – Summary Dashboard", fontsize=16, weight="bold", y=0.995)

    # ---- 3) Embed as an HTML <img> ------------------------------------
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    img64 = base64.b64encode(buf.getvalue()).decode()

    return f"""
    <!doctype html><html><head><title>Capstone Exit Survey – Analysis</title></head>
    <body style="margin:0;display:flex;justify-content:center;align-items:flex-start;background:#f7f9fc">
      <img src="data:image/png;base64,{img64}"
           style="max-width:95%;height:auto;margin:18px;box-shadow:0 4px 18px rgba(0,0,0,.15);border-radius:10px">
    </body></html>
    """

if __name__ == "__main__":
    run_simple("0.0.0.0", 5000, application, use_reloader=True, use_debugger=True)

# expose the correct app for Render deployment
app = application