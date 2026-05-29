from flask import Flask, render_template, request, redirect, session, flash, send_file, url_for
import sqlite3, os, pandas as pd
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'voting_secret_dev')

# Use /tmp/uploads on production (Render), static/uploads locally
if os.environ.get('RENDER'):
    UPLOAD_FOLDER = '/tmp/uploads'
else:
    UPLOAD_FOLDER = 'static/uploads'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Use /tmp on Render (free tier), local voting.db otherwise
DB_PATH = '/tmp/voting.db' if os.environ.get('RENDER') else 'voting.db'

def allowed_file(fname):
    return '.' in fname and fname.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE,
      password TEXT,
      name TEXT,
      dob TEXT,
      citizenship_id TEXT UNIQUE,
      citizenship_photo TEXT,
      personal_photo TEXT,
      verified INTEGER DEFAULT 0,
      role TEXT DEFAULT 'user'
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS elections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT,
      start_date TEXT,
      end_date TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,
      party TEXT,
      election_id INTEGER,
      FOREIGN KEY(election_id) REFERENCES elections(id)
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS votes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      candidate_id INTEGER,
      election_id INTEGER
    )""")
    c.execute("INSERT OR IGNORE INTO users(username,password,role,verified) VALUES('admin','admin123','admin',1)")
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        name = request.form['name']
        dob = request.form['dob']
        cid = request.form['citizenship_id']
        cit = request.files.get('citizenship_photo')
        per = request.files.get('personal_photo')

        if not (cit and per and allowed_file(cit.filename) and allowed_file(per.filename)):
            flash("Please upload two valid image files.")
            return redirect('/register')

        cit_name = secure_filename(f"cit_{u}_{cit.filename}")
        per_name = secure_filename(f"per_{u}_{per.filename}")
        cit.save(os.path.join(UPLOAD_FOLDER, cit_name))
        per.save(os.path.join(UPLOAD_FOLDER, per_name))

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if username already exists
        cursor.execute("SELECT 1 FROM users WHERE username = ?", (u,))
        if cursor.fetchone():
            flash("Username already exists.")
            conn.close()
            return redirect('/register')

        # Check if citizenship ID already exists
        cursor.execute("SELECT 1 FROM users WHERE citizenship_id = ?", (cid,))
        if cursor.fetchone():
            flash("A user with this citizenship ID already exists.")
            conn.close()
            return redirect('/register')

        # If unique, insert user
        try:
            cursor.execute("""
                INSERT INTO users(username, password, name, dob, citizenship_id, citizenship_photo, personal_photo)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (u, p, name, dob, cid, cit_name, per_name))
            conn.commit()
            flash("Registered! Await admin approval.")
            return redirect('/login')
        except Exception as e:
            flash("Registration failed.")
        finally:
            conn.close()

    return render_template('register.html')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form['username']
        p = request.form['password']
        conn = sqlite3.connect(DB_PATH)
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p)).fetchone()
        conn.close()
        if not user:
            flash("Invalid credentials.")
            return redirect('/login')

        (uid, uname, pwd, name, dob, cid, cit_photo,
         per_photo, verified, role) = user

        if role != 'admin' and verified == 0:
            flash("Awaiting admin approval.")
            return redirect('/login')

        session['user_id'] = uid
        session['username'] = uname
        session['role'] = role
        session['logged_in'] = True
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'role' not in session:
        return redirect('/login')
    return redirect('/admin') if session['role']=='admin' else redirect('/user')

@app.route('/admin')
def admin_dashboard():
    if session.get('role')!='admin':
        return redirect('/login')
    return render_template('admin_dashboard.html')

@app.route('/admin/manage_election', methods=['GET', 'POST'])
def manage_election():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Handle creating a new election
    if request.method == 'POST' and 'create_election' in request.form:
        title = request.form['title']
        start_datetime = request.form['start_date']  # e.g., "2025-07-20T09:00"
        end_datetime = request.form['end_date']      # e.g., "2025-07-21T17:00"

        try:
            start_dt = datetime.fromisoformat(start_datetime)
            end_dt = datetime.fromisoformat(end_datetime)
            if start_dt > end_dt:
                flash("Start date/time cannot be after end date/time.", "danger")
            else:
                cursor.execute("INSERT INTO elections(title, start_date, end_date) VALUES (?, ?, ?)",
                               (title, start_datetime, end_datetime))
                conn.commit()
                flash("Election created successfully.", "success")
        except ValueError:
            flash("Invalid date/time format.", "danger")

    # Handle adding a candidate
    if request.method == 'POST' and 'add_candidate' in request.form:
        name = request.form['candidate_name']
        party = request.form['party']
        election_id = request.form['election_id']
        cursor.execute("INSERT INTO candidates(name, party, election_id) VALUES (?, ?, ?)",
                       (name, party, election_id))
        conn.commit()
        flash("Candidate added.", "success")

    # Fetch elections and candidates
    cursor.execute("SELECT * FROM elections")
    elections = cursor.fetchall()

    cursor.execute("""
        SELECT c.id, c.name, c.party, c.election_id, e.title
        FROM candidates c
        LEFT JOIN elections e ON c.election_id = e.id
    """)
    candidates = cursor.fetchall()

    conn.close()

    return render_template('manage_election.html', elections=elections, candidates=candidates)


@app.route('/admin/delete_election/<int:election_id>', methods=['POST'])
def delete_election(election_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM candidates WHERE election_id=?", (election_id,))
    cursor.execute("DELETE FROM votes WHERE election_id=?", (election_id,))
    cursor.execute("DELETE FROM elections WHERE id=?", (election_id,))
    conn.commit()
    conn.close()
    flash("Election and related data deleted.")
    return redirect(url_for('manage_election'))

@app.route('/admin/delete_candidate/<int:candidate_id>', methods=['POST'])
def delete_candidate(candidate_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM votes WHERE candidate_id=?", (candidate_id,))
    cursor.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
    conn.commit()
    conn.close()
    flash("Candidate deleted.")
    return redirect(url_for('manage_election'))

@app.route('/admin/verify_users')
def verify_users():
    if session.get('role') != 'admin':
        return redirect('/login')
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("""
        SELECT id, username, name, dob, citizenship_id, citizenship_photo, personal_photo, verified
        FROM users
        WHERE role='user'
    """).fetchall()
    conn.close()
    return render_template('verify_users.html', users=users)

@app.route('/admin/approve_user/<int:user_id>')
def approve_user(user_id):
    if session.get('role')!='admin':
        return redirect('/login')
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET verified=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User approved.")
    return redirect('/admin/verify_users')

@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted successfully.")
    return redirect(url_for('verify_users'))


@app.route('/user')
def user_dashboard():
    if session.get('role') != 'user':
        return redirect('/login')

    now = datetime.now().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    ongoing = cursor.execute("SELECT * FROM elections WHERE start_date <= ? AND end_date >= ?", (now, now)).fetchall()
    expired = cursor.execute("SELECT * FROM elections WHERE end_date < ?", (now,)).fetchall()
    future = cursor.execute("SELECT * FROM elections WHERE start_date > ?", (now,)).fetchall()

    voted = cursor.execute("SELECT election_id FROM votes WHERE user_id = ?", (session['user_id'],)).fetchall()
    voted_ids = {v[0] for v in voted}

    conn.close()
    return render_template('user_dashboard.html', ongoing=ongoing, expired=expired, future=future, voted=voted_ids)



@app.route('/vote/<int:election_id>', methods=['GET','POST'])
def vote(election_id):
    if session.get('role')!='user':
        return redirect('/login')
    conn = sqlite3.connect(DB_PATH)
    verified = conn.execute("SELECT verified FROM users WHERE id=?", (session['user_id'],)).fetchone()[0]
    if verified == 0:
        conn.close()
        flash("Awaiting admin approval.")
        return redirect('/user')
    now = datetime.now().isoformat()
    election = conn.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    if not (election[2] <= now <= election[3]):
        conn.close()
        flash("Election not active.")
        return redirect('/user')
    if conn.execute("SELECT * FROM votes WHERE user_id=? AND election_id=?", (session['user_id'], election_id)).fetchone():
        conn.close()
        flash("Already voted.")
        return redirect('/user')
    candidates = conn.execute("SELECT * FROM candidates WHERE election_id=?", (election_id,)).fetchall()
    if request.method=='POST':
        cid = request.form['candidate']
        conn.execute("INSERT INTO votes(user_id,candidate_id,election_id) VALUES(?,?,?)",
                     (session['user_id'], cid, election_id))
        conn.commit()
        conn.close()
        flash("Vote cast!")
        return redirect('/user')
    conn.close()
    return render_template('vote.html', election=election, candidates=candidates)

@app.route('/result/<int:election_id>')
def result(election_id):
    if 'role' not in session:
        return redirect('/login')

    conn = sqlite3.connect(DB_PATH)
    election = conn.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()

    # Check for normal users if election has ended
    if session['role'] != 'admin':
        now = datetime.now().isoformat()
        if now <= election[3]:
            conn.close()
            flash("Results are not available until the election ends.")
            return redirect('/user')

    result = conn.execute(
        "SELECT candidates.name, COUNT(votes.id) as vote_count FROM votes "
        "JOIN candidates ON votes.candidate_id = candidates.id "
        "WHERE votes.election_id = ? "
        "GROUP BY candidates.name", (election_id,)
    ).fetchall()
    conn.close()

    return render_template('result.html', result=result, election=election)



@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# Initialize DB on startup
try:
    init_db()
except Exception as e:
    print(f"DB init error: {e}")

if __name__ == '__main__':
    app.run(debug=False)

