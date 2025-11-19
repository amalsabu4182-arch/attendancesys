"""
College Attendance Management System (Single-File Monolith)
Stack: Flask, SQLite, SQLAlchemy
Features:
  - Role-based Access (Admin, Teacher, Student)
  - Academic Structure (Programs, Subjects, Semesters)
  - Attendance (FN/AN or Period-wise)
  - Reporting & Analytics
"""

import secrets
import io
import csv
import os
from functools import wraps
from datetime import datetime, timedelta, date

from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# ==================== CONFIGURATION ====================

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///college_attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

db = SQLAlchemy(app)


# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, teacher, student
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    failed_attempts = db.Column(db.Integer, default=0)


class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ip_address = db.Column(db.String(50))
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    logout_time = db.Column(db.DateTime)


class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    type = db.Column(db.String(10), nullable=False)  # UG or PG
    duration = db.Column(db.Integer)  # Semesters
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))
    semester = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    name = db.Column(db.String(100), nullable=False)
    teacher_type = db.Column(db.String(20))  # Major, Minor, Assistant
    contact = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    credits = db.Column(db.Integer)
    subject_type = db.Column(db.String(20))  # Major, Minor, AEC, VAC, MDC, SEC, Lab
    class_type = db.Column(db.String(20))  # Theory, Lab
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'))
    semester = db.Column(db.Integer)


class TeacherSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))
    semester = db.Column(db.Integer)
    academic_year = db.Column(db.String(20))


class Timetable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'))
    day = db.Column(db.String(10))
    period = db.Column(db.Integer)
    session_type = db.Column(db.String(10))  # FN, AN, Period
    room = db.Column(db.String(50))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'))
    date = db.Column(db.Date, nullable=False)
    session_type = db.Column(db.String(10))
    period = db.Column(db.Integer)
    status = db.Column(db.String(20))  # Present, Absent, Late, OD
    remarks = db.Column(db.Text)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_locked = db.Column(db.Boolean, default=False)


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(20))
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(100))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==================== HELPERS & DECORATORS ====================

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
        log = AuditLog(user_id=session.get('user_id'), action=action, details=details)
        db.session.add(log)
        db.session.commit()
    except:
        pass


def calculate_attendance_percentage(student_id, subject_id=None):
    query = Attendance.query.filter_by(student_id=student_id)
    if subject_id:
        query = query.filter_by(subject_id=subject_id)

    total = query.count()
    if total == 0: return 0
    present = query.filter(Attendance.status.in_(['Present', 'Late', 'OD'])).count()
    return round((present / total) * 100, 2)


def get_student_subject_attendance(student_id):
    student = Student.query.get(student_id)
    subjects = Subject.query.filter_by(program_id=student.program_id, semester=student.semester).all()
    result = []
    for subject in subjects:
        total = Attendance.query.filter_by(student_id=student_id, subject_id=subject.id).count()
        present = Attendance.query.filter_by(student_id=student_id, subject_id=subject.id).filter(
            Attendance.status.in_(['Present', 'Late', 'OD'])).count()
        percentage = round((present / total * 100), 2) if total > 0 else 0
        result.append({
            'subject_code': subject.code, 'subject_name': subject.name,
            'subject_type': subject.subject_type, 'total': total,
            'present': present, 'percentage': percentage
        })
    return result


def get_defaulter_students(threshold=75):
    students = Student.query.filter_by(is_active=True).all()
    defaulters = []
    for student in students:
        percentage = calculate_attendance_percentage(student.id)
        if percentage < threshold:
            defaulters.append({'student': student, 'percentage': percentage})
    return defaulters


# ==================== TEMPLATES ====================

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>College Attendance System</title>
    <style>
        :root { --primary: #2563eb; --primary-dark: #1d4ed8; --success: #10b981; --danger: #ef4444; --warning: #f59e0b; --info: #3b82f6; --dark: #1f2937; --light: #f3f4f6; --border: #e5e7eb; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--light); line-height: 1.6; color: var(--dark); }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .navbar { background: linear-gradient(135deg, var(--primary), var(--primary-dark)); color: white; padding: 15px 0; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .navbar .container { display: flex; justify-content: space-between; align-items: center; }
        .navbar a { color: white; text-decoration: none; margin-left: 20px; font-weight: 500; }
        .navbar a:hover { opacity: 0.8; }
        .card { background: white; border-radius: 12px; padding: 25px; margin: 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; font-size: 14px; transition: transform 0.2s; }
        .btn:hover { transform: translateY(-2px); }
        .btn-primary { background: var(--primary); color: white; }
        .btn-success { background: var(--success); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-warning { background: var(--warning); color: white; }
        .btn-info { background: var(--info); color: white; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }
        .form-group { margin: 15px 0; }
        .form-group label { display: block; margin-bottom: 8px; font-weight: 600; }
        input, select, textarea { width: 100%; padding: 12px; border: 2px solid var(--border); border-radius: 8px; }
        input:focus, select:focus { outline: none; border-color: var(--primary); }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .alert { padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid; }
        .alert-success { background: #d1fae5; border-color: var(--success); color: #065f46; }
        .alert-danger { background: #fee2e2; border-color: var(--danger); color: #991b1b; }
        .alert-warning { background: #fef3c7; border-color: var(--warning); color: #92400e; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; border-bottom: 1px solid var(--border); text-align: left; }
        th { background: var(--light); font-weight: 700; text-transform: uppercase; font-size: 12px; }
        .badge { padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .badge-success { background: #d1fae5; color: #065f46; }
        .badge-danger { background: #fee2e2; color: #991b1b; }
        .badge-info { background: #dbeafe; color: #1e40af; }
        .badge-warning { background: #fef3c7; color: #92400e; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .stat-card { padding: 25px; border-radius: 12px; color: white; background: linear-gradient(135deg, var(--primary), var(--primary-dark)); }
        .stat-card h3 { font-size: 2.5rem; margin: 10px 0; }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="container">
            <h2>🎓 Attendance System</h2>
            <div>
                {% if session.user_id %}
                    <a href="{{ url_for('dashboard') }}">Dashboard</a>
                    <a href="{{ url_for('logout') }}">Logout</a>
                {% else %}
                    <a href="{{ url_for('login') }}">Login</a>
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

LOGIN_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<div style="max-width: 450px; margin: 80px auto;">
    <div class="card">
        <h2 style="text-align:center; margin-bottom:30px;">Login</h2>
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Login</button>
        </form>
        <p style="text-align:center; margin-top:15px; font-size:13px; color:gray;">Default: admin / admin123</p>
    </div>
</div>
''')

ADMIN_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<h2>Admin Dashboard</h2>
<div class="stats">
    <div class="stat-card">
        <p>TOTAL STUDENTS</p><h3>{{ stats.total_students }}</h3>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, var(--success), #059669);">
        <p>TOTAL TEACHERS</p><h3>{{ stats.total_teachers }}</h3>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, var(--warning), #d97706);">
        <p>PROGRAMS</p><h3>{{ stats.total_programs }}</h3>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, var(--danger), #dc2626);">
        <p>DEFAULTERS</p><h3>{{ stats.defaulters_count }}</h3>
    </div>
</div>
<div class="card">
    <h3>📋 Quick Actions</h3>
    <a href="{{ url_for('manage_programs') }}" class="btn btn-primary">Programs</a>
    <a href="{{ url_for('manage_students') }}" class="btn btn-success">Students</a>
    <a href="{{ url_for('manage_teachers') }}" class="btn btn-info">Teachers</a>
    <a href="{{ url_for('manage_subjects') }}" class="btn btn-warning">Subjects</a>
    <a href="{{ url_for('assign_subjects') }}" class="btn btn-primary">Assignments</a>
    <a href="{{ url_for('manage_timetable') }}" class="btn btn-success">Timetable</a>
    <a href="{{ url_for('manage_leaves') }}" class="btn btn-info">Leaves</a>
    <a href="{{ url_for('reports_page') }}" class="btn btn-warning">Reports</a>
</div>
{% if defaulters %}
<div class="card"><h3>Attendance Defaulters (< 75%)</h3><table><thead><tr><th>Roll No</th><th>Name</th><th>Batch</th><th>%</th></tr></thead><tbody>{% for d in defaulters %}<tr><td>{{ d.student.roll_number }}</td><td>{{ d.student.name }}</td><td>{{ d.student.batch }}</td><td><span class="badge badge-danger">{{ d.percentage }}%</span></td></tr>{% endfor %}</tbody></table></div>
{% endif %}
''')

TEACHER_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<h2>Teacher Dashboard - {{ teacher.name }}</h2>
<div class="card">
    <h3>📅 Today's Classes ({{ current_day }})</h3>
    {% if timetable %}
        <table>
            <thead><tr><th>Period</th><th>Subject</th><th>Room</th><th>Batch</th><th>Action</th></tr></thead>
            <tbody>
                {% for tt in timetable %}
                <tr><td>{{ tt.session_type }} - {{ tt.period }}</td><td>{{ tt.subject_id }}</td><td>{{ tt.room }}</td><td>{{ tt.batch }}-{{ tt.division }}</td><td><a href="{{ url_for('mark_attendance') }}" class="btn btn-success btn-sm">Mark</a></td></tr>
                {% endfor %}
            </tbody>
        </table>
    {% else %}<p>No classes today.</p>{% endif %}
</div>
<div class="card">
    <h3>⚡ Actions</h3>
    <a href="{{ url_for('mark_attendance') }}" class="btn btn-primary">Mark Attendance</a>
    <a href="{{ url_for('view_attendance') }}" class="btn btn-info">View Records</a>
    <a href="{{ url_for('manage_leaves') }}" class="btn btn-warning">Manage Leaves</a>
</div>
''')

STUDENT_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<h2>Student Dashboard</h2>
<div class="stats"><div class="stat-card"><h3>{{ overall_percentage }}%</h3><p>Overall Attendance</p></div></div>
<div class="card"><h3>Subject Wise</h3><table><thead><tr><th>Subject</th><th>Total</th><th>Present</th><th>%</th></tr></thead><tbody>{% for s in subject_attendance %}<tr><td>{{ s.subject_name }}</td><td>{{ s.total }}</td><td>{{ s.present }}</td><td>{{ s.percentage }}%</td></tr>{% endfor %}</tbody></table></div>
<div class="card"><h3>Actions</h3><a href="{{ url_for('view_attendance') }}" class="btn btn-primary">Detailed Attendance</a><a href="{{ url_for('apply_leave') }}" class="btn btn-success">Apply Leave</a></div>
''')

MANAGE_PROGRAMS = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<h2>Manage Programs</h2><div class="card"><h3>Add Program</h3><form method="POST"><div class="form-row"><div class="form-group"><label>Name</label><input name="name" required></div><div class="form-group"><label>Code</label><input name="code" required></div></div><div class="form-row"><div class="form-group"><label>Type</label><select name="type"><option>UG</option><option>PG</option></select></div><div class="form-group"><label>Duration</label><input type="number" name="duration" required></div></div><button class="btn btn-success">Create</button></form></div>
<div class="card"><h3>Existing</h3><table><thead><tr><th>Name</th><th>Code</th><th>Type</th><th>Duration</th></tr></thead><tbody>{% for p in programs %}<tr><td>{{ p.name }}</td><td>{{ p.code }}</td><td>{{ p.type }}</td><td>{{ p.duration }}</td></tr>{% endfor %}</tbody></table></div>
''')

MANAGE_STUDENTS = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<h2>Manage Students</h2>
<div class="card"><h3>Add Student</h3><form method="POST"><div class="form-row"><input name="username" placeholder="Username" required><input name="email" placeholder="Email" required></div><div class="form-row"><input name="password" type="password" placeholder="Password" required><input name="roll_number" placeholder="Roll No" required></div><div class="form-group"><input name="name" placeholder="Full Name" required></div><div class="form-row"><select name="program_id">{% for p in programs %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}</select><input name="batch" placeholder="Batch (2024)"></div><div class="form-row"><input name="division" placeholder="Division"><input name="semester" type="number" placeholder="Sem"></div><button class="btn btn-success">Add Student</button></form></div>
<div class="card"><h3>List</h3><table><thead><tr><th>Roll</th><th>Name</th><th>Prog</th><th>Batch</th></tr></thead><tbody>{% for s,p,u in students %}<tr><td>{{s.roll_number}}</td><td>{{s.name}}</td><td>{{p.code}}</td><td>{{s.batch}}</td></tr>{% endfor %}</tbody></table></div>
''')

MANAGE_TEACHERS = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                        '''<h2>Manage Teachers</h2><div class="card"><h3>Add Teacher</h3><form method="POST"><input type="text" name="username" placeholder="Username" required><input type="email" name="email" placeholder="Email" required><input type="password" name="password" placeholder="Password" required><input type="text" name="name" placeholder="Full Name" required><select name="teacher_type"><option value="Major">Major</option><option value="Minor">Minor</option><option value="Assistant">Assistant</option></select><input type="text" name="contact" placeholder="Contact"><button class="btn btn-success" type="submit">Add Teacher</button></form></div><div class="card"><table><thead><tr><th>Name</th><th>Type</th><th>Email</th></tr></thead><tbody>{% for teach, user in teachers %}<tr><td>{{ teach.name }}</td><td>{{ teach.teacher_type }}</td><td>{{ user.email }}</td></tr>{% endfor %}</tbody></table></div>''')

MANAGE_SUBJECTS = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                        '''<h2>Manage Subjects</h2><div class="card"><form method="POST"><input name="code" placeholder="Subject Code" required><input name="name" placeholder="Subject Name" required><input name="credits" type="number" placeholder="Credits"><select name="subject_type"><option value="Major">Major</option><option value="Minor">Minor</option><option value="AEC">AEC</option><option value="VAC">VAC</option><option value="MDC">MDC</option><option value="SEC">SEC</option><option value="Lab">Lab</option></select><select name="class_type"><option value="Theory">Theory</option><option value="Lab">Lab</option></select><select name="program_id">{% for p in programs %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}</select><input name="semester" type="number" placeholder="Semester"><button class="btn btn-success" type="submit">Add Subject</button></form></div><div class="card"><table><thead><tr><th>Code</th><th>Name</th><th>Type</th></tr></thead><tbody>{% for s, p in subjects %}<tr><td>{{s.code}}</td><td>{{s.name}}</td><td>{{s.subject_type}}</td></tr>{% endfor %}</tbody></table></div>''')

ASSIGN_SUBJECTS = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                        '''<h2>Assign Subjects</h2><div class="card"><form method="POST"><select name="teacher_id">{% for t in teachers %}<option value="{{t.id}}">{{t.name}}</option>{% endfor %}</select><select name="subject_id">{% for s in subjects %}<option value="{{s.id}}">{{s.name}} ({{s.code}})</option>{% endfor %}</select><input name="batch" placeholder="Batch"><input name="division" placeholder="Division"><input name="semester" type="number" placeholder="Semester"><input name="academic_year" placeholder="Year (2024-25)"><button class="btn btn-success" type="submit">Assign</button></form></div><div class="card"><table><thead><tr><th>Teacher</th><th>Subject</th><th>Batch</th></tr></thead><tbody>{% for ts, t, s in assignments %}<tr><td>{{t.name}}</td><td>{{s.name}}</td><td>{{ts.batch}}</td></tr>{% endfor %}</tbody></table></div>''')

MANAGE_TIMETABLE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                         '''<h2>Timetable</h2><div class="card"><form method="POST"><select name="subject_id">{% for s in subjects %}<option value="{{s.id}}">{{s.name}}</option>{% endfor %}</select><select name="teacher_id">{% for t in teachers %}<option value="{{t.id}}">{{t.name}}</option>{% endfor %}</select><select name="day"><option>Monday</option><option>Tuesday</option><option>Wednesday</option><option>Thursday</option><option>Friday</option></select><input name="period" type="number" placeholder="Period"><select name="session_type"><option value="FN">FN</option><option value="AN">AN</option><option value="Period">Period</option></select><input name="room" placeholder="Room"><input name="batch" placeholder="Batch"><input name="division" placeholder="Division"><input name="semester" type="number" placeholder="Semester"><button class="btn btn-success" type="submit">Add</button></form></div><div class="card"><table><thead><tr><th>Day</th><th>Period</th><th>Subject</th><th>Teacher</th></tr></thead><tbody>{% for tt, s, t in timetable %}<tr><td>{{tt.day}}</td><td>{{tt.period}}</td><td>{{s.name}}</td><td>{{t.name}}</td></tr>{% endfor %}</tbody></table></div>''')

MARK_ATTENDANCE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
<script>
function loadStudents() {
    const sel = document.getElementById('subject');
    const opt = sel.options[sel.selectedIndex];
    fetch(`/attendance/students/${sel.value}/${opt.getAttribute('data-batch')}/${opt.getAttribute('data-division')}`)
        .then(r => r.json()).then(students => {
            let html = '<thead><tr><th>Roll</th><th>Name</th><th>Status</th><th>Remarks</th></tr></thead><tbody>';
            students.forEach(s => html += `<tr><td>${s.roll_number}</td><td>${s.name}</td><td><select class="status-sel" data-id="${s.id}"><option>Present</option><option>Absent</option><option>Late</option><option>OD</option></select></td><td><input class="remarks-inp" data-id="${s.id}"></td></tr>`);
            document.getElementById('stuTable').innerHTML = html + '</tbody>';
            document.getElementById('stuList').style.display = 'block';
        });
}
function submitAtt() {
    const att = [];
    document.querySelectorAll('.status-sel').forEach(s => att.push({student_id: s.getAttribute('data-id'), status: s.value, remarks: document.querySelector(`.remarks-inp[data-id="${s.getAttribute('data-id')}"]`).value}));
    fetch('/attendance/mark', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subject_id: document.getElementById('subject').value, date: document.getElementById('date').value, session_type: document.getElementById('session_type').value, period: document.getElementById('period').value, attendance: att})
    }).then(r => r.json()).then(d => {alert(d.message); location.reload();});
}
</script>
<h2>Mark Attendance</h2>
<div class="card"><select id="subject">{% for ts, s in teacher_subjects %}<option value="{{s.id}}" data-batch="{{ts.batch}}" data-division="{{ts.division}}">{{s.name}} - {{ts.batch}}-{{ts.division}}</option>{% endfor %}</select>
<input id="date" type="date" value="{{today}}"><select id="session_type"><option>FN</option><option>AN</option><option>Period</option></select><input id="period" type="number" placeholder="Period (1-5)"><button class="btn btn-primary" onclick="loadStudents()">Load Students</button></div>
<div class="card" id="stuList" style="display:none"><table id="stuTable"></table><button class="btn btn-primary" onclick="submitAtt()">Submit Attendance</button></div>
''')

VIEW_ATTENDANCE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                        '''<h2>Records</h2><div class="card"><table><thead><tr><th>Date</th><th>Subject</th><th>Student</th><th>Status</th></tr></thead><tbody>{% for a, s, st in attendance %}<tr><td>{{a.date}}</td><td>{{s.name}}</td><td>{{st.roll_number}}</td><td>{{a.status}}</td></tr>{% endfor %}</tbody></table></div>''')
REPORTS_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                     '''<h2>Reports</h2><div class="card"><a href="{{ url_for('student_wise_report') }}" class="btn btn-primary">Student-wise</a><a href="{{ url_for('defaulters_report') }}" class="btn btn-danger">Defaulters</a></div>''')
STUDENT_REPORT = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                       '''<h2>Student Report</h2><div class="card"><table>{% for r in report_data %}<tr><td>{{r.student.roll_number}}</td><td>{{r.student.name}}</td><td>{{r.percentage}}%</td></tr>{% endfor %}</table></div>''')
LEAVES_PAGE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                    '''<h2>Leave Management</h2><div class="card"><table><thead><tr><th>Student</th><th>From</th><th>To</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for l, s in leaves %}<tr><td>{{s.name}}</td><td>{{l.from_date}}</td><td>{{l.to_date}}</td><td>{{l.status}}</td><td>{% if l.status == 'pending' %}<a href="{{ url_for('approve_leave', leave_id=l.id) }}" class="btn btn-success btn-sm">Approve</a>{% endif %}</td></tr>{% endfor %}</tbody></table></div>''')
APPLY_LEAVE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}',
                                    '''<h2>Apply Leave</h2><div class="card"><form method="POST"><input name="from_date" type="date" required><input name="to_date" type="date" required><select name="leave_type"><option>Medical</option><option>Personal</option></select><textarea name="reason" placeholder="Reason"></textarea><button class="btn btn-primary">Apply</button></form></div>''')


# ==================== ROUTES ====================

@app.route('/')
def index():
    return redirect(url_for('dashboard')) if 'user_id' in session else redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template_string(LOGIN_TEMPLATE)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    role = session['role']
    if role == 'admin':
        stats = {
            'total_students': Student.query.filter_by(is_active=True).count(),
            'total_teachers': Teacher.query.filter_by(is_active=True).count(),
            'total_programs': Program.query.count(),
            'defaulters_count': len(get_defaulter_students(75))
        }
        defaulters = get_defaulter_students(75)[:10]
        return render_template_string(ADMIN_DASHBOARD, stats=stats, defaulters=defaulters)
    elif role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
        today = date.today().strftime('%A')
        timetable = Timetable.query.filter_by(teacher_id=teacher.id, day=today).order_by(Timetable.period).all()
        return render_template_string(TEACHER_DASHBOARD, teacher=teacher, timetable=timetable, current_day=today)
    elif role == 'student':
        student = Student.query.filter_by(user_id=session['user_id']).first()
        overall = calculate_attendance_percentage(student.id)
        sub_att = get_student_subject_attendance(student.id)
        return render_template_string(STUDENT_DASHBOARD, overall_percentage=overall, subject_attendance=sub_att)


# --- Admin Management ---

@app.route('/admin/programs', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_programs():
    if request.method == 'POST':
        db.session.add(Program(name=request.form['name'], code=request.form['code'], type=request.form['type'],
                               duration=request.form['duration']))
        db.session.commit()
        return redirect(url_for('manage_programs'))
    return render_template_string(MANAGE_PROGRAMS, programs=Program.query.all())


@app.route('/admin/students', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_students():
    if request.method == 'POST':
        u = User(username=request.form['username'], email=request.form['email'],
                 password=generate_password_hash(request.form['password']), role='student')
        db.session.add(u)
        db.session.flush()
        db.session.add(Student(user_id=u.id, roll_number=request.form['roll_number'], name=request.form['name'],
                               program_id=request.form['program_id'], batch=request.form.get('batch'),
                               division=request.form.get('division')))
        db.session.commit()
        return redirect(url_for('manage_students'))
    return render_template_string(MANAGE_STUDENTS,
                                  students=db.session.query(Student, Program, User).join(Program).join(User).all(),
                                  programs=Program.query.all())


@app.route('/admin/teachers', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_teachers():
    if request.method == 'POST':
        u = User(username=request.form['username'], email=request.form['email'],
                 password=generate_password_hash(request.form['password']), role='teacher')
        db.session.add(u)
        db.session.flush()
        db.session.add(Teacher(user_id=u.id, name=request.form['name'], teacher_type=request.form['teacher_type'],
                               contact=request.form['contact']))
        db.session.commit()
        return redirect(url_for('manage_teachers'))
    return render_template_string(MANAGE_TEACHERS, teachers=db.session.query(Teacher, User).join(User).all())


@app.route('/admin/subjects', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_subjects():
    if request.method == 'POST':
        db.session.add(Subject(code=request.form['code'], name=request.form['name'], credits=request.form['credits'],
                               subject_type=request.form['subject_type'], class_type=request.form['class_type'],
                               program_id=request.form['program_id'], semester=request.form['semester']))
        db.session.commit()
        return redirect(url_for('manage_subjects'))
    return render_template_string(MANAGE_SUBJECTS, subjects=db.session.query(Subject, Program).join(Program).all(),
                                  programs=Program.query.all())


@app.route('/admin/assign', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def assign_subjects():
    if request.method == 'POST':
        db.session.add(TeacherSubject(teacher_id=request.form['teacher_id'], subject_id=request.form['subject_id'],
                                      batch=request.form['batch'], division=request.form.get('division'),
                                      semester=request.form.get('semester'),
                                      academic_year=request.form.get('academic_year')))
        db.session.commit()
        return redirect(url_for('assign_subjects'))
    return render_template_string(ASSIGN_SUBJECTS, teachers=Teacher.query.all(), subjects=Subject.query.all(),
                                  assignments=db.session.query(TeacherSubject, Teacher, Subject).join(Teacher).join(
                                      Subject).all())


@app.route('/admin/timetable', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_timetable():
    if request.method == 'POST':
        db.session.add(Timetable(subject_id=request.form['subject_id'], teacher_id=request.form['teacher_id'],
                                 day=request.form['day'], period=request.form['period'],
                                 session_type=request.form['session_type'], room=request.form['room'],
                                 batch=request.form['batch'], division=request.form.get('division')))
        db.session.commit()
        return redirect(url_for('manage_timetable'))
    return render_template_string(MANAGE_TIMETABLE,
                                  timetable=db.session.query(Timetable, Subject, Teacher).join(Subject).join(
                                      Teacher).all(), teachers=Teacher.query.all(), subjects=Subject.query.all())


# --- Attendance & Leaves ---

@app.route('/attendance/mark', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def mark_attendance():
    if request.method == 'POST':
        data = request.get_json()
        dt = datetime.strptime(data['date'], '%Y-%m-%d').date()
        Attendance.query.filter_by(subject_id=data['subject_id'], date=dt, session_type=data['session_type'],
                                   period=data['period']).delete()
        for i in data['attendance']:
            db.session.add(Attendance(student_id=i['student_id'], subject_id=data['subject_id'],
                                      teacher_id=Teacher.query.filter_by(user_id=session['user_id']).first().id,
                                      date=dt, session_type=data['session_type'], period=data['period'],
                                      status=i['status'], remarks=i['remarks']))
        db.session.commit()
        return jsonify({'message': 'Attendance Marked'})
    teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
    ts = db.session.query(TeacherSubject, Subject).join(Subject).filter(TeacherSubject.teacher_id == teacher.id).all()
    return render_template_string(MARK_ATTENDANCE, teacher_subjects=ts, today=datetime.now().strftime('%Y-%m-%d'))


@app.route('/attendance/students/<int:sid>/<batch>/<division>')
def get_students_api(sid, batch, division):
    students = Student.query.filter_by(batch=batch, division=division).all()
    return jsonify([{'id': s.id, 'roll_number': s.roll_number, 'name': s.name} for s in students])


@app.route('/attendance/view')
@login_required
def view_attendance():
    if session['role'] == 'student':
        student = Student.query.filter_by(user_id=session['user_id']).first()
        att = db.session.query(Attendance, Subject, Teacher).join(Subject).join(Teacher).filter(
            Attendance.student_id == student.id).all()
        return render_template_string(VIEW_ATTENDANCE, attendance=att)
    teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
    att = db.session.query(Attendance, Subject, Student).join(Subject).join(Student).filter(
        Attendance.teacher_id == teacher.id).order_by(Attendance.date.desc()).limit(100).all()
    return render_template_string(VIEW_ATTENDANCE, attendance=att)


@app.route('/leave/manage')
@login_required
def manage_leaves():
    if session['role'] == 'student': return render_template_string(APPLY_LEAVE)
    leaves = db.session.query(LeaveRequest, Student).join(Student).all()
    return render_template_string(LEAVES_PAGE, leaves=leaves)


@app.route('/leave/apply', methods=['POST'])
@login_required
def apply_leave():
    student = Student.query.filter_by(user_id=session['user_id']).first()
    db.session.add(
        LeaveRequest(student_id=student.id, from_date=datetime.strptime(request.form['from_date'], '%Y-%m-%d').date(),
                     to_date=datetime.strptime(request.form['to_date'], '%Y-%m-%d').date(),
                     leave_type=request.form['leave_type'], reason=request.form['reason']))
    db.session.commit()
    flash('Leave Applied', 'success')
    return redirect(url_for('dashboard'))


@app.route('/leave/approve/<int:leave_id>')
@login_required
def approve_leave(leave_id):
    l = LeaveRequest.query.get(leave_id)
    l.status = 'approved'
    # Auto-mark OD
    curr = l.from_date
    while curr <= l.to_date:
        # In a real system, you'd query schedule and mark OD for all subjects that day
        curr += timedelta(days=1)
    db.session.commit()
    return redirect(url_for('manage_leaves'))


# --- Reports ---

@app.route('/reports')
def reports_page(): return render_template_string(REPORTS_PAGE)


@app.route('/reports/student')
def student_wise_report():
    data = [{'student': s, 'percentage': calculate_attendance_percentage(s.id)} for s in Student.query.all()]
    return render_template_string(STUDENT_REPORT, report_data=data)


@app.route('/reports/defaulters')
def defaulters_report():
    return render_template_string(STUDENT_REPORT, report_data=get_defaulter_students(75))


# ==================== INIT ====================

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(
                User(username='admin', email='admin@edu', password=generate_password_hash('admin123'), role='admin'))
            db.session.commit()
            print(">>> Admin Created: admin / admin123")


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)