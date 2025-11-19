# app.py
import os
import secrets
import csv
import io
from datetime import datetime, timedelta, date
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func, case

# ================= CONFIGURATION =================
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-prod-12345')
    
    # Database Logic: Auto-switch between Render (Postgres) and Local (SQLite)
    uri = os.environ.get('DATABASE_URL')
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = uri or 'sqlite:///college_attendance.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)

# ================= MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))
    semester = db.Column(db.Integer)

class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    name = db.Column(db.String(100), nullable=False)
    teacher_type = db.Column(db.String(20))

class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'))
    semester = db.Column(db.Integer)
    subject_type = db.Column(db.String(20))

class TeacherSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    batch = db.Column(db.String(20))
    division = db.Column(db.String(10))

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'))
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20))
    remarks = db.Column(db.String(200))
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')

# ================= DECORATORS =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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

# ================= ROUTES =================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username')).first()
        if u and check_password_hash(u.password, request.form.get('password')):
            session['user_id'] = u.id
            session['role'] = u.role
            session['name'] = u.username
            session.permanent = True
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'danger')
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
        counts = {
            'students': Student.query.count(),
            'teachers': Teacher.query.count(),
            'programs': Program.query.count()
        }
        return render_template_string(ADMIN_DASHBOARD, counts=counts)
    elif role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
        allocations = db.session.query(TeacherSubject, Subject).join(Subject).filter(TeacherSubject.teacher_id == teacher.id).all()
        leaves = db.session.query(LeaveRequest, Student).join(Student).filter(LeaveRequest.status == 'pending').all()
        return render_template_string(TEACHER_DASHBOARD, allocations=allocations, leaves=leaves, today=date.today())
    elif role == 'student':
        student = Student.query.filter_by(user_id=session['user_id']).first()
        # Stats
        total = Attendance.query.filter_by(student_id=student.id).count()
        present = Attendance.query.filter_by(student_id=student.id, status='Present').count()
        perc = round((present/total*100), 2) if total > 0 else 0
        # Recent
        recent = db.session.query(Attendance, Subject).join(Subject).filter(Attendance.student_id == student.id).order_by(Attendance.date.desc()).limit(10).all()
        return render_template_string(STUDENT_DASHBOARD, student=student, perc=perc, recent=recent)
    return "Role Error"

# --- ADMIN ROUTES ---
@app.route('/admin/setup', methods=['GET', 'POST'])
@role_required('admin')
def admin_setup():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_program':
            db.session.add(Program(name=request.form['name'], code=request.form['code']))
            flash('Program Added', 'success')
            
        elif action == 'add_subject':
            db.session.add(Subject(
                name=request.form['name'], 
                code=request.form['code'],
                subject_type=request.form['type'],
                semester=request.form['semester'],
                program_id=request.form['program_id']
            ))
            flash('Subject Added', 'success')
            
        elif action == 'add_user':
            try:
                # Create User Login
                hashed = generate_password_hash('college123')
                u = User(username=request.form['username'], password=hashed, role=request.form['role'])
                db.session.add(u)
                db.session.flush()
                
                if request.form['role'] == 'student':
                    s = Student(user_id=u.id, name=request.form['name'], roll_number=request.form['roll_number'],
                                program_id=request.form['program_id'], batch=request.form['batch'],
                                division=request.form['division'], semester=request.form['semester'])
                    db.session.add(s)
                elif request.form['role'] == 'teacher':
                    t = Teacher(user_id=u.id, name=request.form['name'], teacher_type='Major')
                    db.session.add(t)
                flash('User Created', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error: {str(e)}', 'danger')

        elif action == 'assign_teacher':
            ts = TeacherSubject(teacher_id=request.form['teacher_id'], subject_id=request.form['subject_id'],
                                batch=request.form['batch'], division=request.form['division'])
            db.session.add(ts)
            flash('Subject Assigned', 'success')

        db.session.commit()
        return redirect(url_for('admin_setup'))

    programs = Program.query.all()
    subjects = Subject.query.all()
    teachers = Teacher.query.all()
    return render_template_string(ADMIN_SETUP, programs=programs, subjects=subjects, teachers=teachers)

@app.route('/admin/bulk_upload', methods=['POST'])
@role_required('admin')
def bulk_upload():
    if 'file' not in request.files: return redirect(url_for('admin_setup'))
    file = request.files['file']
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_reader = csv.DictReader(stream)
    count = 0
    for row in csv_reader:
        try:
            if User.query.filter_by(username=row['username']).first(): continue
            u = User(username=row['username'], password=generate_password_hash('college123'), role='student')
            db.session.add(u)
            db.session.flush()
            s = Student(user_id=u.id, name=row['name'], roll_number=row['roll_number'],
                        program_id=row['program_id'], batch=row['batch'], division=row['division'], semester=row['semester'])
            db.session.add(s)
            count += 1
        except: db.session.rollback()
    db.session.commit()
    flash(f'Uploaded {count} students', 'success')
    return redirect(url_for('admin_setup'))

# --- TEACHER ROUTES ---
@app.route('/teacher/fetch_students/<int:subject_id>/<batch>/<division>')
@role_required('teacher')
def fetch_students(subject_id, batch, division):
    students = Student.query.filter_by(batch=batch, division=division).order_by(Student.roll_number).all()
    return jsonify([{'id': s.id, 'roll': s.roll_number, 'name': s.name} for s in students])

@app.route('/teacher/submit_attendance', methods=['POST'])
@role_required('teacher')
def submit_attendance():
    data = request.json
    teacher = Teacher.query.filter_by(user_id=session['user_id']).first()
    date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
    
    # Clear existing for this day/subject to prevent dupes
    Attendance.query.filter_by(subject_id=data['subject_id'], date=date_obj).delete()
    
    for entry in data['records']:
        a = Attendance(
            student_id=entry['student_id'],
            subject_id=data['subject_id'],
            teacher_id=teacher.id,
            date=date_obj,
            status=entry['status']
        )
        db.session.add(a)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Attendance Saved'})

@app.route('/teacher/leave/<action>/<int:leave_id>')
@role_required('teacher')
def handle_leave(action, leave_id):
    req = LeaveRequest.query.get(leave_id)
    req.status = 'approved' if action == 'approve' else 'rejected'
    db.session.commit()
    flash(f'Leave {req.status}', 'info')
    return redirect(url_for('dashboard'))

# --- STUDENT ROUTES ---
@app.route('/student/apply_leave', methods=['POST'])
@role_required('student')
def apply_leave():
    student = Student.query.filter_by(user_id=session['user_id']).first()
    lr = LeaveRequest(
        student_id=student.id,
        from_date=datetime.strptime(request.form['from_date'], '%Y-%m-%d').date(),
        to_date=datetime.strptime(request.form['to_date'], '%Y-%m-%d').date(),
        reason=request.form['reason']
    )
    db.session.add(lr)
    db.session.commit()
    flash('Leave Applied', 'success')
    return redirect(url_for('dashboard'))

# ================= TEMPLATES =================
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>College System</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --primary: #4f46e5; --bg: #f3f4f6; }
        body { font-family: system-ui, sans-serif; background: var(--bg); margin: 0; }
        .navbar { background: white; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,0.1); display: flex; justify-content: space-between; }
        .navbar a { text-decoration: none; color: #374151; margin-left: 15px; font-weight: 500; }
        .container { max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
        .card { background: white; padding: 1.5rem; border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 1.5rem; }
        .btn { background: var(--primary); color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; }
        .btn:hover { opacity: 0.9; }
        input, select { padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; width: 100%; margin-bottom: 10px; box-sizing: border-box;}
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #e5e7eb; }
        .alert { padding: 1rem; margin-bottom: 1rem; border-radius: 0.375rem; background: #fee2e2; color: #991b1b; }
        .alert-success { background: #d1fae5; color: #065f46; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
    </style>
</head>
<body>
    <div class="navbar">
        <div style="font-weight:bold; color:var(--primary)">🎓 CampusManager</div>
        <div>
            {% if session.user_id %}
                <a href="{{ url_for('dashboard') }}">Dashboard</a>
                <a href="{{ url_for('logout') }}">Logout</a>
            {% endif %}
        </div>
    </div>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}{% for cat, msg in messages %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}{% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<div style="max-width:400px; margin:3rem auto;">
    <div class="card">
        <h2 style="text-align:center">Login</h2>
        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <label>Username</label>
            <input name="username" required>
            <label>Password</label>
            <input type="password" name="password" required>
            <button class="btn" style="width:100%">Sign In</button>
        </form>
        <p style="text-align:center; font-size:0.8rem; color:grey; margin-top:1rem">Default: admin / admin123</p>
    </div>
</div>
{% endblock %}
''')

ADMIN_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Admin Dashboard</h2>
<div class="grid">
    <div class="card"><h3>{{ counts.students }}</h3><p>Students</p></div>
    <div class="card"><h3>{{ counts.teachers }}</h3><p>Teachers</p></div>
    <div class="card"><h3>{{ counts.programs }}</h3><p>Programs</p></div>
</div>
<div class="card">
    <h3>Quick Actions</h3>
    <a href="{{ url_for('admin_setup') }}" class="btn">⚙️ Go to Setup Manager</a>
</div>
{% endblock %}
''')

ADMIN_SETUP = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>System Setup</h2>
<div class="grid">
    <div class="card">
        <h3>Add Program</h3>
        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="action" value="add_program">
            <input name="name" placeholder="Name (e.g. Computer Science)" required>
            <input name="code" placeholder="Code (e.g. CS)" required>
            <button class="btn">Add Program</button>
        </form>
    </div>

    <div class="card">
        <h3>Add Subject</h3>
        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="action" value="add_subject">
            <input name="name" placeholder="Subject Name" required>
            <input name="code" placeholder="Subject Code" required>
            <select name="program_id">{% for p in programs %}<option value="{{p.id}}">{{p.code}}</option>{% endfor %}</select>
            <input name="semester" placeholder="Semester" type="number">
            <select name="type"><option>Core</option><option>Lab</option></select>
            <button class="btn">Add Subject</button>
        </form>
    </div>
</div>

<div class="card">
    <h3>Add User (Student/Teacher)</h3>
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="action" value="add_user">
        <div class="grid">
            <input name="username" placeholder="Username" required>
            <select name="role" id="roleSel" onchange="toggleFields()">
                <option value="student">Student</option>
                <option value="teacher">Teacher</option>
            </select>
            <input name="name" placeholder="Full Name" required>
        </div>
        <div id="studentFields" class="grid">
            <input name="roll_number" placeholder="Roll No">
            <select name="program_id">{% for p in programs %}<option value="{{p.id}}">{{p.code}}</option>{% endfor %}</select>
            <input name="batch" placeholder="Batch (e.g. 2024)">
            <input name="division" placeholder="Division (e.g. A)">
            <input name="semester" placeholder="Sem" type="number">
        </div>
        <button class="btn" style="margin-top:10px">Create User</button>
    </form>
</div>

<div class="card">
    <h3>Assign Subject to Teacher</h3>
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="action" value="assign_teacher">
        <div class="grid">
            <select name="teacher_id">{% for t in teachers %}<option value="{{t.id}}">{{t.name}}</option>{% endfor %}</select>
            <select name="subject_id">{% for s in subjects %}<option value="{{s.id}}">{{s.name}}</option>{% endfor %}</select>
            <input name="batch" placeholder="Batch">
            <input name="division" placeholder="Division">
        </div>
        <button class="btn">Assign</button>
    </form>
</div>

<div class="card">
    <h3>Bulk Upload Students (CSV)</h3>
    <form method="POST" action="{{ url_for('bulk_upload') }}" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="file" name="file" accept=".csv" required>
        <p style="font-size:0.8rem">Format: username,name,roll_number,program_id,batch,division,semester</p>
        <button class="btn">Upload CSV</button>
    </form>
</div>

<script>
function toggleFields() {
    const role = document.getElementById('roleSel').value;
    document.getElementById('studentFields').style.display = role === 'student' ? 'grid' : 'none';
}
</script>
{% endblock %}
''')

TEACHER_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Teacher Dashboard</h2>

<div class="card">
    <h3>📝 Mark Attendance</h3>
    <div class="grid">
        <select id="allocSelect">
            <option value="">Select Class...</option>
            {% for alloc, sub in allocations %}
            <option value="{{sub.id}}" data-batch="{{alloc.batch}}" data-div="{{alloc.division}}">
                {{sub.name}} ({{alloc.batch}} - {{alloc.division}})
            </option>
            {% endfor %}
        </select>
        <input type="date" id="attDate" value="{{ today }}">
        <button class="btn" onclick="loadStudents()">Load Students</button>
    </div>
    
    <div id="attendanceArea" style="display:none; margin-top:20px;">
        <table id="attTable">
            <thead><tr><th>Roll</th><th>Name</th><th>Status</th></tr></thead>
            <tbody></tbody>
        </table>
        <button class="btn" style="margin-top:15px; width:100%" onclick="submitAttendance()">💾 Save Attendance</button>
    </div>
</div>

<div class="card">
    <h3>Leave Requests</h3>
    {% if leaves %}
    <table>
        <tr><th>Student</th><th>Dates</th><th>Reason</th><th>Action</th></tr>
        {% for req, stud in leaves %}
        <tr>
            <td>{{stud.name}}</td>
            <td>{{req.from_date}} to {{req.to_date}}</td>
            <td>{{req.reason}}</td>
            <td>
                <a href="/teacher/leave/approve/{{req.id}}" style="color:green">Approve</a> | 
                <a href="/teacher/leave/reject/{{req.id}}" style="color:red">Reject</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}<p>No pending leaves.</p>{% endif %}
</div>

<script>
const csrfToken = "{{ csrf_token() }}"; // Get Token for JS

function loadStudents() {
    const sel = document.getElementById('allocSelect');
    const opt = sel.options[sel.selectedIndex];
    if (!opt.value) return alert('Select a class');
    
    const batch = opt.getAttribute('data-batch');
    const div = opt.getAttribute('data-div');
    
    fetch(`/teacher/fetch_students/${opt.value}/${batch}/${div}`)
        .then(r => r.json())
        .then(data => {
            const tbody = document.querySelector('#attTable tbody');
            tbody.innerHTML = '';
            data.forEach(s => {
                tbody.innerHTML += `
                    <tr data-sid="${s.id}">
                        <td>${s.roll}</td>
                        <td>${s.name}</td>
                        <td>
                            <select class="status-sel">
                                <option value="Present">Present</option>
                                <option value="Absent">Absent</option>
                                <option value="Late">Late</option>
                            </select>
                        </td>
                    </tr>`;
            });
            document.getElementById('attendanceArea').style.display = 'block';
        });
}

function submitAttendance() {
    const rows = document.querySelectorAll('#attTable tbody tr');
    const records = Array.from(rows).map(r => ({
        student_id: r.getAttribute('data-sid'),
        status: r.querySelector('.status-sel').value
    }));
    
    fetch('/teacher/submit_attendance', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken // Security Header
        },
        body: JSON.stringify({
            subject_id: document.getElementById('allocSelect').value,
            date: document.getElementById('attDate').value,
            records: records
        })
    }).then(r => r.json()).then(d => {
        alert(d.message);
        location.reload();
    });
}
</script>
{% endblock %}
''')

STUDENT_DASHBOARD = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Welcome, {{ student.name }}</h2>
<div class="grid">
    <div class="card">
        <h3>{{ perc }}%</h3>
        <p>Overall Attendance</p>
    </div>
    <div class="card">
        <h3>Apply for Leave</h3>
        <form method="POST" action="{{ url_for('apply_leave') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div class="grid">
                <input type="date" name="from_date" required>
                <input type="date" name="to_date" required>
            </div>
            <input name="reason" placeholder="Reason" required>
            <button class="btn">Apply</button>
        </form>
    </div>
</div>

<div class="card">
    <h3>Recent Attendance History</h3>
    <table>
        <tr><th>Date</th><th>Subject</th><th>Status</th></tr>
        {% for att, sub in recent %}
        <tr>
            <td>{{ att.date }}</td>
            <td>{{ sub.name }}</td>
            <td>
                <span style="color: {% if att.status=='Present' %}green{% else %}red{% endif %}">
                    {{ att.status }}
                </span>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
''')

# ================= INITIALIZATION =================
def init_db():
    with app.app_context():
        db.create_all()
        # Create Admin if not exists
        if not User.query.filter_by(username='admin').first():
            hashed = generate_password_hash('admin123')
            db.session.add(User(username='admin', password=hashed, role='admin'))
            db.session.commit()
            print(">>> DATABASE INITIALIZED. Admin: admin/admin123")

if __name__ == '__main__':
    init_db()
    # Running on Port 5001 as requested
    app.run(debug=True, port=5001)
