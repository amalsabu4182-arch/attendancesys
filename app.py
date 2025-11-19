import os
import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# CONFIGURATION
# ==========================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'university-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///university_attendance_v2.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==========================================
# DATABASE MODELS
# ==========================================

# M:M Relationship: Teachers <-> Subjects
teacher_subjects = db.Table('teacher_subjects',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subject.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'hod', 'teacher', 'student'
    
    # For Students: Which Course (Batch) they belong to
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)

    # Relationships
    assigned_subjects = db.relationship('Subject', secondary=teacher_subjects, backref=db.backref('teachers', lazy=True))
    attendances = db.relationship('Attendance', backref='student', foreign_keys='Attendance.student_id', lazy=True)

class Course(db.Model):
    """Represents a Batch/Class, e.g., 'B.Tech Year 1 Sem 1'"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    semester = db.Column(db.Integer, nullable=False)

    # Relationships
    subjects = db.relationship('Subject', backref='course', cascade="all, delete-orphan", lazy=True)
    students = db.relationship('User', backref='course_batch', lazy=True)

class Subject(db.Model):
    """Represents a specific topic taught in a Course, e.g., 'Data Structures'"""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)

    # Relationships
    attendances = db.relationship('Attendance', backref='subject', cascade="all, delete-orphan", lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'Present', 'Absent'
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    marked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# ==========================================
# HELPERS & SEEDING
# ==========================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def seed_database():
    if User.query.first(): return

    pw = generate_password_hash('password')
    
    # 1. Create HOD
    hod = User(username='hod', password_hash=pw, role='hod', full_name='Dr. Head of Dept')
    db.session.add(hod)
    
    # 2. Create Teachers
    t1 = User(username='teacher1', password_hash=pw, role='teacher', full_name='Prof. Smith')
    t2 = User(username='teacher2', password_hash=pw, role='teacher', full_name='Prof. Jones')
    db.session.add_all([t1, t2])
    db.session.commit()

    # 3. Create Course (Batch)
    c1 = Course(name="B.Tech CS", year=1, semester=1)
    db.session.add(c1)
    db.session.commit()

    # 4. Create Subjects
    sub1 = Subject(code='CS101', name='Intro to Python', course_id=c1.id)
    sub2 = Subject(code='CS102', name='Calculus I', course_id=c1.id)
    db.session.add_all([sub1, sub2])
    db.session.commit()

    # 5. Assign Teachers to Subjects (Multi-to-Multi)
    t1.assigned_subjects.append(sub1) # Smith teaches Python
    t2.assigned_subjects.append(sub2) # Jones teaches Calculus
    # Example: Smith also helps with Calculus (Multi assign)
    t1.assigned_subjects.append(sub2) 
    db.session.commit()

    # 6. Create Students assigned to Course
    s1 = User(username='student1', password_hash=pw, role='student', full_name='Alice Student', course_id=c1.id)
    s2 = User(username='student2', password_hash=pw, role='student', full_name='Bob Learner', course_id=c1.id)
    db.session.add_all([s1, s2])
    db.session.commit()
    
    print("Database seeded successfully.")

# ==========================================
# ROUTES
# ==========================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template_string(HTML_LAYOUT, content=HTML_LOGIN)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'hod':
        return hod_dashboard()
    elif current_user.role == 'teacher':
        return teacher_dashboard()
    elif current_user.role == 'student':
        return student_dashboard()
    return "Role Error", 403

# ---------------------------------------------------------
# HOD LOGIC
# ---------------------------------------------------------
def hod_dashboard():
    teachers = User.query.filter_by(role='teacher').all()
    courses = Course.query.all()
    subjects = Subject.query.all()
    return render_template_string(HTML_LAYOUT, content=HTML_HOD_DASH, 
                                  teachers=teachers, courses=courses, subjects=subjects)

@app.route('/hod/manage/<type>/<action>', methods=['POST'])
@login_required
def hod_manage(type, action):
    if current_user.role != 'hod': abort(403)

    if type == 'teacher':
        if action == 'add':
            u = request.form['username']
            p = generate_password_hash(request.form['password'])
            fn = request.form['fullname']
            new_user = User(username=u, password_hash=p, full_name=fn, role='teacher')
            db.session.add(new_user)
            flash('Teacher added.', 'success')
        elif action == 'delete':
            uid = request.form['user_id']
            User.query.filter_by(id=uid).delete()
            flash('Teacher deleted.', 'warning')
        elif action == 'assign':
            uid = request.form['user_id']
            subject_ids = request.form.getlist('subject_ids')
            user = User.query.get(uid)
            user.assigned_subjects = [] # Clear old
            for sid in subject_ids:
                s = Subject.query.get(sid)
                user.assigned_subjects.append(s)
            flash('Subjects assigned.', 'success')

    elif type == 'course':
        if action == 'add':
            c = Course(name=request.form['name'], year=request.form['year'], semester=request.form['semester'])
            db.session.add(c)
            flash('Course added.', 'success')
        elif action == 'delete':
            Course.query.filter_by(id=request.form['course_id']).delete()
            flash('Course deleted.', 'warning')

    elif type == 'subject':
        if action == 'add':
            s = Subject(name=request.form['name'], code=request.form['code'], course_id=request.form['course_id'])
            db.session.add(s)
            flash('Subject added.', 'success')
        elif action == 'delete':
            Subject.query.filter_by(id=request.form['subject_id']).delete()
            flash('Subject deleted.', 'warning')

    db.session.commit()
    return redirect(url_for('dashboard'))

# ---------------------------------------------------------
# TEACHER LOGIC
# ---------------------------------------------------------
def teacher_dashboard():
    # Teachers see their subjects and can manage students
    subjects = current_user.assigned_subjects
    students = User.query.filter_by(role='student').all() # Global student list for management
    courses = Course.query.all() # For assigning students to courses
    return render_template_string(HTML_LAYOUT, content=HTML_TEACHER_DASH, 
                                  subjects=subjects, students=students, courses=courses)

@app.route('/teacher/student/<action>', methods=['POST'])
@login_required
def teacher_manage_student(action):
    if current_user.role not in ['teacher', 'hod']: abort(403)

    if action == 'add':
        u = request.form['username']
        p = generate_password_hash(request.form['password'])
        fn = request.form['fullname']
        cid = request.form['course_id']
        new_s = User(username=u, password_hash=p, full_name=fn, role='student', course_id=cid)
        db.session.add(new_s)
        flash('Student added.', 'success')
    elif action == 'delete':
        User.query.filter_by(id=request.form['user_id']).delete()
        flash('Student deleted.', 'warning')
    elif action == 'edit':
        s = User.query.get(request.form['user_id'])
        s.full_name = request.form['fullname']
        s.course_id = request.form['course_id']
        if request.form['password']:
            s.password_hash = generate_password_hash(request.form['password'])
        flash('Student updated.', 'success')
    
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/mark/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def mark_attendance(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    # Security: Check if teacher is assigned to this subject (or is HOD)
    if current_user.role != 'hod' and subject not in current_user.assigned_subjects:
        abort(403)

    # Get students belonging to the Course of this Subject
    students = subject.course.students

    if request.method == 'POST':
        date = datetime.datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        for student in students:
            status_key = f'status_{student.id}'
            status = request.form.get(status_key)
            if status:
                # Update or Create
                att = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id, date=date).first()
                if not att:
                    att = Attendance(student_id=student.id, subject_id=subject.id, date=date, marked_by=current_user.id, status=status)
                    db.session.add(att)
                else:
                    att.status = status
                    att.marked_by = current_user.id
        db.session.commit()
        flash('Attendance saved.', 'success')
        return redirect(url_for('dashboard'))

    today = datetime.date.today().strftime('%Y-%m-%d')
    return render_template_string(HTML_LAYOUT, content=HTML_MARK_ATTENDANCE, subject=subject, students=students, today=today)

# ---------------------------------------------------------
# STUDENT LOGIC
# ---------------------------------------------------------
def student_dashboard():
    # Show attendance per subject in their course
    if not current_user.course_batch:
        return render_template_string(HTML_LAYOUT, content="<div class='alert alert-info'>You are not assigned to a course yet.</div>")
    
    subjects = current_user.course_batch.subjects
    report = []
    
    for sub in subjects:
        total_classes = Attendance.query.filter_by(subject_id=sub.id).with_entities(Attendance.date).distinct().count()
        my_present = Attendance.query.filter_by(student_id=current_user.id, subject_id=sub.id, status='Present').count()
        
        perc = (my_present / total_classes * 100) if total_classes > 0 else 0
        report.append({
            'subject': sub.name,
            'code': sub.code,
            'total': total_classes,
            'present': my_present,
            'percentage': round(perc, 1),
            'color': 'success' if perc >= 75 else 'warning' if perc >= 60 else 'danger'
        })

    return render_template_string(HTML_LAYOUT, content=HTML_STUDENT_DASH, report=report, course=current_user.course_batch)

# ==========================================
# TEMPLATES
# ==========================================

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UniManager</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; }
        .sidebar { min-height: 100vh; background: #343a40; color: #ecf0f1; }
        .sidebar a { color: #adb5bd; text-decoration: none; display: block; padding: 12px; border-radius: 4px; }
        .sidebar a:hover { background: #495057; color: white; }
        .card { border: none; box-shadow: 0 0 10px rgba(0,0,0,0.05); }
        .btn-icon { width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
    </style>
</head>
<body>
    <div class="d-flex">
        {% if current_user.is_authenticated %}
        <div class="sidebar p-3 d-flex flex-column" style="width: 260px; flex-shrink: 0;">
            <h4 class="mb-4 text-white"><i class="fas fa-graduation-cap"></i> UniManager</h4>
            <div class="mb-4 pb-3 border-bottom border-secondary">
                <small class="text-muted d-block">Logged in as</small>
                <strong class="text-white">{{ current_user.full_name }}</strong>
                <span class="badge bg-info text-dark mt-1 d-inline-block">{{ current_user.role|upper }}</span>
            </div>
            <a href="{{ url_for('dashboard') }}" class="mb-2"><i class="fas fa-home me-2"></i> Dashboard</a>
            <a href="{{ url_for('logout') }}" class="mt-auto text-danger"><i class="fas fa-sign-out-alt me-2"></i> Logout</a>
        </div>
        {% endif %}
        <div class="flex-grow-1 p-4" style="overflow-y: auto; height: 100vh;">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }} alert-dismissible fade show">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            {{ content|safe }}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

HTML_LOGIN = """
<div class="container mt-5" style="max-width: 400px;">
    <div class="card">
        <div class="card-body p-4">
            <h3 class="text-center mb-4">Login</h3>
            <form method="POST">
                <div class="mb-3"><label>Username</label><input type="text" name="username" class="form-control" required></div>
                <div class="mb-3"><label>Password</label><input type="password" name="password" class="form-control" required></div>
                <button class="btn btn-primary w-100">Sign In</button>
            </form>
            <div class="mt-3 small text-muted text-center">
                Defaults: hod/password, teacher1/password, student1/password
            </div>
        </div>
    </div>
</div>
"""

HTML_HOD_DASH = """
<h2>HOD Dashboard</h2>
<hr>

<!-- TEACHERS SECTION -->
<div class="card mb-4">
    <div class="card-header bg-white d-flex justify-content-between align-items-center">
        <h5 class="mb-0">Manage Teachers</h5>
        <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#addTeacherModal"><i class="fas fa-plus"></i> Add Teacher</button>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table align-middle">
                <thead><tr><th>Name</th><th>Username</th><th>Assigned Subjects</th><th>Action</th></tr></thead>
                <tbody>
                {% for t in teachers %}
                <tr>
                    <td>{{ t.full_name }}</td>
                    <td>{{ t.username }}</td>
                    <td>
                        {% for s in t.assigned_subjects %}
                            <span class="badge bg-secondary">{{ s.code }}</span>
                        {% else %} <span class="text-muted small">None</span> {% endfor %}
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-info" data-bs-toggle="modal" data-bs-target="#assignModal{{t.id}}">Assign</button>
                        <form method="POST" action="{{ url_for('hod_manage', type='teacher', action='delete') }}" class="d-inline" onsubmit="return confirm('Delete?');">
                            <input type="hidden" name="user_id" value="{{t.id}}">
                            <button class="btn btn-sm btn-outline-danger"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                
                <!-- Assign Modal -->
                <div class="modal fade" id="assignModal{{t.id}}">
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <form method="POST" action="{{ url_for('hod_manage', type='teacher', action='assign') }}">
                                <div class="modal-header"><h5 class="modal-title">Assign Subjects to {{ t.full_name }}</h5></div>
                                <div class="modal-body">
                                    <input type="hidden" name="user_id" value="{{t.id}}">
                                    <label class="form-label">Select Subjects (Multi-select)</label>
                                    <select name="subject_ids" class="form-select" multiple size="5">
                                        {% for s in subjects %}
                                            <option value="{{s.id}}" {% if s in t.assigned_subjects %}selected{% endif %}>{{ s.code }} - {{ s.name }} ({{ s.course.name }})</option>
                                        {% endfor %}
                                    </select>
                                    <small class="text-muted">Hold Ctrl/Cmd to select multiple.</small>
                                </div>
                                <div class="modal-footer"><button class="btn btn-primary">Save Assignments</button></div>
                            </form>
                        </div>
                    </div>
                </div>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- COURSES SECTION -->
<div class="row">
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-white d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Courses (Batches)</h5>
                <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#addCourseModal"><i class="fas fa-plus"></i> Add</button>
            </div>
            <ul class="list-group list-group-flush">
                {% for c in courses %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div><strong>{{ c.name }}</strong> <br><small class="text-muted">Year {{ c.year }} | Sem {{ c.semester }}</small></div>
                    <form method="POST" action="{{ url_for('hod_manage', type='course', action='delete') }}" onsubmit="return confirm('Delete?');">
                        <input type="hidden" name="course_id" value="{{c.id}}">
                        <button class="btn btn-sm btn-link text-danger"><i class="fas fa-trash"></i></button>
                    </form>
                </li>
                {% endfor %}
            </ul>
        </div>
    </div>
    
    <!-- SUBJECTS SECTION -->
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-white d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Subjects</h5>
                <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#addSubjectModal"><i class="fas fa-plus"></i> Add</button>
            </div>
            <ul class="list-group list-group-flush">
                {% for s in subjects %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{{ s.code }}</strong>: {{ s.name }}
                        <br><small class="text-muted">Batch: {{ s.course.name }}</small>
                    </div>
                    <form method="POST" action="{{ url_for('hod_manage', type='subject', action='delete') }}" onsubmit="return confirm('Delete?');">
                        <input type="hidden" name="subject_id" value="{{s.id}}">
                        <button class="btn btn-sm btn-link text-danger"><i class="fas fa-trash"></i></button>
                    </form>
                </li>
                {% endfor %}
            </ul>
        </div>
    </div>
</div>

<!-- MODALS -->
<div class="modal fade" id="addTeacherModal">
    <div class="modal-dialog">
        <form class="modal-content" method="POST" action="{{ url_for('hod_manage', type='teacher', action='add') }}">
            <div class="modal-header"><h5 class="modal-title">Add Teacher</h5></div>
            <div class="modal-body">
                <input type="text" name="fullname" class="form-control mb-2" placeholder="Full Name" required>
                <input type="text" name="username" class="form-control mb-2" placeholder="Username" required>
                <input type="password" name="password" class="form-control mb-2" placeholder="Password" required>
            </div>
            <div class="modal-footer"><button class="btn btn-primary">Create</button></div>
        </form>
    </div>
</div>

<div class="modal fade" id="addCourseModal">
    <div class="modal-dialog">
        <form class="modal-content" method="POST" action="{{ url_for('hod_manage', type='course', action='add') }}">
            <div class="modal-header"><h5 class="modal-title">Add Course (Batch)</h5></div>
            <div class="modal-body">
                <input type="text" name="name" class="form-control mb-2" placeholder="Name (e.g. B.Tech CS)" required>
                <div class="row">
                    <div class="col"><input type="number" name="year" class="form-control" placeholder="Year" required></div>
                    <div class="col"><input type="number" name="semester" class="form-control" placeholder="Sem" required></div>
                </div>
            </div>
            <div class="modal-footer"><button class="btn btn-primary">Create</button></div>
        </form>
    </div>
</div>

<div class="modal fade" id="addSubjectModal">
    <div class="modal-dialog">
        <form class="modal-content" method="POST" action="{{ url_for('hod_manage', type='subject', action='add') }}">
            <div class="modal-header"><h5 class="modal-title">Add Subject</h5></div>
            <div class="modal-body">
                <input type="text" name="code" class="form-control mb-2" placeholder="Subject Code (e.g. CS101)" required>
                <input type="text" name="name" class="form-control mb-2" placeholder="Subject Name" required>
                <label>Assign to Batch:</label>
                <select name="course_id" class="form-select">
                    {% for c in courses %}
                    <option value="{{c.id}}">{{c.name}} (Yr {{c.year}} Sem {{c.semester}})</option>
                    {% endfor %}
                </select>
            </div>
            <div class="modal-footer"><button class="btn btn-primary">Create</button></div>
        </form>
    </div>
</div>
"""

HTML_TEACHER_DASH = """
<h2>Teacher Dashboard</h2>
<hr>

<div class="row">
    <div class="col-md-6">
        <div class="card mb-4 shadow-sm">
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0">My Assigned Subjects</h5>
            </div>
            <div class="list-group list-group-flush">
                {% for sub in subjects %}
                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-0">{{ sub.code }} - {{ sub.name }}</h6>
                        <small class="text-muted">Batch: {{ sub.course.name }}</small>
                    </div>
                    <a href="{{ url_for('mark_attendance', subject_id=sub.id) }}" class="btn btn-sm btn-success">Mark Attendance</a>
                </div>
                {% else %}
                <div class="list-group-item">No subjects assigned yet.</div>
                {% endfor %}
            </div>
        </div>
    </div>

    <div class="col-md-6">
        <div class="card shadow-sm">
            <div class="card-header bg-white d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Manage Students</h5>
                <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#addStudentModal"><i class="fas fa-plus"></i> Add Student</button>
            </div>
            <div class="card-body p-0" style="max-height: 400px; overflow-y:auto;">
                <table class="table table-hover mb-0">
                    <thead class="table-light"><tr><th>Name</th><th>Batch</th><th>Action</th></tr></thead>
                    <tbody>
                    {% for s in students %}
                    <tr>
                        <td>{{ s.full_name }}<br><small class="text-muted">{{ s.username }}</small></td>
                        <td><span class="badge bg-light text-dark">{{ s.course_batch.name if s.course_batch else 'Unassigned' }}</span></td>
                        <td>
                            <button class="btn btn-sm btn-light" data-bs-toggle="modal" data-bs-target="#editStudent{{s.id}}"><i class="fas fa-edit"></i></button>
                            <form method="POST" action="{{ url_for('teacher_manage_student', action='delete') }}" class="d-inline" onsubmit="return confirm('Delete?');">
                                <input type="hidden" name="user_id" value="{{s.id}}">
                                <button class="btn btn-sm btn-light text-danger"><i class="fas fa-trash"></i></button>
                            </form>
                        </td>
                    </tr>
                    <!-- Edit Modal -->
                    <div class="modal fade" id="editStudent{{s.id}}">
                        <div class="modal-dialog">
                            <form class="modal-content" method="POST" action="{{ url_for('teacher_manage_student', action='edit') }}">
                                <div class="modal-header"><h5 class="modal-title">Edit Student</h5></div>
                                <div class="modal-body">
                                    <input type="hidden" name="user_id" value="{{s.id}}">
                                    <label>Full Name</label>
                                    <input type="text" name="fullname" class="form-control mb-2" value="{{s.full_name}}" required>
                                    <label>Batch</label>
                                    <select name="course_id" class="form-select mb-2">
                                        {% for c in courses %}
                                        <option value="{{c.id}}" {% if s.course_id == c.id %}selected{% endif %}>{{c.name}}</option>
                                        {% endfor %}
                                    </select>
                                    <label>Reset Password (Optional)</label>
                                    <input type="password" name="password" class="form-control" placeholder="Leave empty to keep current">
                                </div>
                                <div class="modal-footer"><button class="btn btn-primary">Save</button></div>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<div class="modal fade" id="addStudentModal">
    <div class="modal-dialog">
        <form class="modal-content" method="POST" action="{{ url_for('teacher_manage_student', action='add') }}">
            <div class="modal-header"><h5 class="modal-title">Add Student</h5></div>
            <div class="modal-body">
                <input type="text" name="fullname" class="form-control mb-2" placeholder="Full Name" required>
                <input type="text" name="username" class="form-control mb-2" placeholder="Username" required>
                <input type="password" name="password" class="form-control mb-2" placeholder="Password" required>
                <label>Assign to Batch:</label>
                <select name="course_id" class="form-select">
                    {% for c in courses %}
                    <option value="{{c.id}}">{{c.name}}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="modal-footer"><button class="btn btn-primary">Add Student</button></div>
        </form>
    </div>
</div>
"""

HTML_MARK_ATTENDANCE = """
<div class="d-flex justify-content-between align-items-center mb-4">
    <div>
        <h2>{{ subject.name }} <span class="text-muted">({{ subject.code }})</span></h2>
        <p class="text-muted mb-0">Batch: {{ subject.course.name }}</p>
    </div>
    <a href="{{ url_for('dashboard') }}" class="btn btn-outline-secondary">Back</a>
</div>

<div class="card shadow">
    <div class="card-body">
        <form method="POST">
            <div class="row mb-4 align-items-end">
                <div class="col-md-4">
                    <label class="form-label fw-bold">Attendance Date</label>
                    <input type="date" name="date" class="form-control" value="{{ today }}" required>
                </div>
                <div class="col-md-8 text-end">
                    <button type="button" class="btn btn-outline-success btn-sm" onclick="markAll('Present')">All Present</button>
                    <button type="button" class="btn btn-outline-danger btn-sm" onclick="markAll('Absent')">All Absent</button>
                </div>
            </div>

            <div class="table-responsive">
                <table class="table table-striped align-middle">
                    <thead>
                        <tr><th>Student Name</th><th width="300">Status</th></tr>
                    </thead>
                    <tbody>
                        {% for s in students %}
                        <tr>
                            <td>{{ s.full_name }}</td>
                            <td>
                                <div class="btn-group w-100" role="group">
                                    <input type="radio" class="btn-check" name="status_{{s.id}}" id="p_{{s.id}}" value="Present" checked>
                                    <label class="btn btn-outline-success" for="p_{{s.id}}">Present</label>

                                    <input type="radio" class="btn-check" name="status_{{s.id}}" id="a_{{s.id}}" value="Absent">
                                    <label class="btn btn-outline-danger" for="a_{{s.id}}">Absent</label>
                                </div>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="2" class="text-center text-muted">No students in this batch.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="d-grid mt-3">
                <button class="btn btn-primary btn-lg">Save Attendance Record</button>
            </div>
        </form>
    </div>
</div>

<script>
function markAll(status) {
    const radios = document.querySelectorAll('input[type="radio"][value="' + status + '"]');
    radios.forEach(r => r.checked = true);
}
</script>
"""

HTML_STUDENT_DASH = """
<h2 class="mb-4">My Attendance Report</h2>
<div class="card mb-4">
    <div class="card-body">
        <h5 class="card-title">Batch: {{ course.name }}</h5>
        <p class="card-text">Year {{ course.year }}, Semester {{ course.semester }}</p>
    </div>
</div>

<div class="row">
    {% for r in report %}
    <div class="col-md-4 mb-4">
        <div class="card h-100 border-{{ r.color }}">
            <div class="card-body text-center">
                <h3 class="display-4 text-{{ r.color }}">{{ r.percentage }}%</h3>
                <h5 class="card-title">{{ r.subject }}</h5>
                <p class="text-muted mb-1">{{ r.code }}</p>
                <hr>
                <div class="d-flex justify-content-between small text-muted">
                    <span>Present: {{ r.present }}</span>
                    <span>Total: {{ r.total }}</span>
                </div>
            </div>
            <div class="card-footer bg-{{ r.color }} text-white text-center py-1">
                <small>{{ 'Good Standing' if r.percentage >= 75 else 'Warning' if r.percentage >= 60 else 'Critical' }}</small>
            </div>
        </div>
    </div>
    {% else %}
    <div class="col-12"><p class="text-muted">No attendance records found.</p></div>
    {% endfor %}
</div>
"""

# ==========================================
# MAIN
# ==========================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True, port=5001)
