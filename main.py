# main.py  – login + mounted ABET app
"""
Run:
    pip install flask werkzeug
    python main.py
Open http://127.0.0.1:5000/login
"""
# ─── top of each file (after imports) ───────────────────────────────
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

// ─── enable Analyze SLO btn when dropdown chosen ────────────────
document.getElementById('sloOnlySel').addEventListener('change',e=>{
  document.getElementById('analyzeSloBtn').disabled = !e.target.value;
});
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
    pis = sorted(df["pi"].unique())  # NEW ↓ dynamic PI list
    n_pi = len(pis)  # NEW ↓ use everywhere

    # ── NEW: normalise Bloom text and build a PI-Bloom combo label ─────────
    df["blooms_level"] = df["blooms_level"].astype(str).str.strip()

    # helper: "PI-1: Able to …"  →  "PI-1"
    def short_pi(txt: str) -> str:
        return txt.split(":")[0].strip()

    # composite label stored in the dataframe
    df["pi_bl"] = df["pi"].apply(short_pi) + " (" + df["blooms_level"] + ")"

    model = smf.mixedlm(
        "attain ~ semester_idx",  # fixed slope = improvement / term
        data=df,
        groups="sem_short"  # one random intercept per semester
    ).fit(method="lbfgs")

    print(model.summary())  # slope β₁ & its p-value

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
    lmm = smf.mixedlm(
        'attain ~ semester_idx',  # fixed slope
        data=df,
        groups='sem_short'  # random intercept per semester
    ).fit(method='lbfgs')
    u = pd.Series({k: v.values[0] for k, v in lmm.random_effects.items()}) \
        .sort_index()

    # ─── 4.  build g = tidy table for plotting  (NEW)  ──────────────────
    g = (df.groupby(['sem_short', 'semester_idx'])
         .agg(mean_attain=('attain', 'mean'))
         .reset_index())

    g = g.sort_values('semester_idx')  # ensure ascending x
   # pred = lmm.get_prediction(g, exog=dict(semester_idx=g.semester_idx))
   # g['fit'] = pred.predicted_mean
   # g[['low', 'high']] = pred.conf_int()

    g['fit'] = lmm.predict(exog=dict(semester_idx=g.semester_idx))

    # design matrix for the fixed effects (Intercept and semester_idx)
    X = pd.DataFrame({
        'Intercept': 1.0,
        'semester_idx': g.semester_idx
    })

    # covariance matrix of the two fixed-effect estimates
    V = lmm.cov_params().loc[['Intercept', 'semester_idx'],
    ['Intercept', 'semester_idx']]

    # standard error for each fitted point
    se = np.sqrt((X @ V * X).sum(axis=1))

    from scipy.stats import t
    crit = t.ppf(0.975, df=lmm.df_resid)  # 95 % two-sided

    g['low'] = g['fit'] - crit * se
    g['high'] = g['fit'] + crit * se

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

    for j, sem in enumerate(semesters):
        vals = pivot2[sem].values
        pos = x2 - 0.4 + (j + .5) * bar_w2

        mask = ~np.isnan(vals)
        colours = [greens[pi_index[tag]] if v >= 70 else reds[pi_index[tag]]
                   for tag, v in zip(pi_tag_for_combo, vals) if not np.isnan(v)]

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

    divnorm = colors.TwoSlopeNorm(vcenter=0, vmin=u.min(), vmax=u.max())
    cmap = plt.cm.RdYlGn

    # inside the loop that scatters the dots on ax4  (replace the old line)
    colours = [cmap(divnorm(u[s]))
               for s in g.semester_idx.map(lambda i: sem_order[i])]

    ax4.scatter(g.semester_idx, g.mean_attain,
                s=80, c=colours, edgecolor="#333", label='Observed')
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

if __name__ == "__main__":
    run_simple("0.0.0.0", 5000, application, use_reloader=True, use_debugger=True)

# expose the correct app for Render deployment
app = application