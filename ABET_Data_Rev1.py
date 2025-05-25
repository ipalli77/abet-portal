# app.py — ABET Data‑Entry Flask App
"""
How to run
==========
1. pip install flask
2. python app.py
3. Open http://127.0.0.1:5000/
"""

from flask import Flask, render_template_string, request, jsonify
import sqlite3

from flask import session, redirect

DB_NAME = "abet_data.db"

# --------------------------------------------------------------------------- #
# Database helper
# --------------------------------------------------------------------------- #
def init_db() -> None:
    """Create the SQLite tables on first run."""
    with sqlite3.connect(DB_NAME) as conn:
        # -------- main production table --------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS abet_entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                course          TEXT,
                course_name     TEXT,
                slo             TEXT,
                pi              TEXT,
                assessment_tool TEXT,
                explanation     TEXT,
                semester        TEXT,
                blooms_level    TEXT,
                expert          REAL,
                practitioner    REAL,
                apprentice      REAL,
                novice          REAL,
                observations    TEXT
            );
        """)

        # -------- per-user draft blob --------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_drafts (
                user  TEXT PRIMARY KEY,
                blob  TEXT
            );
        """)

# call it once at start-up
init_db()

# --------------------------------------------------------------------------- #
# Flask application
# --------------------------------------------------------------------------- #
app = Flask(__name__)

# --------------------------------------------------------------------------- #
# HTML template
# --------------------------------------------------------------------------- #
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ABET Data Collection</title>

  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">

  <style>
    :root{
      --brand:#003638; --accent:#ee7f2f; --success:#28a745;
      --hdr:#c7c7c7;  --row:#edf4ff;  --rub:#fdf6ea; --err:#ffe6e6;
    }
    *{box-sizing:border-box;font-family:'Poppins',sans-serif}
    body{
      margin:0;background:#f7f9fc;color:#252525;
      display:flex;flex-direction:column;align-items:center;padding:2rem 1rem;
    }
    header{text-align:center;margin-bottom:1.5rem}
    .title{font-size:2rem;font-weight:600;color:var(--brand)}
    .subtitle{font-size:1.25rem;color:var(--accent)}

    /* table */
    table{
      width:100%;max-width:1800px;border-collapse:collapse;
      background:#fff;border-radius:12px;box-shadow:0 4px 10px rgba(0,0,0,.06);
    }
    thead th{
      padding:.7rem .5rem;background:var(--hdr);border-right:1px solid #e0e0e0;
      font-weight:600;text-align:center;
    }
    tbody td{
      padding:.45rem .35rem;border-top:1px solid #e5e5e5;border-right:1px solid #e5e5e5;
      text-align:center;vertical-align:top;
    }
    tbody td:last-child, thead th:last-child{border-right:none}
    .input-row td{background:var(--row)}
    .rubric-cell{background:var(--rub)}

    select, input, textarea{
      width:100%;padding:.35rem .5rem;border:1px solid #ccc;border-radius:6px;font-size:.9rem
    }
    textarea{resize:vertical;min-height:60px}
    .num{min-width:60px}
    .err{border-color:red !important;background:var(--err)}

    th.slo, td.slo  {width:220px}
    th.num, td.num  {width:70px}
    th.obs, td.obs  {width:380px}
    
.btn-bar{
  display:flex;
  gap:1.5rem;        /* ← increase or decrease as you like (e.g. 24 px) */
  margin-top:1.2rem; /* keeps the bar away from the table */
}

    .btn{
      margin-top:1rem;padding:.6rem 1.3rem;font-size:.95rem;
      border:none;border-radius:8px;color:#fff;cursor:pointer
    }
    .add   {background:var(--accent)}
    .submit{background:var(--success)}
    
    .cname-cell,
  .slo-display,
  .pi-cell{
    text-align:left !important;
    padding-left:.5rem;          /* optional – nudges text away from border */
  }
  
/* ---- delete button + column -------------------------------- */
.del-hdr, .del-cell{ width:65px; text-align:center; }

.del{
  padding:.4rem .7rem;
  background:#dc3545;   /* red-ish */
  color:#fff;
  border:none;
  border-radius:6px;
  font-size:.85rem;
  cursor:pointer;
  transition:transform .05s, box-shadow .15s;
}
.del:hover {box-shadow:0 3px 8px rgba(0,0,0,.14)}
.del:active{transform:translateY(1px)}
  
.bloom-input,
.bloom-cell{
 // background:#e8fbe8;   /* subtle light green */
}
.bloom-cell{ text-align:center; padding-left:.5rem }

footer.copyright{
  width:100%;
  margin-top:2.5rem;
  padding:0.9rem 0;
  background:linear-gradient(90deg,#003638 0%,#005158 100%);
  color:#ffffff;
  font-size:.9rem;
  font-weight:600;
  letter-spacing:.03rem;
  text-align:center;
  box-shadow:0 -4px 10px rgba(0,0,0,.05);
  border-bottom-left-radius:12px;
  border-bottom-right-radius:12px;
}

.site‑hdr{
  width:100%;
  background:linear-gradient(90deg,#003638 0%,#005158 50%,#00736f 100%);
  box-shadow:0 4px 12px rgba(0,0,0,.08);
  padding:2.2rem 1rem 2rem;             /* top / horiz / bottom */
  display:flex;justify-content:center;
  border-top-left-radius:12px;
  border-top-right-radius:12px;
}

.hdr‑inner{
  text-align:center;color:#ffffff;
  text-shadow:0 1px 3px rgba(0,0,0,.35);
}

.hdr‑title{
  font-size:1.9rem;font-weight:700;letter-spacing:.02rem;
  margin-bottom:.35rem;
}

.hdr‑subtitle{
  font-size:1.15rem;font-weight:500;letter-spacing:.03rem;
  opacity:.93;
}

.exp-hdr,
.exp-cell{
  width:480px;         /* tweak as desired */
}

.obs-note{
  font-size:.85rem;     /* adjust up or down as you like */
  font-weight:400;      /* normal weight (not bold)      */
}

.del:disabled{
  opacity:.45;
  cursor:not-allowed;
}

/* ----- brand-new Home button ---------------------------------- */
.btn.home{
  background:#6c757d;       /* muted gray-blue (adjust if you like) */
}
.btn.home:hover{box-shadow:0 8px 18px rgba(0,0,0,.16)}
.btn.home:active{transform:translateY(3px)}

/* ----- subtler amber Save button ------------------------------ */
.btn.save{
  background:#f0ad4e;       /* appealing amber */
}

.tr-submitted{ background:#e8fbe8; }  /* soft green  */
.tr-draft    { background:#fff8e6; }  /* soft amber */
    
</style>
</head>

<body>
<header class="site‑hdr">
  <div class="hdr‑inner">
    <div class="hdr‑title">UTRGV Department of Mechanical Engineering</div>
    <div class="hdr‑subtitle">ABET Data Collection Portal</div>
  </div>
</header>

<main style="width:100%;display:flex;flex-direction:column;align-items:center">
<table id="tbl">
  <thead>
    <tr>
      <th rowspan="2">Course Number</th>
      <th rowspan="2">Course Name</th>
      <th rowspan="2" class="slo">Student Learning Outcome (SLO)</th>
      <th rowspan="2" id="pi‑hdr">Performance Indicator (PI)</th>
      <th rowspan="2">Assessment Tool Used</th>
      <th rowspan="2" class="bloom-hdr">Bloom's Level</th>
      <th rowspan="2" class="exp-hdr">
  Explanation of Why Tool Appropriately Assesses SLO and PI at the Selected Bloom's Level
</th>
      <th rowspan="2">Assessment Semester</th>
      <th colspan="4">Enter EPAN Data (in %)</th>
      <th rowspan="2" class="obs">
  Observations on Student Performance
  <span class="obs-note">
    (struggles, aha moments, etc. and plans for improvement, closing the loop)
  </span>
</th>
<th rowspan="2" class="del-hdr">Delete</th>
    </tr>
    <tr>
      <th class="num">E</th><th class="num">P</th><th class="num">A</th><th class="num">N</th>
    </tr>
  </thead>

  <tbody id="body">

    <!-- TEMPLATE: selector row -->
    <tr class="input-row">
      <td>
        <select class="course" onchange="syncCourse(this)">
  <option value="" disabled selected>Select course</option>
  <option>MECE 1101</option>
  <option>MECE 1221</option>
  <option>MECE 2140</option>
  <option>MECE 2302</option>
  <option>MECE 2340</option>
  <option>MECE 3170</option>
  <option>MECE 3315</option>
  <option>MECE 3320</option>
  <option>MECE 3336</option>
  <option>MECE 3360</option>
  <option>MECE 3380</option>
  <option>MECE 3450</option>
  <option>MECE 4350</option>
  <option>MECE 4361</option>
  <option>MECE 4362</option>
  <option>PHIL 2393</option>
</select>
      </td>
      <td></td>
      <td class="slo">
        <select class="sloSel" onchange="syncSLO(this)">
          <option value="" disabled selected>Select</option>
          <option value="SLO1">SLO1</option><option value="SLO2">SLO2</option><option value="SLO3">SLO3</option>
          <option value="SLO4">SLO4</option><option value="SLO5">SLO5</option><option value="SLO6">SLO6</option><option value="SLO7">SLO7</option>
        </select>
      </td>
      <td class="pi-input"></td>
      <td></td>
      <td class="bloom-input">
   <select class="bloomSel" onchange="syncBloom(this)">
     <option value="" disabled selected>Select level</option>
     <option>Remember</option>
     <option>Understand</option>
     <option>Apply</option>
     <option>Analyze</option>
     <option>Evaluate</option>
     <option>Create</option>
   </select>
 </td><td></td>
      
      <td class="sem-input">
   <select class="semesterSel" onchange="syncSemester(this)">
     <option value="" disabled selected>Select semester</option>
     <option>Fall 2020</option>
     <option>Spring 2021</option>
     <option>Fall 2021</option>
     <option>Spring 2022</option>
     <option>Fall 2022</option>
     <option>Spring 2023</option>
     <option>Fall 2023</option>
     <option>Spring 2024</option>
     <option>Fall 2024</option>
     <option>Spring 2025</option>
     <option>Fall 2025</option>
     <option>Spring 2026</option>
     <option>Fall 2026</option>
   </select>
</td>
  <td class="rubric-cell num"></td><td class="rubric-cell num"></td>
  <td class="rubric-cell num"></td><td class="rubric-cell num"></td>
  <td class="obs"></td>
  <td class="del-cell">
        <button class="del" onclick="deletePair(this)">🗑</button>
      </td>
    </tr>

    <!-- TEMPLATE: data row -->
    <tr class="data-row">
      <td class="course-display"></td>
      <td class="cname-cell"></td>
      <td class="slo-display text-left slo"></td>
      <td class="pi-cell"></td>
      <td><textarea class="tool"></textarea></td>
      <td class="bloom-cell"></td>
      <td class="exp-cell">
  <textarea class="explan"></textarea>
</td>
      <td class="sem-display"></td>
      <td class="rubric-cell num"><input type="number" class="num inp"></td>
      <td class="rubric-cell num"><input type="number" class="num inp"></td>
      <td class="rubric-cell num"><input type="number" class="num inp"></td>
      <td class="rubric-cell num"><input type="number" class="num inp"></td>
      <td class="obs"><textarea class="obsTxt"></textarea></td>
      <td class="del-cell"></td>
    </tr>

  </tbody>
</table>

<div class="btn-bar">
<button class="btn home"   onclick="goHome()">🏠 Home</button>   <!-- NEW -->
  <button class="btn add"    onclick="addRow()">➕ Add row</button>
  <button class="btn save"   onclick="saveDraft()">💾 Save Draft</button>
  <button class="btn submit" onclick="submitForm()">📤 Submit</button>
</div>
</main>

<!-- put this immediately *after* </main> and before </body> -->
<footer class="copyright">
  ©2025 Center for Aerospace Research
</footer>

<script>
/* -------- SLO descriptions -------- */

/* ───────────────── faculty → allowed courses ────────────────── */
const FAC_COURSES = {
  "Yingchen Yang"   : ["MECE 1101"],
  "Lawrence Cano"   : ["MECE 1221"],
  "Misael Martinez" : ["MECE 2140"],
  "Eleazar Marquez" : ["MECE 2302"],
  "Robert Jones"    : ["MECE 2340"],
  "Jose Sanchez"    : ["MECE 3170", "MECE 3336"],
  "Nadim Zgheib"    : ["MECE 3315"],
  "Isaac Choutapalli" : ["MECE 3320"],
  "Constantine T"   : ["MECE 3360"],
  "Robert Freeman"  : ["MECE 3380"],
  "Caruntu D"       : ["MECE 3450"],
  "Javier Ortega"   : ["MECE 4350"],
  "Noe Vargas"      : ["MECE 4361"],
  "Kamal Sarkar"    : ["MECE 4362"],
  "Mataz Alcoutlabi": ["PHIL 2393"]
};

/* grab ?user=… from the URL and build a normalized ALLOWED set */
const USER_RAW = "{{ session['user'] | escape }}";

/* helper: normalise strings (NBSP → space, collapse spaces, lowercase) */
function norm(str){
  return str.replace(/\u00A0/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .toLowerCase();
}

/* find the FAC_COURSES entry whose key matches the logged‑in user */
let allowedCourses = [];
const userKeyNorm  = norm(USER_RAW);

for (const [fac, courses] of Object.entries(FAC_COURSES)){
  if (norm(fac) === userKeyNorm){
    allowedCourses = courses;      // match found
    break;
  }
}

/* ===== NEW fallback: if no match, treat user like an admin ===== */
if (allowedCourses.length === 0){
  console.warn("No course list found for user:", USER_RAW,
               "— showing all courses.");
}

/* build a Set of normalised course codes */
const ALLOWED = new Set( allowedCourses.map(norm) );

function filterCourses(select){
  /* admins OR unknown users → keep full list */
  if (norm(USER_RAW) === norm("MECE Admin") || allowedCourses.length === 0){
    return;
  }

  const allowed = new Set(allowedCourses.map(norm));

  for (let i = select.options.length - 1; i >= 0; i--){
    const opt = select.options[i];
    if (opt.value && !allowed.has( norm(opt.value) )){
      select.remove(i);
    }
  }
}

/* run once after page load */
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('select.course').forEach(filterCourses);
});

const SLO_DESC = {
  SLO1:"An ability to identify, formulate, and solve complex engineering problems by applying principles of engineering, science, and mathematics.",
  SLO2:"An ability to apply engineering design to produce solutions that meet specified needs with consideration of public health, safety, and welfare, as well as global, cultural, social, environmental, and economic factors.",
  SLO3:"An ability to communicate effectively with a range of audiences.",
  SLO4:"An ability to recognize ethical and professional responsibilities in engineering situations and make informed judgments, which must consider the impact of engineering solutions in global, economic, environmental, and societal contexts.",
  SLO5:"An ability to function effectively on a team whose members together provide leadership, create a collaborative and inclusive environment, establish goals, plan tasks, and meet objectives.",
  SLO6:"An ability to develop and conduct appropriate experimentation, analyze and interpret data, and use engineering judgement to draw conclusions.",
  SLO7:"An ability to acquire and apply new knowledge as needed, using appropriate learning strategies."
};

/* -------- helper functions -------- */
function clearErr(el){ el.classList.remove('err'); }

function syncCourse(sel){
  const inputRow = sel.closest('tr');           // selector row
  const dataRow  = inputRow.nextElementSibling; // data row

  // put course number under the "Course" data cell
  dataRow.querySelector('.course-display').textContent = sel.value;

  // write course name in the new cname-cell
  //dataRow.querySelector('.cname-cell').textContent =
     // COURSE_MAP[sel.value] || "";
      
dataRow.querySelector('.cname-cell').textContent = COURSE_MAP[sel.value]

  clearErr(sel);
}

function syncSemester(sel){
  const dataRow = sel.closest('tr').nextElementSibling;
  dataRow.querySelector('.sem-display').textContent = sel.value;
  clearErr(sel);
}

function syncBloom(sel){
  const dataRow = sel.closest('tr').nextElementSibling;
  dataRow.querySelector('.bloom-cell').textContent = sel.value;
  clearErr(sel);
}

/* live numeric filter & error clear */
document.addEventListener('input', e=>{
  if(e.target.classList.contains('inp')){
    e.target.value = e.target.value.replace(/[^0-9.]/g,'');
  }
  clearErr(e.target);
});
document.addEventListener('change', e=>clearErr(e.target));

function deletePair(btn){
  if(!confirm('Remove this row?')) return;

  const ir = btn.closest('tr');       // selector row
  const dr = ir.nextElementSibling;   // data row

  const pairs = document.querySelectorAll('.input-row').length;
  if(pairs <= 1){                      // protect the last pair
    alert('At least one row is required.');
    return;
  }

  dr.remove();
  ir.remove();
  updateDeleteButtons();              // NEW
}

/* ────────────────────────────────────────────────────────────────────────────────
 * 1)  NEW  enable/disable delete buttons when only one pair remains
 * ────────────────────────────────────────────────────────────────────────────── */
function updateDeleteButtons(){
  const lock = document.querySelectorAll('.input-row').length <= 1;
  document.querySelectorAll('.del').forEach(btn => btn.disabled = lock);
}

/* call once as soon as the DOM is ready */
document.addEventListener('DOMContentLoaded', ()=>{
  document.querySelectorAll('select.course').forEach(filterCourses);
  updateDeleteButtons();                    // ← keep the delete rule

  /* ──────────────────────────────────────────────────────────────────────────
   * 2)  NEW  fetch BOTH submitted rows and drafts from /load_records
   * ──────────────────────────────────────────────────────────────────────── */
  fetch('load_records')                     // <-- endpoint in Flask
    .then(r=>r.ok ? r.json() : Promise.reject(r.status))
    .then(data=>renderRecords(data.rows || []))
    .catch(()=>console.warn('No records found for this user.'));
});

/* ────────────────────────────────────────────────────────────────────────────────
 * 3)  renderRecords    – creates exactly N row-pairs and colours them
 * ────────────────────────────────────────────────────────────────────────────── */
function ensurePairs(n){
  const body = document.getElementById('body');
  while(body.querySelectorAll('.input-row').length < n) addRow();
  while(body.querySelectorAll('.input-row').length > n){
    const ir = body.querySelector('.input-row:last-of-type');
    ir.nextElementSibling.remove();
    ir.remove();
  }
}

function colourPair(ir, dr, status){
  const clr = status === 'submitted' ? '#e8fbe8' :    /* green  */
              status === 'draft'     ? '#fff8e6' :    /* amber  */
                                        'transparent';
  ir.style.backgroundColor = dr.style.backgroundColor = clr;
}

function renderRecords(records){
  if(!records.length) return;

  ensurePairs(records.length);                     // add/remove row pairs
  const inputRows = document.querySelectorAll('.input-row');

  records.forEach((rec, i)=>{
    const ir = inputRows[i];
    const dr = ir.nextElementSibling;

    /* selector row ---------------------------------------------------- */
    ir.querySelector('.course').value      = rec.course;      syncCourse  (ir.querySelector('.course'));
    ir.querySelector('.sloSel').value      = rec.slo;         syncSLO     (ir.querySelector('.sloSel'));
    ir.querySelector('.semesterSel').value = rec.semester;    syncSemester(ir.querySelector('.semesterSel'));
    ir.querySelector('.bloomSel').value    = rec.blooms_level;syncBloom   (ir.querySelector('.bloomSel'));

    const piSel = ir.querySelector('.piSel');
    if(piSel){ piSel.value = rec.pi; piChosen(piSel); }

    /* data row -------------------------------------------------------- */
    dr.querySelector('.tool').value    = rec.assessment_tool;
    dr.querySelector('.explan').value  = rec.explanation;
    dr.querySelector('.obsTxt').value  = rec.observations;

    const nums = dr.querySelectorAll('.inp');
    nums[0].value = rec.expert;
    nums[1].value = rec.practitioner;
    nums[2].value = rec.apprentice;
    nums[3].value = rec.novice;

    /* colouring + metadata ------------------------------------------- */
    colourPair(ir, dr, rec.status);
    ir.dataset.status = dr.dataset.status = rec.status;   //  ← NECESSARY
    ir.dataset.rowId  = dr.dataset.rowId  = rec.id ?? "";
  });

  updateDeleteButtons();
}


/* add a new selector + data row pair */
function addRow(){
  const body = document.getElementById('body');
  const ir   = body.querySelector('.input-row').cloneNode(true);
  const dr   = body.querySelector('.data-row').cloneNode(true);

  ir.querySelectorAll('select').forEach(s=>s.selectedIndex=0);
  dr.querySelectorAll('.sem-display').forEach(el=>el.textContent = "");
  dr.querySelector('.bloom-cell').textContent = "";

  dr.querySelectorAll('textarea, input').forEach(el=>el.value='');
  dr.querySelectorAll('.course-display, .slo-display, .pi-cell').forEach(el=>el.textContent='');
  
  dr.querySelector(".pi-cell").innerHTML = "";
  
  dr.querySelector('.sem-display').textContent = "";
  dr.querySelector('.cname-cell').textContent = "";

  body.append(ir);
  body.append(dr);
  
  filterCourses(ir.querySelector('.course'));
  
  updateDeleteButtons();
  colourPair(ir, dr, 'new');   // remove any residual tint
  ir.dataset.status = dr.dataset.status = 'draft';
  
}

/* validation helpers */
function mark(el){ el.classList.add('err'); }

function validate(){
  let ok = true;

  document.querySelectorAll('.data-row').forEach(dr=>{
    const ir   = dr.previousElementSibling;
    const nums = [...dr.querySelectorAll('.inp')];

    const required = [
      ir.querySelector('.course'),
      ir.querySelector('.sloSel'),
      ir.querySelector('.semesterSel'),
      ir.querySelector('.piSel') || {value:""},
      dr.querySelector('.tool'),
      ir.querySelector('.bloomSel'),
      dr.querySelector('.explan'),
      dr.querySelector('.obsTxt'),
      ...nums
    ];

    required.forEach(el=>{
      if(!el.value.trim()){ mark(el); ok = false; }
    });

    const sum = nums.reduce((a,b)=>a+(parseFloat(b.value)||0),0);
    if(Math.abs(sum-100) > 0.01){
      nums.forEach(mark); ok = false;
    }
  });

  return ok;
}

/* gather rows into JSON */
function collect(){
  const rows = [];

  document.querySelectorAll('.data-row').forEach(dr=>{
    const ir = dr.previousElementSibling;     // matching input‑row
    const n  = [...dr.querySelectorAll('.inp')];

    rows.push({
  id              : ir.dataset.rowId,          // ◀ NEW
  course          : ir.querySelector('.course').value,
  course_name     : dr.querySelector('.cname-cell').textContent,
  blooms_level    : dr.querySelector('.bloom-cell').textContent,
  slo             : ir.querySelector('.sloSel').value,
  pi              : dr.querySelector('.pi-cell').textContent.trim(),
  assessment_tool : dr.querySelector('.tool').value,
  explanation     : dr.querySelector('.explan').value,
  semester        : ir.querySelector('.semesterSel').value,
  expert          : n[0].value,
  practitioner    : n[1].value,
  apprentice      : n[2].value,
  novice          : n[3].value,
  observations    : dr.querySelector('.obsTxt').value
});

  });

  return rows;
}

/* =====================================================
 *  SERVER-SIDE DRAFT  (one JSON blob per faculty member)
 * ===================================================== */

/* Convert whatever is currently on screen into JSON
   and ship it to /save_draft.  No validation needed. */
function saveDraft(){
  const all    = collect();                // rows in screen order
  const drafts = [];                       // rows we’ll actually send
  let i = 0;
  document.querySelectorAll('.data-row').forEach(dr=>{
    const ir = dr.previousElementSibling;
    if(ir.dataset.status !== 'submitted'){ // skip rows already in DB
      drafts.push(all[i]);
    }
    i++;
  });

  fetch('save_draft',{
    method :'POST',
    headers:{'Content-Type':'application/json'},
    body   : JSON.stringify({rows: drafts})
  })
  .then(r=>r.json())
  .then(js=>alert(`Draft saved (${js.saved} row${js.saved!==1?'s':''}).`))
  .catch(()=>alert('Unable to save draft right now.'));
}


/* ========== “Home” button handler ============================== */
function goHome(){
  const msg = "Save your draft before returning to the Home page?";
  if(confirm(msg)){
    saveDraft();                    // uses existing function
  }
  /* parent app’s /logout route clears the session + redirects → /login */
  window.location.href = "/logout";
}

/* ================ colour helpers =================== */
function colourPair(ir, dr, status){
  const clr = status === 'submitted' ? '#e8fbe8'   // subtle green
            : status === 'draft'     ? '#fff8e6'   // subtle amber
            : 'transparent';
  [ir, dr].forEach(tr => tr.style.backgroundColor = clr);
}

/* ================ build or reuse row pairs ========= */
function ensurePairs(n){
  const body = document.getElementById('body');
  while(body.querySelectorAll('.input-row').length < n) addRow();
  while(body.querySelectorAll('.input-row').length > n){
    const ir = body.querySelector('.input-row:last-of-type');
    ir.nextElementSibling.remove();
    ir.remove();
  }
}


/* ================ page-load fetch ================== */
document.addEventListener('DOMContentLoaded', ()=>{
  document.querySelectorAll('select.course').forEach(filterCourses);

  fetch('load_records')
    .then(r=>r.json())
    .then(js=>renderRecords(js.rows || []))
    .catch(()=>console.warn('Could not load previous records'));
});


/* submit handler */
function submitForm(){
  if(!validate()){ alert('Please complete all fields…'); return; }
  if(!confirm('Are you sure you want to submit?')) return;

  const allRows = collect();                         // every row, old or new
  const payload = [];
  document.querySelectorAll('.input-row').forEach((ir, idx)=>{
    const status = ir.dataset.status;                // 'submitted' | 'draft'
    const orig   = ir.dataset.orig ? JSON.parse(ir.dataset.orig) : null;
    const now    = allRows[idx];

    let changed = true;
    if(status === 'submitted' && orig){
      changed = JSON.stringify(orig) !== JSON.stringify(now);
    }
    if(changed) payload.push(now);                   // new or edited
  });

  if(!payload.length){ alert('No changes to save.'); return; }

  fetch('submit',{
    method :'POST',
    headers:{'Content-Type':'application/json'},
    body   : JSON.stringify({rows: payload})
  })
  .then(r=>r.json())
  .then(js=>{
    alert(`${js.saved} row(s) saved successfully.`);
    window.location.href = "/logout";
  })
  .catch(()=>alert('Submission error'));
}


/* --- SLO → PI list --- */
const PI_MAP = {
  SLO1: ["PI‑1: Able to Identify engineering problem",
         "PI‑2: Able to formulate a problem",
         "PI‑3: Able to solve Problem"],
  SLO2: ["PI‑1: Able to design a system, component, or process",
         "PI‑2: Able to design to meet desired needs",
         "PI‑3: Able to design within realistic constraints"],
  SLO3: ["PI‑1: Generate appropriate graphics",
         "PI‑2: Demonstrates adequate presentation skills",
         "PI‑3: Applies technical writing skills",
         "PI‑4: Contextualizes communication for intended audience"],
  SLO4: ["PI‑1: Recognize ethical and professional responsibilities in engineering situations",
         "PI‑2: Make informed ethical and professional judgments",
         "PI‑3: Consider the impact of engineering solutions in global, economic, environmental, and societal contexts"],
  SLO5: ["PI‑1: Establish goals",
         "PI‑2: Plan tasks & meet deadlines",
         "PI‑3: Fulfill duties of team roles",
         "PI‑4: Shares work equally",
         "PI‑5: Communicates effectively in a team setting",
         "PI‑6: Proficient in all aspects of the project"],
  SLO6: ["PI‑1: Develops and conducts appropriate experimentation",
         "PI‑2: Analyzes and interprets data",
         "PI‑3: Evaluates appropriate findings to draw conclusions"],
  SLO7: ["PI‑1: Recognize the ongoing need to acquire new knowledge",
         "PI‑2: Choose appropriate learning strategies to acquire new knowledge",
         "PI‑3: Apply new knowledge appropriately"]
};

/* --- build a PI <select> --- */
function makePiSelect(list){
  const sel = document.createElement("select");
  sel.className = "piSel";
  sel.required  = true;

  const blank = document.createElement("option");
  blank.disabled = true; blank.selected = true;
  blank.textContent = "Select PI";
  sel.append(blank);

  list.forEach(txt=>{
    const opt = document.createElement("option");
    opt.textContent = txt;
    sel.append(opt);
  });

  /* when PI picked, copy to data-row cell */
  sel.onchange = () => piChosen(sel);
  return sel;
}

/* --- when SLO changes, refresh PI cell --- */
function refreshPi(sel){
  const slo        = sel.value;
  const inputRow   = sel.closest("tr");
  const piInputTd  = inputRow.querySelector(".pi-input");
  piInputTd.innerHTML = "";                 // clear dropdown spot

  /* clear display text in data row */
  inputRow.nextElementSibling
           .querySelector(".pi-cell").textContent = "";

  if (PI_MAP[slo]) {
   piInputTd.appendChild( makePiSelect( PI_MAP[slo] ) );
  }
}

function piChosen(piSelect){
  const dataRow = piSelect.closest("tr").nextElementSibling;
  dataRow.querySelector(".pi-cell").textContent = piSelect.value;
  clearErr(piSelect);
}

/* --- hook into your existing syncSLO --- */
const oldSyncSLO = syncSLO;        // keep the existing behaviour
function syncSLO(sel){
  const dr = sel.closest('tr').nextElementSibling;
  dr.querySelector('.slo-display').textContent = sel.value ? sel.value+' - '+SLO_DESC[sel.value] : '';
  clearErr(sel);
  refreshPi(sel);                  // now also build PI dropdown
}

const COURSE_MAP = {
  "MECE 1101": "Intro to ME",
  "MECE 1221": "Engineering Graphics",
  "MECE 2140": "Engineering Materials Lab",
  "MECE 2302": "Dynamics",
  "MECE 2340": "Engineering Materials",
  "MECE 3170": "Thermal Fluids Laboratory",
  "MECE 3315": "Fluid Mechanics",
  "MECE 3320": "Measurements & Instrumentation",
  "MECE 3336": "Thermodynamics II",
  "MECE 3360": "Heat Transfer",
  "MECE 3380": "Kinematics & Dynamics of Machines",
  "MECE 3450": "Mechanical Engineering Analysis II",
  "MECE 4350": "Machine Elements",
  "MECE 4361": "Senior Design‑I",
  "MECE 4362": "Senior Design‑II",
  "PHIL 2393": "Philosophy"
};

</script>
</body>
</html>
"""  # <-- triple‑quoted string closed here

# --------------------------------------------------------------------------- #
# Flask routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

import json
from flask import session
# ---------- Save draft (overwrite any existing one) ---------- #
@app.route("/save_draft", methods=["POST"])
def save_draft():
    rows  = request.get_json(force=True).get("rows", [])
    blob  = json.dumps(rows)
    user  = session["user"]            # set by the parent login app
    with sqlite3.connect(DB_NAME) as c:
        c.execute("INSERT OR REPLACE INTO user_drafts(user,blob) VALUES(?,?)",
                  (user, blob))
    return jsonify({"saved": len(rows)})

# ---------- Load draft (if any) ---------- #
@app.route("/load_draft")
def load_draft():
    user = session["user"]
    with sqlite3.connect(DB_NAME) as c:
        cur = c.execute("SELECT blob FROM user_drafts WHERE user=?", (user,))
        row = cur.fetchone()
    return jsonify({"rows": json.loads(row[0]) if row else []})

@app.route("/load_records")
def load_records():
    """
    Return every submitted row that belongs to the logged-in user
    (or all rows for MECE Admin) plus the user’s current draft, if any.
    The front-end colours rows based on `status` = 'submitted' | 'draft'.
    """
    import json, sqlite3

    user = session.get("user", "MECE Admin")            # fallback → admin

    # ---------- which courses this faculty owns ---------- #
    FAC_COURSES = {
        "Yingchen Yang"   : ["MECE 1101"],
        "Lawrence Cano"   : ["MECE 1221"],
        "Misael Martinez" : ["MECE 2140"],
        "Eleazar Marquez" : ["MECE 2302"],
        "Robert Jones"    : ["MECE 2340"],
        "Jose Sanchez"    : ["MECE 3170", "MECE 3336"],
        "Nadim Zgheib"    : ["MECE 3315"],
        "Isaac Choutapalli": ["MECE 3320"],
        "Constantine T"   : ["MECE 3360"],
        "Robert Freeman"  : ["MECE 3380"],
        "Caruntu D"       : ["MECE 3450"],
        "Javier Ortega"   : ["MECE 4350"],
        "Noe Vargas"      : ["MECE 4361"],
        "Kamal Sarkar"    : ["MECE 4362"],
        "Mataz Alcoutlabi": ["PHIL 2393"]
    }
    allowed = FAC_COURSES.get(user, [])      # [] → treat as super-user

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        # ---------- submitted rows --------------------------------------- #
        if allowed:                               # faculty
            placeholders = ",".join("?" * len(allowed))
            sql = f"""
                SELECT *, 'submitted' AS status
                  FROM abet_entries
                 WHERE course IN ({placeholders})
            """
            cur.execute(sql, allowed)
        else:                                     # super-user
            cur.execute("""
                SELECT *, 'submitted' AS status
                  FROM abet_entries
              ORDER BY course ASC
            """)

        colnames   = [d[0] for d in cur.description]     # from the cursor
        submitted  = [dict(zip(colnames, row)) for row in cur.fetchall()]

        # ---------- draft blob ------------------------------------------- #
        cur.execute("SELECT blob FROM user_drafts WHERE user=?", (user,))
        row = cur.fetchone()
        drafts = json.loads(row[0]) if row else []
        for d in drafts:
            d["status"] = "draft"

    return jsonify({"rows": submitted + drafts})


@app.route("/submit", methods=["POST"])
def submit():
    """
    • INSERT brand-new rows   (no id in the payload)
    • UPDATE existing rows    (payload includes id)
    • Normalise course code   (NBSP → space)
    """
    rows = request.get_json(force=True).get("rows", [])

    with sqlite3.connect(DB_NAME) as conn:
        for r in rows:

            # ---- clean up MECE NNNN vs MECE NNNN --------------------------
            clean_course = r["course"].replace("\u00A0", " ")

            values = (
                clean_course,                   # course
                r["course_name"],
                r["slo"], r["pi"],
                r["assessment_tool"], r["explanation"],
                r["semester"], r["blooms_level"],
                r["expert"], r["practitioner"], r["apprentice"], r["novice"],
                r["observations"]
            )

            row_id = r.get("id")                # may be None / ""
            if row_id:                          # ---- UPDATE existing row
                conn.execute("""
                    UPDATE abet_entries SET
                        course          =?, course_name =?,
                        slo             =?, pi          =?,
                        assessment_tool =?, explanation =?,
                        semester        =?, blooms_level=?,
                        expert          =?, practitioner=?,
                        apprentice      =?, novice      =?,
                        observations    =?
                    WHERE id = ?;
                """, (*values, row_id))
            else:                               # ---- INSERT new row
                conn.execute("""
                    INSERT INTO abet_entries (
                        course, course_name, slo, pi,
                        assessment_tool, explanation,
                        semester, blooms_level,
                        expert, practitioner, apprentice, novice,
                        observations
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, values)

        conn.commit()
        conn.execute("DELETE FROM user_drafts WHERE user=?", (session["user"],))

    return jsonify({"saved": len(rows)})


# --------------------------------------------------------------------------- #
# Run the app
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    app.run(debug=True)

# --- add at end of ABET_Data_Rev0.py ---
@app.before_request
def must_be_logged_in():
    # The parent app puts the user in the session.
    # If it’s missing, send the browser back to /login.
    if "user" not in session:
        return redirect("/login")
