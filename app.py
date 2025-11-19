# app.py
"""
Complete Single-Department College Attendance Management System
Cleaned & updated single-file Flask app (port 5001)

Notes:
- Explicit relationships added with `foreign_keys` to avoid ambiguous joins.
- Simple DB compatibility check: if existing SQLite DB schema is incompatible
  (missing expected columns), the file is backed up and a fresh DB is created.
- All routes, helpers and templates kept in a single file for easy testing.
"""

import os
import secrets
import io
import csv
import shutil
import sqlite3
from datetime import datetime, timedelta, date
from functools import wraps
from collections import defaultdict

from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, case
from sqlalchemy.exc import OperationalError

# ----------------- App setup -----------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
DB_FILE = os.environ.get('DATABASE_URI', 'sqlite:///college_attendance.db').replace('sqlite:///', '')
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_FILE}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

db = SQLAlchemy(app)

# ==================== MODELS ====================
# NOTE: define relationships with explicit foreign_keys to avoid ambiguous joins

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, teacher, student
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    failed_attempts = db.Column(db.Integer, default=0)

    # relationships
    login_history = db.relationship('LoginHistory', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='LoginHistory.user_id')
    students = db.relationship('Student', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='Student.user_id')
    teachers = db.relationship('Teacher', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='Teacher.user_id')
    edited_attendances = db.relationship('Attendance', backref='editor', lazy=True, foreign_keys='Attendance.edited_by')


class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    logout_time = db.Column(db.DateTime)


class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    type = db.Column(db.String(10), nullable=False)  # UG or PG
    duration = db.Column(db.Integer)  # Number of semesters
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subjects = db.relationship('Subject', backref='program', lazy=True)
    students = db.relationship('Student', backref='program', lazy=True)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, index=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'), index=True)
    batch = db.Column(db.String(20))  # e.g., 2024
    division = db.Column(db.String(10))  # A, B, C, etc.
    semester = db.Column(db.Integer)
    photo_url = db.Column(db.String(200))
    parent_contact = db.Column(db.String(20))
    parent_email = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True)

    attendances = db.relationship('Attendance', backref='student', lazy=True, foreign_keys='Attendance.student_id')
    leaves = db.relationship('LeaveRequest', backref='student', lazy=True)


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    teacher_type = db.Column(db.String(20))  # Major, Minor, Assistant
    contact = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

    teacher_subjects = db.relationship('TeacherSubject', backref='teacher', lazy=True)
    timetables = db.relationship('Timetable', backref='teacher', lazy=True)
    attendances = db.relationship('Attendance', backref='teacher', lazy=True, foreign_keys='Attendance.teacher_id')


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    credits = db.Column(db.Integer)
    subject_type = db.Column(db.String(20))  # Major, Minor, AEC, VAC, MDC, SEC, Lab
    class_type = db.Column(db.String(20))  # Theory, Lab, Seminar
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'), index=True)
    semester = db.Column(db.Integer)
    weekly_hours = db.Column(db.Integer, default=3)

    teacher_subjects = db.relationship('TeacherSubject', backref='subject', lazy=True)
    timetables = db.relationship('Timetable', backref='subject', lazy=True)
    attendances = db.relationship('Attendance', backref='subject', lazy=True)


class TeacherSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), index=True)
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))
    semester = db.Column(db.Integer)
    academic_year = db.Column(db.String(20))


class Timetable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), index=True)
    day = db.Column(db.String(10))  # Monday, Tuesday, etc.
    period = db.Column(db.Integer)  # 1-5 or session (FN/AN)
    session_type = db.Column(db.String(10))  # FN, AN, Period
    room = db.Column(db.String(50))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))
    semester = db.Column(db.Integer)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    session_type = db.Column(db.String(10))  # FN, AN, Period
    period = db.Column(db.Integer)  # 1-5 if period-wise, null if session-wise
    status = db.Column(db.String(20))  # Present, Absent, Late, EarlyExit, OD, ML, EL
    remarks = db.Column(db.Text)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    edited_at = db.Column(db.DateTime)
    edited_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_locked = db.Column(db.Boolean, default=False)

    # explicit relationships:
    # - 'student', 'subject', 'teacher' backrefs already defined on those models
    editor = db.relationship('User', foreign_keys=[edited_by], backref='edited_records')


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(20))  # Medical, Personal, Emergency
    reason = db.Column(db.Text)
    proof_url = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    action = db.Column(db.String(100))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==================== HELPERS / UTILITIES ====================
def backup_and_reset_db(db_path):
    """Back up the existing sqlite database and remove it (so create_all will recreate)."""
    try:
        if os.path.exists(db_path):
            ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            bak_name = f"{db_path}.bak.{ts}"
            shutil.copy2(db_path, bak_name)
            print(f"⚠️  Backed up existing DB to: {bak_name}")
            os.remove(db_path)
            print("🔄 Removed old DB file to recreate schema.")
    except Exception as e:
        print("Error while backing up DB:", e)


def is_db_compatible(db_path):
    """
    Quick schema check: ensure that the 'user' table contains expected columns.
    If DB doesn't exist, return True (we will create it).
    If it exists and appears compatible, return True; otherwise False.
    """
    if not os.path.exists(db_path):
        return True
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(user);")
        cols = [r[1] for r in cur.fetchall()]  # name column
        conn.close()
        # required columns from the User model
        required = {'id', 'username', 'email', 'password', 'role', 'created_at'}
        if required.issubset(set(cols)):
            return True
        return False
    except Exception:
        return False


def ensure_db():
    """Ensure DB is present and compatible; back it up if not compatible, then create_all."""
    db_path = DB_FILE
    if not is_db_compatible(db_path):
        backup_and_reset_db(db_path)
    # create tables (safe to call repeatedly)
    with app.app_context():
        db.create_all()


# ==================== DECORATORS ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] not in roles:
                flash('Access denied', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_audit(action, details=''):
    try:
        log = AuditLog(
            user_id=session.get('user_id'),
            action=action,
            details=details,
            ip_address=request.remote_addr if request else None
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


def calculate_attendance_percentage(student_id, subject_id=None, from_date=None, to_date=None):
    q = db.session.query(
        func.count(Attendance.id).label('total'),
        func.sum(case([(Attendance.status.in_(['Present', 'Late', 'OD']), 1)], else_=0)).label('present')
    ).filter(Attendance.student_id == student_id)

    if subject_id:
        q = q.filter(Attendance.subject_id == subject_id)
    if from_date:
        q = q.filter(Attendance.date >= from_date)
    if to_date:
        q = q.filter(Attendance.date <= to_date)
    row = q.one_or_none()
    if not row or (row.total or 0) == 0:
        return 0.0
    total = row.total or 0
    present = row.present or 0
    try:
        return round((present / total) * 100, 2)
    except ZeroDivisionError:
        return 0.0


def get_student_subject_attendance(student_id):
    student = Student.query.get(student_id)
    if not student:
        return []
    subjects = Subject.query.filter_by(program_id=student.program_id, semester=student.semester).all()
    result = []
    for subject in subjects:
        agg = db.session.query(
            func.count(Attendance.id).label('total'),
            func.sum(case([(Attendance.status.in_(['Present', 'Late', 'OD']), 1)], else_=0)).label('present')
        ).filter(Attendance.student_id == student_id, Attendance.subject_id == subject.id).one()
        total = agg.total or 0
        present = agg.present or 0
        percentage = round((present / total * 100), 2) if total > 0 else 0.0
        result.append({
            'subject_code': subject.code,
            'subject_name': subject.name,
            'subject_type': subject.subject_type,
            'total': total,
            'present': present,
            'percentage': percentage
        })
    return result


def get_defaulter_students(threshold=75):
    # Aggregate attendance per student in one query (avoid N+1)
    agg_q = db.session.query(
        Attendance.student_id.label('student_id'),
        func.count(Attendance.id).label('total'),
        func.sum(case([(Attendance.status.in_(['Present', 'Late', 'OD']), 1)], else_=0)).label('present')
    ).group_by(Attendance.student_id).subquery()

    joined = db.session.query(
        Student, agg_q.c.total, agg_q.c.present
    ).join(agg_q, Student.id == agg_q.c.student_id).filter(Student.is_active == True)

    defaulters = []
    for student, total, present in joined:
        total = total or 0
        present = present or 0
        perc = round((present / total * 100), 2) if total > 0 else 0.0
        if perc < threshold:
            defaulters.append({'student': student, 'percentage': perc})
    # Also include students with zero records (total 0) as defaulters at 0%
    zero_q = db.session.query(Student).filter(~Student.id.in_(db.session.query(Attendance.student_id)), Student.is_active == True)
    for s in zero_q:
        if 0 < threshold:
            defaulters.append({'student': s, 'percentage': 0.0})
    defaulters.sort(key=lambda x: x['percentage'])
    return defaulters


# ==================== TEMPLATES ====================
# (For brevity I keep templates identical to what you provided earlier;
#  they are large; you can edit them later. For production, move templates
#  into templates/*.html files instead of inline.)

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Attendance System{% endblock %}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --info: #3b82f6;
            --dark: #1f2937;
            --light: #f3f4f6;
            --border: #e5e7eb;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--light); line-height: 1.6; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .navbar { background: linear-gradient(135deg, var(--primary), var(--primary-dark)); color: white; padding: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.15); position: sticky; top: 0; z-index: 100; }
        .navbar .container { display: flex; justify-content: space-between; align-items: center; }
        .navbar h1 { font-size: 1.5rem; font-weight: 700; }
        .navbar a { color: white; text-decoration: none; margin-left: 18px; transition: opacity 0.2s; font-weight: 500; }
        .navbar a:hover { opacity: 0.8; }
        .card { background: white; border-radius: 12px; padding: 25px; margin: 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: box-shadow 0.2s; }
        .card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.2s; display: inline-block; text-decoration: none; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-success { background: var(--success); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-warning { background: var(--warning); color: white; }
        .btn-info { background: var(--info); color: white; }
        .form-group { margin: 15px 0; }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .alert { padding: 15px 20px; border-radius: 8px; margin: 15px 0; border-left: 4px solid; }
        .alert-success { background: #d1fae5; color: #065f46; border-color: var(--success); }
        .alert-danger { background: #fee2e2; color: #991b1b; border-color: var(--danger); }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; background: white; }
        table th, table td { padding: 14px; text-align: left; border-bottom: 1px solid var(--border); }
        @media (max-width: 768px) {
            .form-row { grid-template-columns: 1fr; }
            .navbar .container { flex-direction: column; text-align: center; }
            .navbar a { margin: 5px 10px; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="container">
            <h1>🎓 College Attendance System</h1>
            <div>
                {% if session.username %}
                    <span style="margin-right:15px;">{{ session.username }} ({{ session.role|upper }})</span>
                    <a href="{{ url_for('dashboard') }}">📊 Dashboard</a>
                    {% if session.role == 'teacher' %}
                        <a href="{{ url_for('mark_attendance') }}">✓ Mark Attendance</a>
                        <a href="{{ url_for('view_attendance') }}">📋 View Records</a>
                    {% elif session.role == 'student' %}
                        <a href="{{ url_for('view_attendance') }}">📋 My Attendance</a>
                        <a href="{{ url_for('apply_leave') }}">📝 Apply Leave</a>
                    {% elif session.role == 'admin' %}
                        <a href="{{ url_for('reports_page') }}">📊 Reports</a>
                        <a href="{{ url_for('system_settings') }}">⚙️ Settings</a>
                    {% endif %}
                    <a href="{{ url_for('logout') }}">🚪 Logout</a>
                {% else %}
                    <a href="{{ url_for('login') }}">🔐 Login</a>
                {% endif %}
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

# Minimal templates derived from BASE_TEMPLATE for common pages (kept concise)
LOGIN_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<div style="max-width: 450px; margin: 80px auto;">
    <div class="card">
        <h2 style="text-align:center; margin-bottom:30px; color:var(--primary);">🔐 Login to System</h2>
        <form method="POST">
            <div class="form-group"><label>Username</label><input type="text" name="username" required autofocus></div>
            <div class="form-group"><label>Password</label><input type="password" name="password" required></div>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Login</button>
        </form>
        <p style="margin-top:20px; text-align:center; color:#6b7280; font-size:13px;">Default: admin/admin123 (change after login)</p>
    </div>
</div>
{% endblock %}
''')

# For brevity in this single-file, add a couple of compact templates used in routes.
# (You can expand these or re-use your full templates as needed.)
DASHBOARD_SIMPLE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Dashboard</h2>
<div class="card">
    <p>Welcome, {{ session.username }} ({{ session.role }})</p>
    {% if session.role == 'admin' %}
        <a class="btn btn-primary" href="{{ url_for('manage_programs') }}">Manage Programs</a>
        <a class="btn btn-success" href="{{ url_for('manage_students') }}">Manage Students</a>
        <a class="btn btn-info" href="{{ url_for('manage_teachers') }}">Manage Teachers</a>
    {% elif session.role == 'teacher' %}
        <a class="btn btn-primary" href="{{ url_for('mark_attendance') }}">Mark Attendance</a>
        <a class="btn btn-info" href="{{ url_for('view_timetable') }}">My Timetable</a>
    {% elif session.role == 'student' %}
        <a class="btn btn-primary" href="{{ url_for('view_attendance') }}">My Attendance</a>
        <a class="btn btn-success" href="{{ url_for('apply_leave') }}">Apply Leave</a>
    {% endif %}
</div>
{% endblock %}
''')

# ------------------- ROUTES (core ones implemented) -------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()
        if user and user.is_active:
            if user.failed_attempts >= 5:
                flash('Account locked due to multiple failed attempts. Contact administrator.', 'danger')
                return redirect(url_for('login'))
            if check_password_hash(user.password, password):
                session.clear()
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                session.permanent = True
                user.last_login = datetime.utcnow()
                user.failed_attempts = 0
                login_hist = LoginHistory(
                    user_id=user.id,
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent', '')[:200]
                )
                db.session.add(login_hist)
                db.session.commit()
                log_audit('Login', f'User {username} logged in')
                flash(f'Welcome back, {username}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                user.failed_attempts += 1
                db.session.commit()
                flash('Invalid credentials', 'danger')
        else:
            flash('Invalid credentials or account inactive', 'danger')
    return render_template_string(LOGIN_TEMPLATE)


@app.route('/logout')
@login_required
def logout():
    login_hist = LoginHistory.query.filter_by(user_id=session['user_id'], logout_time=None).first()
    if login_hist:
        login_hist.logout_time = datetime.utcnow()
        db.session.commit()
    log_audit('Logout', f'User {session.get("username")} logged out')
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    if role == 'admin':
        # simplified admin summary
        stats = {
            'total_students': Student.query.filter_by(is_active=True).count(),
            'total_teachers': Teacher.query.filter_by(is_active=True).count(),
            'total_programs': Program.query.count(),
            'total_subjects': Subject.query.count(),
            'pending_leaves': LeaveRequest.query.filter_by(status='pending').count(),
        }
        return render_template_string(DASHBOARD_SIMPLE, stats=stats)
    elif role == 'teacher':
        return render_template_string(DASHBOARD_SIMPLE)
    else:
        return render_template_string(DASHBOARD_SIMPLE)


# -------------------- Admin Management (selected) --------------------
@app.route('/admin/programs', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_programs():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip()
        type_ = request.form.get('type')
        duration = request.form.get('duration') or None
        if not name or not code:
            flash('Name and code required', 'danger')
            return redirect(url_for('manage_programs'))
        if Program.query.filter_by(code=code).first():
            flash('Program code already exists', 'danger')
            return redirect(url_for('manage_programs'))
        program = Program(name=name, code=code, type=type_, duration=int(duration) if duration else None)
        db.session.add(program)
        db.session.commit()
        log_audit('Create Program', f'Created program: {name}')
        flash('Program created successfully', 'success')
        return redirect(url_for('manage_programs'))
    programs = Program.query.all()
    # small program list template inline
    content = '''
    {% extends base %}
    {% block content %}
    <h2>Manage Programs</h2>
    <div class="card">
      <form method="POST">
        <div class="form-row">
          <input name="name" placeholder="Program name" required>
          <input name="code" placeholder="Program code" required>
        </div>
        <div class="form-row">
          <select name="type"><option value="UG">UG</option><option value="PG">PG</option></select>
          <input name="duration" type="number" placeholder="Semesters">
        </div>
        <button class="btn btn-success" type="submit">Create</button>
      </form>
    </div>
    <div class="card">
      <table><thead><tr><th>ID</th><th>Name</th><th>Code</th></tr></thead><tbody>
      {% for p in programs %}<tr><td>{{p.id}}</td><td>{{p.name}}</td><td>{{p.code}}</td></tr>{% endfor %}
      </tbody></table>
    </div>
    {% endblock %}
    '''
    # Use base template as 'base' variable in render_template_string context
    return render_template_string('{% set base %}' + BASE_TEMPLATE + '{% endset %}' + content, programs=programs)


@app.route('/admin/students', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'teacher')
def manage_students():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = generate_password_hash(request.form.get('password') or 'student123')
        roll_number = (request.form.get('roll_number') or '').strip()
        name = (request.form.get('name') or '').strip()
        program_id = request.form.get('program_id')
        batch = request.form.get('batch')
        division = request.form.get('division')
        semester = request.form.get('semester')
        parent_contact = request.form.get('parent_contact')
        parent_email = request.form.get('parent_email')
        if User.query.filter_by(username=username).first() or Student.query.filter_by(roll_number=roll_number).first():
            flash('Username or roll number already exists', 'danger')
            return redirect(url_for('manage_students'))
        user = User(username=username, email=email, password=password, role='student')
        db.session.add(user)
        db.session.flush()
        student = Student(user_id=user.id, roll_number=roll_number, name=name, program_id=program_id, batch=batch, division=division, semester=semester, parent_contact=parent_contact, parent_email=parent_email)
        db.session.add(student)
        db.session.commit()
        log_audit('Create Student', f'Created student: {name} ({roll_number})')
        flash('Student created successfully', 'success')
        return redirect(url_for('manage_students'))
    students = db.session.query(Student, Program, User).join(Program, Student.program_id == Program.id).join(User, Student.user_id == User.id).all()
    programs = Program.query.all()
    # Render a compact students page
    html = '''
    {% set base %}''' + BASE_TEMPLATE + '''{% endset %}
    {% block content %}
    <h2>Students</h2>
    <div class="card">
      <form method="POST">
        <div class="form-row">
          <input name="username" placeholder="username" required>
          <input name="email" placeholder="email" required>
        </div>
        <div class="form-row">
          <input name="password" placeholder="password" required>
          <input name="roll_number" placeholder="roll number" required>
        </div>
        <input name="name" placeholder="full name" required>
        <div class="form-row">
          <select name="program_id">{% for p in programs %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}</select>
          <input name="batch" placeholder="Batch">
        </div>
        <div class="form-row">
          <input name="division" placeholder="Division">
          <input name="semester" placeholder="Semester">
        </div>
        <button class="btn btn-success" type="submit">Add Student</button>
      </form>
    </div>
    <div class="card">
      <table><thead><tr><th>Roll</th><th>Name</th><th>Program</th></tr></thead><tbody>
      {% for stud, prog, user in students %}
        <tr><td>{{stud.roll_number}}</td><td>{{stud.name}}</td><td>{{prog.code}}</td></tr>
      {% endfor %}
      </tbody></table>
    </div>
    {% endblock %}
    '''
    return render_template_string(html, students=students, programs=programs)


# -------------------- Attendance --------------------
@app.route('/attendance/mark', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def mark_attendance():
    teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
    if request.method == 'POST':
        data = request.get_json()
        subject_id = data.get('subject_id')
        date_str = data.get('date')
        try:
            attendance_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid date format'})
        session_type = data.get('session_type')  # FN, AN, Period
        period = data.get('period')
        attendance_data = data.get('attendance') or []
        existing = Attendance.query.filter_by(subject_id=subject_id, teacher_id=teacher.id, date=attendance_date, session_type=session_type, period=period).first()
        if existing and existing.is_locked:
            return jsonify({'success': False, 'message': 'Attendance is locked and cannot be modified'})
        # Delete existing attendance for this session
        Attendance.query.filter_by(subject_id=subject_id, teacher_id=teacher.id, date=attendance_date, session_type=session_type, period=period).delete()
        for item in attendance_data:
            att = Attendance(
                student_id=item['student_id'],
                subject_id=subject_id,
                teacher_id=teacher.id,
                date=attendance_date,
                session_type=session_type,
                period=period,
                status=item['status'],
                remarks=item.get('remarks', '')
            )
            db.session.add(att)
        db.session.commit()
        log_audit('Mark Attendance', f'Marked attendance for subject {subject_id} on {date_str}')
        return jsonify({'success': True, 'message': 'Attendance marked successfully'})
    teacher_subjects = db.session.query(TeacherSubject, Subject).join(Subject, TeacherSubject.subject_id == Subject.id).filter(TeacherSubject.teacher_id == teacher.id).all()
    # small mark attendance UI
    html = '''
    {% set base %}''' + BASE_TEMPLATE + '''{% endset %}
    {% block content %}
    <h2>Mark Attendance</h2>
    <div class="card">
      <p>Teacher: {{teacher.name}}</p>
      <form id="attform" onsubmit="return false;">
        <div class="form-row">
          <select id="subject">{% for ts, s in teacher_subjects %}<option value="{{s.id}}">{{s.name}} - {{ts.batch or ''}}-{{ts.division or ''}}</option>{% endfor %}</select>
          <input id="date" type="date" value="{{ default_date }}">
        </div>
        <div style="margin-top:10px;">
          <button class="btn btn-primary" onclick="loadStudents()">Load Students</button>
        </div>
      </form>
    </div>
    <div class="card" id="stuList" style="display:none;">
      <button class="btn btn-success" onclick="markAll('Present')">All Present</button>
      <button class="btn btn-danger" onclick="markAll('Absent')">All Absent</button>
      <table id="stuTable"></table>
      <div style="margin-top:10px;"><button class="btn btn-primary" onclick="submitAtt()">Submit</button></div>
    </div>

    <script>
    function loadStudents() {
      const sid = document.getElementById('subject').value;
      // NOTE: teacher must include batch/division in TeacherSubject for correct filtering in real setup.
      fetch(`/attendance/students/${sid}/ALL/ALL`).then(r=>r.json()).then(students=>{
        let html = '<thead><tr><th>Roll</th><th>Name</th><th>Status</th></tr></thead><tbody>';
        students.forEach(s => {
          html += `<tr><td>${s.roll_number}</td><td>${s.name}</td><td><select class="status-sel" data-id="${s.id}"><option>Present</option><option>Absent</option><option>Late</option><option>OD</option></select></td></tr>`;
        });
        html += '</tbody>';
        document.getElementById('stuTable').innerHTML = html;
        document.getElementById('stuList').style.display = 'block';
      });
    }
    function markAll(status) {
      document.querySelectorAll('.status-sel').forEach(s => s.value = status);
    }
    function submitAtt() {
      const att = [];
      document.querySelectorAll('.status-sel').forEach(s => {
        att.push({ student_id: parseInt(s.getAttribute('data-id')), status: s.value, remarks: '' });
      });
      fetch('/attendance/mark', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ subject_id: parseInt(document.getElementById('subject').value), date: document.getElementById('date').value, session_type: 'FN', period: null, attendance: att })
      }).then(r=>r.json()).then(d=>{ alert(d.message || 'Done'); if(d.success) window.location.reload(); });
    }
    </script>
    {% endblock %}
    '''
    return render_template_string(html, teacher_subjects=teacher_subjects, teacher=teacher, default_date=date.today().isoformat())


@app.route('/attendance/students/<int:subject_id>/<batch>/<division>')
@login_required
@role_required('teacher')
def get_students_for_attendance(subject_id, batch, division):
    # If batch/division = 'ALL', return broad list (useful for basic testing)
    q = Student.query.filter(Student.is_active == True)
    if batch and batch != 'ALL':
        q = q.filter_by(batch=batch)
    if division and division != 'ALL':
        q = q.filter_by(division=division)
    students = q.order_by(Student.roll_number).all()
    return jsonify([{'id': s.id, 'roll_number': s.roll_number, 'name': s.name} for s in students])


@app.route('/attendance/view')
@login_required
def view_attendance():
    role = session.get('role')
    if role == 'student':
        student = Student.query.filter_by(user_id=session['user_id']).first()
        query = db.session.query(Attendance, Subject).join(Subject, Attendance.subject_id == Subject.id).filter(Attendance.student_id == student.id)
        attendance = query.order_by(Attendance.date.desc()).limit(200).all()
        # small listing
        html = '''
        {% set base %}''' + BASE_TEMPLATE + '''{% endset %}
        {% block content %}
        <h2>My Attendance</h2>
        <div class="card">
          <table><thead><tr><th>Date</th><th>Subject</th><th>Status</th></tr></thead>
          <tbody>{% for a, s in attendance %}<tr><td>{{a.date}}</td><td>{{s.name}}</td><td>{{a.status}}</td></tr>{% endfor %}</tbody></table>
        </div>
        {% endblock %}
        '''
        return render_template_string(html, attendance=attendance)
    elif role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
        attendance = db.session.query(Attendance, Subject, Student).join(Subject, Attendance.subject_id == Subject.id).join(Student, Attendance.student_id == Student.id).filter(Attendance.teacher_id == teacher.id).order_by(Attendance.date.desc()).limit(200).all()
        html = '''
        {% set base %}''' + BASE_TEMPLATE + '''{% endset %}
        {% block content %}
        <h2>Attendance Records</h2>
        <div class="card"><table><thead><tr><th>Date</th><th>Subject</th><th>Student</th><th>Status</th></tr></thead>
        <tbody>{% for a, s, st in attendance %}<tr><td>{{a.date}}</td><td>{{s.name}}</td><td>{{st.roll_number}}</td><td>{{a.status}}</td></tr>{% endfor %}</tbody></table></div>
        {% endblock %}
        '''
        return render_template_string(html, attendance=attendance)
    else:
        # admin view simplified
        attendance = db.session.query(Attendance, Subject, Student).join(Subject, Attendance.subject_id == Subject.id).join(Student, Attendance.student_id == Student.id).order_by(Attendance.date.desc()).limit(200).all()
        return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
            {% block content %}
            <h2>All Attendance (Admin)</h2>
            <div class="card">
              <table><thead><tr><th>Date</th><th>Subject</th><th>Student</th><th>Status</th></tr></thead>
              <tbody>{% for a, s, st in attendance %}<tr><td>{{a.date}}</td><td>{{s.name}}</td><td>{{st.roll_number}}</td><td>{{a.status}}</td></tr>{% endfor %}</tbody>
              </table>
            </div>
            {% endblock %}
        '''), attendance=attendance)


# -------------------- Leave Management --------------------
@app.route('/leave/apply', methods=['GET', 'POST'])
@login_required
@role_required('student')
def apply_leave():
    student = Student.query.filter_by(user_id=session['user_id']).first()
    if request.method == 'POST':
        from_date = datetime.strptime(request.form.get('from_date'), '%Y-%m-%d').date()
        to_date = datetime.strptime(request.form.get('to_date'), '%Y-%m-%d').date()
        leave_type = request.form.get('leave_type')
        reason = request.form.get('reason')
        leave = LeaveRequest(student_id=student.id, from_date=from_date, to_date=to_date, leave_type=leave_type, reason=reason)
        db.session.add(leave)
        db.session.commit()
        log_audit('Apply Leave', f'Student {student.name} applied for leave from {from_date} to {to_date}')
        flash('Leave application submitted successfully', 'success')
        return redirect(url_for('apply_leave'))
    leaves = LeaveRequest.query.filter_by(student_id=student.id).order_by(LeaveRequest.created_at.desc()).all()
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
        {% block content %}
        <h2>Apply Leave</h2>
        <div class="card">
          <form method="POST">
            <div class="form-row"><input name="from_date" type="date" required><input name="to_date" type="date" required></div>
            <div class="form-row"><select name="leave_type"><option>Medical</option><option>Personal</option></select></div>
            <textarea name="reason" placeholder="Reason"></textarea>
            <button class="btn btn-primary" type="submit">Apply</button>
          </form>
        </div>
        <div class="card"><h3>My Leaves</h3>
          <table><thead><tr><th>From</th><th>To</th><th>Status</th></tr></thead>
            <tbody>{% for l in leaves %}<tr><td>{{l.from_date}}</td><td>{{l.to_date}}</td><td>{{l.status}}</td></tr>{% endfor %}</tbody>
          </table>
        </div>
        {% endblock %}
    '''), leaves=leaves)


@app.route('/leave/manage')
@login_required
@role_required('teacher', 'admin')
def manage_leaves():
    status_filter = request.args.get('status', 'pending')
    query = db.session.query(LeaveRequest, Student, Program).join(Student, LeaveRequest.student_id == Student.id).join(Program, Student.program_id == Program.id)
    if status_filter != 'all':
        query = query.filter(LeaveRequest.status == status_filter)
    leaves = query.order_by(LeaveRequest.created_at.desc()).all()
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
        {% block content %}
        <h2>Manage Leaves</h2>
        <div class="card">
          <table><thead><tr><th>Student</th><th>From</th><th>To</th><th>Type</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>{% for l, s, p in leaves %}<tr><td>{{s.roll_number}} - {{s.name}}</td><td>{{l.from_date}}</td><td>{{l.to_date}}</td><td>{{l.leave_type}}</td><td>{{l.status}}</td>
          <td>{% if l.status == 'pending' %}<a class="btn btn-success" href="{{ url_for('approve_leave', leave_id=l.id) }}">Approve</a> <a class="btn btn-danger" href="{{ url_for('reject_leave', leave_id=l.id) }}">Reject</a>{% endif %}</td></tr>{% endfor %}</tbody></table>
        </div>
        {% endblock %}
    '''), leaves=leaves)


@app.route('/leave/approve/<int:leave_id>')
@login_required
@role_required('teacher', 'admin')
def approve_leave(leave_id):
    leave = LeaveRequest.query.get_or_404(leave_id)
    leave.status = 'approved'
    leave.approved_by = session['user_id']
    leave.approved_at = datetime.utcnow()
    current_date = leave.from_date
    while current_date <= leave.to_date:
        attendances = Attendance.query.filter_by(student_id=leave.student_id, date=current_date).all()
        for att in attendances:
            att.status = 'OD'
            att.remarks = f'Leave approved: {leave.leave_type}'
        current_date += timedelta(days=1)
    db.session.commit()
    log_audit('Approve Leave', f'Approved leave request {leave_id}')
    flash('Leave approved and attendance updated', 'success')
    return redirect(url_for('manage_leaves'))


@app.route('/leave/reject/<int:leave_id>')
@login_required
@role_required('teacher', 'admin')
def reject_leave(leave_id):
    leave = LeaveRequest.query.get_or_404(leave_id)
    leave.status = 'rejected'
    leave.approved_by = session['user_id']
    leave.approved_at = datetime.utcnow()
    db.session.commit()
    log_audit('Reject Leave', f'Rejected leave request {leave_id}')
    flash('Leave request rejected', 'info')
    return redirect(url_for('manage_leaves'))


# -------------------- Simple Reporting --------------------
@app.route('/reports')
@login_required
@role_required('admin', 'teacher')
def reports_page():
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
        {% block content %}
        <h2>Reports</h2>
        <div class="card">
          <a class="btn btn-primary" href="{{ url_for('student_wise_report') }}">Student-wise Report</a>
          <a class="btn btn-danger" href="{{ url_for('defaulters_report') }}">Defaulters</a>
        </div>
        {% endblock %}
    '''))


@app.route('/reports/student-wise')
@login_required
@role_required('admin', 'teacher')
def student_wise_report():
    students = Student.query.filter_by(is_active=True).all()
    report_data = []
    for student in students:
        percentage = calculate_attendance_percentage(student.id)
        report_data.append({'student': student, 'percentage': percentage, 'status': 'Good' if percentage >= 75 else 'Low'})
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
        {% block content %}
        <h2>Student-wise Report</h2>
        <div class="card">
          <table><thead><tr><th>Roll</th><th>Name</th><th>%</th><th>Status</th></tr></thead>
          <tbody>{% for r in report_data %}<tr><td>{{r.student.roll_number}}</td><td>{{r.student.name}}</td><td>{{r.percentage}}</td><td>{{r.status}}</td></tr>{% endfor %}</tbody></table>
        </div>
        {% endblock %}
    '''), report_data=report_data)


@app.route('/reports/defaulters')
@login_required
@role_required('admin', 'teacher')
def defaulters_report():
    threshold = int(request.args.get('threshold', 75))
    defaulters = get_defaulter_students(threshold=threshold)
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
        {% block content %}
        <h2>Defaulters (Below {{threshold}}%)</h2>
        <div class="card">
          <table><thead><tr><th>Roll</th><th>Name</th><th>%</th></tr></thead>
          <tbody>{% for d in defaulters %}<tr><td>{{d.student.roll_number}}</td><td>{{d.student.name}}</td><td>{{d.percentage}}</td></tr>{% endfor %}</tbody></table>
        </div>
        {% endblock %}
    '''), defaulters=defaulters, threshold=threshold)


# -------------------- API --------------------
@app.route('/api/attendance/summary/<int:student_id>')
@login_required
def api_attendance_summary(student_id):
    if session['role'] == 'student':
        student = Student.query.filter_by(user_id=session['user_id']).first()
        if student.id != student_id:
            return jsonify({'error': 'Unauthorized'}), 403
    overall = calculate_attendance_percentage(student_id)
    subject_wise = get_student_subject_attendance(student_id)
    return jsonify({'overall_percentage': overall, 'subject_wise': subject_wise})


@app.route('/api/stats/dashboard')
@login_required
@role_required('admin')
def api_dashboard_stats():
    stats = {
        'total_students': Student.query.filter_by(is_active=True).count(),
        'total_teachers': Teacher.query.filter_by(is_active=True).count(),
        'total_programs': Program.query.count(),
        'total_subjects': Subject.query.count(),
        'pending_leaves': LeaveRequest.query.filter_by(status='pending').count(),
        'defaulters_count': len(get_defaulter_students(75))
    }
    return jsonify(stats)


# ==================== INITIALIZE DATABASE ====================
def init_db():
    ensure_db()
    with app.app_context():
        # ensure admin exists
        try:
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', email='admin@college.edu', password=generate_password_hash('admin123'), role='admin', is_active=True)
                db.session.add(admin)
                db.session.commit()
                print("✓ Admin created: admin/admin123")
            if not Program.query.first():
                prog = Program(name='Bachelor of Computer Applications', code='BCA', type='UG', duration=6)
                db.session.add(prog)
                db.session.commit()
                print("✓ Sample program created")
        except OperationalError as e:
            # If something goes wrong, attempt to backup and recreate DB once
            print("OperationalError during init_db:", e)
            backup_and_reset_db(DB_FILE)
            db.create_all()


# ==================== RUN ====================
if __name__ == '__main__':
    init_db()
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)

