from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector, os
import requests
from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask import send_file
from flask import send_from_directory, abort #add this in mahira

BASE_DIR = os.path.dirname(os.path.abspath(__file__))#add this in mahira
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')#add this in mahira

#also change teacher upload material,student vievmateria and download material route

app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER #add this in mahira
UPLOAD_FOLDER = 'static/uploads/photos/'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

from config import db_config

def get_db_connection():
    return mysql.connector.connect(**db_config)

# from PyPDF2 import PdfReader
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.metrics.pairwise import cosine_similarity

# -------------- AI Notes & RAG config --------------
AI_NOTES_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'ai_notes')
os.makedirs(AI_NOTES_UPLOAD_FOLDER, exist_ok=True)

def save_chat_message(username, role, message):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO ai_chat_history (username, role, message) VALUES (%s, %s, %s)",
        (username, role, message),
    )
    con.commit()
    cur.close()
    con.close()

def get_chat_history(username, limit=50):
    con = get_db_connection()
    cur = con.cursor(dictionary=True)
    cur.execute(
        "SELECT role, message, created_at FROM ai_chat_history "
        "WHERE username = %s ORDER BY id DESC LIMIT %s",
        (username, limit),
    )
    rows = cur.fetchall()
    cur.close()
    con.close()
    # return oldest -> newest
    return list(reversed(rows))

def save_document(username, title, content):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO ai_documents (username, title, content) VALUES (%s, %s, %s)",
        (username, title, content),
    )
    con.commit()
    cur.close()
    con.close()

def load_user_documents(username):
    con = get_db_connection()
    cur = con.cursor(dictionary=True)
    cur.execute(
        "SELECT id, title, content FROM ai_documents "
        "WHERE username = %s OR username = 'global'",
        (username,),
    )
    docs = cur.fetchall()
    cur.close()
    con.close()
    return docs

def build_context_from_docs(question, docs, max_chunks=3):
    """
    Simple RAG:
    - Split docs into chunks
    - TF-IDF similarity with question
    - Pick top chunks as context
    """
    chunks = []
    for d in docs:
        text = d["content"] or ""
        title = d["title"]
        for i in range(0, len(text), 800):
            chunk_text = text[i:i+800]
            if chunk_text.strip():
                chunks.append({"title": title, "text": chunk_text})

    if not chunks:
        return ""

    corpus = [c["text"] for c in chunks] + [question]
    vectorizer = TfidfVectorizer().fit(corpus)
    vectors = vectorizer.transform(corpus)
    question_vec = vectors[-1]
    chunk_vecs = vectors[:-1]

    sims = cosine_similarity(question_vec, chunk_vecs)[0]
    scored = sorted(zip(chunks, sims), key=lambda x: x[1], reverse=True)[:max_chunks]

    selected = [f"From '{c['title']}':\n{c['text']}" for c, _ in scored]
    return "\n\n---\n\n".join(selected)

def extract_text_from_pdf(path):
    reader = PdfReader(path)
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n\n".join(texts)


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

ADMIN_USERNAME = "sharma"
ADMIN_PASSWORD = "12"

@app.route('/')
def home():
    return render_template("landing_school.html")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))

        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT password, role FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        con.close()

        if user and check_password_hash(user[0], password):
            session[user[1]] = username
            return redirect(url_for('teacher_dashboard' if user[1]=='teacher' else 'student_dashboard'))

        flash("Invalid credentials.")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    # Fetch messages
    cur.execute("SELECT * FROM messages ORDER BY id DESC")
    messages = cur.fetchall()

    # Fetch voting results
    cur.execute("SELECT id, title, option_text, votes FROM votes")
    votes = cur.fetchall()

    # Fetch teachers
    cur.execute("SELECT username FROM users WHERE role = 'teacher'")
    teachers = [r[0] for r in cur.fetchall()]

    # Fetch students
    cur.execute("SELECT username FROM users WHERE role = 'student'")
    students = cur.fetchall()

    # ✅ FETCH EVENTS (THIS WAS MISSING)
    cur.execute("""
        SELECT id, title, description, start_date, end_date, audience
        FROM events
        ORDER BY start_date DESC
    """)
    events = cur.fetchall()

    con.close()

    return render_template(
        'admin_dashboard.html',
        messages=messages,
        teachers=teachers,
        students=students,
        votes=votes,
        events=events   # ✅ FIXED
    )

@app.route('/admin/create-event', methods=['POST'])
def create_event():
    if not session.get('admin'):
        return redirect(url_for('login'))

    title = request.form['title']
    description = request.form['description']
    start_date = request.form['start_date']
    end_date = request.form.get('end_date')
    audience = request.form['audience']  # teacher | student | both

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO events (title, description, start_date, end_date, audience)
        VALUES (%s, %s, %s, %s, %s)
    """, (title, description, start_date, end_date, audience))

    con.commit()
    con.close()

    flash("✅ Event created successfully")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/register', methods=['POST'])
def admin_register():
    if not session.get('admin'):
        return redirect(url_for('login'))

    username = request.form['username']
    password = generate_password_hash(request.form['password'])
    role = request.form['role']
    standard = request.form.get('standard') if role == 'student' else None
    email = request.form['email']
    mobile = request.form['mobile']
    dob = request.form['dob']

    con = get_db_connection()
    cur = con.cursor()

    # Check duplicate username
    cur.execute("SELECT id FROM users WHERE username = %s", (username,))
    if cur.fetchone():
        flash("Username already exists.")
        con.close()
        return redirect(url_for('admin_dashboard'))

    # Insert user
    cur.execute(
    """
    INSERT INTO users (username, password, role, standard, email, mobile, dob)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """,
    (username, password, role, standard, email, mobile, dob)
)


    con.commit()
    con.close()

    flash("User registered successfully.")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/message', methods=['GET', 'POST'])
def admin_message():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        message = request.form.get('message')
        recipient = request.form.get('recipient')

        if not message or not recipient:
            flash("Message or recipient missing")
            return redirect(url_for('admin_message'))

        con = get_db_connection()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO messages (content, recipient) VALUES (%s, %s)",
            (message, recipient)
        )
        con.commit()
        con.close()

        flash("✅ Message sent successfully")
        return redirect(url_for('admin_dashboard'))

    # 👇 GET request → just show admin dashboard
    return redirect(url_for('admin_dashboard'))



@app.route('/admin/recent-messages')
def admin_recent_messages():
    if 'admin' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
        SELECT content, recipient
        FROM messages
        ORDER BY id DESC
    """)
    messages = cur.fetchall()
    con.close()

    return render_template(
        'admin_recent_messages.html',
        messages=messages
    )


@app.route('/admin/create-vote', methods=['GET', 'POST'])
def create_vote():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        options_raw = request.form['options'].strip()

        # Convert comma-separated options into list
        options = [opt.strip() for opt in options_raw.split(',') if opt.strip()]

        if not title or not options:
            flash("⚠️ Title and options are required.", "warning")
            return redirect(url_for('admin_dashboard'))

        con = get_db_connection()
        cur = con.cursor()

        # 🧹 Delete any old vote data with same title
        cur.execute("DELETE FROM student_votes WHERE vote_title = %s", (title,))
        cur.execute("DELETE FROM vote_options WHERE title = %s", (title,))
        cur.execute("DELETE FROM votes WHERE title = %s", (title,))
        con.commit()

        # 🆕 Insert into vote_options and votes tables
        for opt in options:
            cur.execute("INSERT INTO vote_options (title, option) VALUES (%s, %s)", (title, opt))
            cur.execute("INSERT INTO votes (title, option_text, votes, active) VALUES (%s, %s, 0, 1)", (title, opt))

        con.commit()
        con.close()

        flash("✅ Vote created successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    return render_template("admin_create_vote.html")


# @app.route('/admin/stop-vote', methods=['POST'])
# def stop_vote():
#     if not session.get('admin'):
#         return redirect(url_for('login'))

#     title = request.form['title']
#     con = get_db_connection()
#     cur = con.cursor()
#     cur.execute("UPDATE votes SET active=FALSE WHERE title=%s", (title,))
#     con.commit()
#     con.close()

#     flash(f"Voting for '{title}' stopped.")
#     return redirect(url_for('admin_dashboard'))

@app.route('/delete_vote', methods=['POST'])
def delete_vote():
    if not session.get('admin'):
        return redirect(url_for('login'))

    title = request.form.get('vote_title', '').strip()

    if not title:
        flash("⚠️ No vote title selected.", "warning")
        return redirect(url_for('admin_dashboard'))

    con = get_db_connection()
    cur = con.cursor()

    # ❌ Remove from all relevant tables
    cur.execute("DELETE FROM student_votes WHERE vote_title = %s", (title,))
    cur.execute("DELETE FROM vote_options WHERE title = %s", (title,))
    cur.execute("DELETE FROM votes WHERE title = %s", (title,))
    
    con.commit()
    con.close()

    flash(f"🗑️ Vote '{title}' deleted successfully.")
    return redirect(url_for('admin_dashboard'))

@app.route('/vote', methods=['GET', 'POST'])
def vote():
    if 'student' not in session:
        return redirect(url_for('login'))

    student = session['student']
    selected_title = request.args.get('title') or request.form.get('title')
    message = None
    voted = False
    options = []

    con = get_db_connection()
    cur = con.cursor()

    # 🔹 Get all vote titles
    cur.execute("SELECT DISTINCT title FROM votes")
    titles = [row[0] for row in cur.fetchall()]

    if selected_title:
        # 🔹 Check if already voted
        cur.execute("""
            SELECT 1 FROM student_votes 
            WHERE username = %s AND vote_title = %s AND option_id IS NOT NULL
        """, (student, selected_title))
        already_voted = cur.fetchone()

        # 🔹 Get options
        cur.execute("SELECT id, option FROM vote_options WHERE title = %s", (selected_title,))
        options = cur.fetchall()

        if request.method == 'POST' and not already_voted:
            option_id = request.form.get('option_id')

            if option_id:
                # Get actual option text
                cur.execute("SELECT option FROM vote_options WHERE id = %s", (option_id,))
                option_row = cur.fetchone()

                if option_row:
                    option_text = option_row[0]

                    # Insert vote
                    cur.execute("""
                        INSERT INTO student_votes (username, vote_title, option_id, voted_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (student, selected_title, option_id))

                    # Increment vote count
                    cur.execute("""
                        UPDATE votes SET votes = votes + 1 
                        WHERE title = %s AND option_text = %s
                    """, (selected_title, option_text))

                    con.commit()
                    message = "✅ Your vote has been submitted."
                    voted = True
                else:
                    message = "❌ Invalid option selected."
            else:
                message = "⚠️ Please select an option to vote."

        elif already_voted:
            message = f"✅ You have already voted for \"{selected_title}\"."
            voted = True

    con.close()

    return render_template("vote.html",
        titles=titles,
        selected_title=selected_title,
        options=options,
        message=message,
        voted=voted
    )

@app.route('/admin/student-votes', methods=['GET', 'POST'])
def view_student_votes():

    if 'admin' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor(dictionary=True)

    # Fetch students for dropdown
    cur.execute("SELECT username FROM users WHERE role='student'")
    students = [row['username'] for row in cur.fetchall()]

    selected_student = None
    votes = []

    if request.method == 'POST':
        selected_student = request.form.get('student')

        if selected_student:
            cur.execute("""
                SELECT
                    sv.vote_title,
                    v.option_text,
                    sv.voted_at
                FROM student_votes sv
                JOIN votes v ON sv.option_id = v.id
                WHERE sv.username = %s
                ORDER BY sv.voted_at DESC
            """, (selected_student,))
            votes = cur.fetchall()

    con.close()

    return render_template(
        "admin_student_votes.html",
        students=students,
        selected_student=selected_student,
        votes=votes
    )


@app.route('/student/chat', methods=['GET', 'POST'])
def student_chat():
    if 'student' not in session:
        return redirect(url_for('login'))

    username = session['student']
    last_error = None
    last_info = None

    if request.method == 'POST':

        # ===============================
        # FILE UPLOAD (PDF / TXT / MD)
        # ===============================
        if 'file' in request.files and request.files['file'].filename != '':
            uploaded = request.files['file']

            filename = secure_filename(uploaded.filename)
            ext = filename.lower().rsplit('.', 1)[-1]
            save_path = os.path.join(AI_NOTES_UPLOAD_FOLDER, filename)
            uploaded.save(save_path)

            try:
                if ext == 'pdf':
                    text_content = extract_text_from_pdf(save_path)
                elif ext in ('txt', 'md'):
                    with open(save_path, 'r', encoding='utf-8', errors='ignore') as f:
                        text_content = f.read()
                else:
                    last_error = "Only PDF, TXT, and MD files are supported."
                    text_content = ""

                if text_content.strip():
                    save_document(username, filename, text_content)
                    last_info = f"📄 File '{filename}' uploaded and indexed."
                elif not last_error:
                    last_error = "Could not extract any text from the file."

            except Exception as e:
                last_error = f"❌ File processing error: {e}"

        # ===============================
        # CHAT MESSAGE
        # ===============================
        else:
            user_input = request.form.get('message', '').strip()

            if not user_input:
                last_error = "Please type a message."
            else:
                # Save user message
                save_chat_message(username, 'user', user_input)

                # Build RAG context
                docs = load_user_documents(username)
                context = build_context_from_docs(user_input, docs)

                if context:
                    prompt = (
                        "You are an AI tutor. Use the student's notes below "
                        "to help answer the question. If the notes are not helpful, "
                        "answer normally.\n\n"
                        f"Notes:\n{context}\n\n"
                        f"Question: {user_input}"
                    )
                else:
                    prompt = user_input

                # ===============================
                # OLLAMA CALL (FIXED)
                # ===============================
                try:
                    result = requests.post(
                        "http://127.0.0.1:11434/api/generate",
                        json={
                            "model": "tinyllama",   # ✅ FIXED
                            "prompt": prompt,
                            "stream": False
                        },
                        timeout=120
                    )

                    result.raise_for_status()

                    data = result.json()   # ✅ FIXED
                    response = data.get("response", "No response from AI.")

                    save_chat_message(username, 'assistant', response)

                except Exception as e:
                    last_error = f"❌ Error talking to AI: {e}"

    # ===============================
    # LOAD CHAT HISTORY
    # ===============================
    history = get_chat_history(username)

    return render_template(
        'student_chat.html',
        history=history,
        last_error=last_error,
        last_info=last_info
    )

@app.route('/teacher', methods=['GET', 'POST'])
def teacher_dashboard():

    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor(dictionary=True)
    
    

    # Admin messages
    cur.execute("SELECT content FROM messages WHERE recipient IN ('teacher','all') ORDER BY id DESC")
    messages = [row['content'] for row in cur.fetchall()]

    # Materials
    cur.execute("SELECT * FROM materials")
    materials = cur.fetchall()

    # Quizzes
    cur.execute("SELECT * FROM quizzes")
    quizzes = cur.fetchall()

    # Students (for photo upload section)
    cur.execute("SELECT username, standard, photo FROM users WHERE role='student'")
    students = cur.fetchall()

    # Event updates
    cur.execute("""
        SELECT title, description, start_date
        FROM events
        WHERE audience IN ('teacher','both')
        ORDER BY start_date ASC
    """)
    event_updates = cur.fetchall()
    
    # Upcoming live classes
    cur.execute("""
    SELECT subject, standard, duration, date
    FROM live_classes
    WHERE DATE_ADD(date, INTERVAL duration MINUTE) > NOW()
    ORDER BY date ASC
    """)
    upcoming_classes = cur.fetchall()

    # Quiz scores (from your quiz_scores table)
    cur.execute("""
        SELECT name AS username,
               subject AS quiz_title,
               score,
               taken_at AS date
        FROM quiz_scores
        ORDER BY taken_at DESC
    """)
    quiz_scores = cur.fetchall()

    con.close()
    teacher = session.get('teacher')

    return render_template(
        "dashboard.html",
        teacher=teacher,
        materials=materials,
        messages=messages,
        quizzes=quizzes,     # ✅ FIX
        students=students, 
        event_updates=event_updates,
        quiz_scores=quiz_scores,
        upcoming_classes=upcoming_classes
)

@app.route('/teacher/queries')
def teacher_queries():
    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        SELECT id, student_username, subject, message, status, created_at
        FROM student_queries
        WHERE teacher_username=%s
        ORDER BY created_at DESC
    """, (session['teacher'],))

    queries = cur.fetchall()

    # 🔔 notification count
    cur.execute("""
        SELECT COUNT(*) FROM student_queries
        WHERE teacher_username=%s AND status='open'
    """, (session['teacher'],))
    new_count = cur.fetchone()[0]

    con.close()
    return render_template(
        'teacher_queries.html',
        queries=queries,
        new_count=new_count
    )

@app.route('/teacher/reply-query/<int:qid>', methods=['POST'])
def reply_query(qid):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        UPDATE student_queries
        SET reply=%s, status='replied'
        WHERE id=%s
    """, (request.form['reply'], qid))

    con.commit()
    con.close()
    return redirect(url_for('teacher_queries'))


@app.route('/teacher/close-query/<int:qid>')
def close_query(qid):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()
    cur.execute("UPDATE student_queries SET status='closed' WHERE id=%s", (qid,))
    con.commit()
    con.close()
    return redirect(url_for('teacher_queries'))

@app.route('/teacher/send-standard-message', methods=['GET', 'POST'])
def send_standard_message():
    if 'teacher' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        standard = request.form['standard']
        message = request.form['message']

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("""
            INSERT INTO teacher_broadcasts
            (teacher_username, standard, message)
            VALUES (%s, %s, %s)
        """, (session['teacher'], standard, message))

        con.commit()
        con.close()

        return redirect(url_for('send_standard_message'))

    return render_template('teacher_send_message.html')


@app.route('/teacher/profile')
def teacher_profile():
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT full_name, employee_id, dob, gender, mobile,
               alternate_mobile, official_email, personal_email,
               address, profile_photo
        FROM teachers
        WHERE employee_id = %s
    """, (session['employee_id'],))
    
    teacher = cursor.fetchone()
    cursor.close()

    return render_template(
        "updated_teacher_dashboard.html",
        teacher=teacher,
        section="profile"
    )
@app.route('/upload-teacher-photo', methods=['POST'])
def upload_teacher_photo():
    if 'teacher' not in session:
        return redirect(url_for('login'))

    file = request.files.get('photo')
    if not file or file.filename == '':
        flash("No photo selected")
        return redirect(url_for('teacher_dashboard'))

    filename = secure_filename(session['teacher'] + "_" + file.filename)
    save_path = os.path.join('static/uploads/photos', filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)

    con = get_db_connection()
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET photo=%s WHERE username=%s",
        (filename, session['teacher'])
    )
    con.commit()
    con.close()

    flash("✅ Profile photo updated")
    return redirect(url_for('teacher_dashboard'))


@app.route('/upload-student-photo/<username>', methods=['POST'])
def upload_student_photo(username):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    file = request.files['photo']

    if file:
        filename = secure_filename(f"{username}_{file.filename}")
        save_path = os.path.join('static/uploads/photos/', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)

        con = get_db_connection()
        cur = con.cursor()
        cur.execute("UPDATE users SET photo=%s WHERE username=%s", (filename, username))
        con.commit()
        con.close()

        flash("Photo uploaded successfully.")

    return redirect(url_for('teacher_dashboard'))


@app.route('/create-quiz', methods=['GET', 'POST'])
def create_quiz():
    if not session.get('teacher'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        questions = request.form.getlist('question')
        a_options = request.form.getlist('a')
        b_options = request.form.getlist('b')
        c_options = request.form.getlist('c')
        d_options = request.form.getlist('d')
        correct_options = request.form.getlist('correct')
        subject = request.form['subject']
        standard = request.form['standard']

        con = get_db_connection()
        cur = con.cursor()

        for i in range(len(questions)):
            cur.execute("""
                INSERT INTO quizzes (question, option1, option2, option3, option4, answer, subject, standard)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                questions[i], a_options[i], b_options[i],
                c_options[i], d_options[i], correct_options[i],
                subject, standard
            ))

        con.commit()
        con.close()

        flash("Quiz created successfully!")
        return redirect(url_for('teacher_dashboard'))

    return render_template('create_quiz.html')
    
@app.route('/take-quiz', methods=['GET', 'POST'])
def take_quiz():
    if not session.get('student'):
        return redirect(url_for('login'))

    username = session['student']
    con = get_db_connection()
    cur = con.cursor()

    # Get student's own standard
    cur.execute("SELECT standard FROM users WHERE username=%s", (username,))
    result = cur.fetchone()

    if not result:
        flash("Could not fetch your standard.")
        return redirect(url_for('login'))

    student_standard = result[0]

    # Get available subjects for this student's standard from quizzes table
    cur.execute("SELECT DISTINCT subject FROM quizzes WHERE standard=%s", (student_standard,))
    subjects = [row[0] for row in cur.fetchall()]

    if request.method == 'POST':
        name = request.form['name']
        subject = request.form['subject']

        cur.execute("SELECT * FROM quizzes WHERE standard=%s AND subject=%s", (student_standard, subject))
        questions = cur.fetchall()

        con.close()
        return render_template(
            'take_quiz.html',
            questions=questions,
            name=name,
            standard=student_standard,
            subject=subject
        )

    con.close()
    return render_template(
        'take_quiz.html',
        questions=None,
        subjects=subjects,
        standard=student_standard
    )

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    if not session.get('student'):
        return redirect(url_for('login'))

    # Fetch submitted form data
    name = request.form['name']
    standard = request.form['standard']
    subject = request.form['subject']

    # Collect submitted answers
    answers = {key: value for key, value in request.form.items() if key not in ['name', 'standard', 'subject']}

    con = get_db_connection()
    cur = con.cursor()

    score = 0
    total_questions = len(answers)

    # Check each answer against correct option
    for question, selected_option in answers.items():
        cur.execute("SELECT answer FROM quizzes WHERE id=%s", (question,))
        correct_option = cur.fetchone()
        if correct_option and correct_option[0] == selected_option:
            score += 1

    # Optional: Store score in a quiz_scores table (if you have one)
    # Example:
    cur.execute("INSERT INTO quiz_scores (name, standard, subject, score, total) VALUES (%s, %s, %s, %s, %s)",
                (name, standard, subject, score, total_questions))
    con.commit()

    con.close()

    return render_template('student_result.html', name=name, score=score, total=total_questions, subject=subject)


@app.route('/quiz-scores')
def quiz_scores():
    if not session.get('teacher') and not session.get('admin'):
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM quiz_scores")
    scores = cur.fetchall()
    con.close()
    return render_template('quiz_scores.html', scores=scores)


@app.route('/materials')
def view_materials():
    if not session.get('student'):
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    # Fetch student's standard using session username
    cur.execute("SELECT standard FROM users WHERE username=%s", (session['student'],))
    student_standard = cur.fetchone()[0]

    # Fetch study materials for that standard
    cur.execute("SELECT * FROM materials WHERE standard=%s", (student_standard,))
    materials = cur.fetchall()

    con.close()

    return render_template('materials.html', materials=materials)

# @app.route('/upload-material', methods=['GET','POST'])
# def upload_material():
#     if 'teacher' not in session:
#         return redirect(url_for('login'))

#     if request.method == 'POST':
#         title = request.form['title']
#         standard = request.form['standard']
#         subject = request.form['subject']
#         file = request.files['file']

#         filename = file.filename
#         file.save(os.path.join('static/uploads', filename))

#         con = get_db_connection()
#         cur = con.cursor()
#         cur.execute("""INSERT INTO materials(title,standard,subject,filename)
#                        VALUES(%s,%s,%s,%s)""",
#                     (title,standard,subject,filename))
#         con.commit()
#         con.close()

#         flash("Material uploaded successfully")
#         return redirect('/teacher')

#     return render_template("upload.html")
from werkzeug.utils import secure_filename
import os

@app.route('/upload-material', methods=['GET', 'POST'])
def upload_material():
    if 'teacher' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        standard = request.form['standard']
        subject = request.form['subject']
        file = request.files['file']

        if not file or file.filename == '':
            flash("No file selected")
            return redirect(request.url)

        # 🔐 Secure filename
        filename = secure_filename(file.filename)

        # 📁 Absolute upload path
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # 📂 Ensure folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # 💾 Save file
        file.save(file_path)

        # 💾 Save ONLY filename in DB
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO materials (title, standard, subject, filename)
            VALUES (%s, %s, %s, %s)
        """, (title, standard, subject, filename))
        con.commit()
        con.close()

        flash("Material uploaded successfully")
        return redirect('/teacher')

    return render_template("upload.html")


@app.route('/edit-material/<int:id>', methods=['GET', 'POST'])
def edit_material(id):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    if request.method == 'POST':
        title = request.form['title']
        standard = request.form['standard']
        subject = request.form['subject']

        cur.execute("UPDATE materials SET title=%s, standard=%s, subject=%s WHERE id=%s",
                    (title, standard, subject, id))
        con.commit()
        con.close()
        flash("Material updated successfully.")
        return redirect(url_for('teacher_dashboard'))

    cur.execute("SELECT * FROM materials WHERE id=%s", (id,))
    material = cur.fetchone()
    con.close()
    return render_template("edit_material.html", material=material)

@app.route('/delete-material/<int:id>')
def delete_material(id):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("SELECT filename FROM materials WHERE id=%s",(id,))
    file = cur.fetchone()
    if file:
        path = os.path.join('static/uploads', file[0])
        if os.path.exists(path):
            os.remove(path)

    cur.execute("DELETE FROM materials WHERE id=%s",(id,))
    con.commit()
    con.close()
    flash("Material deleted")
    return redirect('/teacher')


from flask import send_file

@app.route('/view-material/<path:filename>')
def teacher_view_material(filename):
    if 'teacher' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(file_path):
        abort(404)

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=False
    )

# 🔹 View material INLINE (no download)
# @app.route('/student/view-material/<filename>')
# def student_view_material(filename):
#     if 'student' not in session:
#         return redirect(url_for('login'))

#     file_path = os.path.join('static/uploads', filename)

#     return send_file(
#         file_path,
#         mimetype='application/pdf',
#         as_attachment=False   # 👈 inline view
#     )
@app.route('/student/view-material/<path:filename>')
def student_view_material(filename):
    if 'student' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(file_path):
        abort(404, description="Material not found")

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=False
    )



# 🔹 Download material
# @app.route('/student/download-material/<filename>')
# def student_download_material(filename):
#     if 'student' not in session:
#         return redirect(url_for('login'))

#     file_path = os.path.join('static/uploads', filename)

#     return send_file(
#         file_path,
#         as_attachment=True    # 👈 force download
#     )
@app.route('/student/download-material/<path:filename>')
def student_download_material(filename):
    if 'student' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(file_path):
        abort(404, description="Material not found")

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=True
    )



@app.route('/student', methods=['GET', 'POST'])
def student_dashboard():

    if 'student' not in session:
        return redirect(url_for('login'))

    username = session['student']
    con = get_db_connection()
    cur = con.cursor(dictionary=True)

    # -------------------------------
    # Get student's standard
    # -------------------------------
    cur.execute(
        "SELECT standard FROM users WHERE username=%s",
        (username,)
    )
    result = cur.fetchone()

    if not result:
        flash("Could not fetch your standard.")
        con.close()
        return redirect(url_for('login'))

    student_standard = result['standard']

    # -------------------------------
    # Subjects (for dropdown)
    # -------------------------------
    cur.execute(
        "SELECT DISTINCT subject FROM materials WHERE standard=%s",
        (student_standard,)
    )
    subjects = [r['subject'] for r in cur.fetchall()]

    # -------------------------------
    # Messages (admin announcements)
    # -------------------------------
    cur.execute(
        "SELECT content FROM messages WHERE recipient IN ('student','all')"
    )
    messages = [row['content'] for row in cur.fetchall()]

    # -------------------------------
    # Votes
    # -------------------------------
    cur.execute(
        "SELECT vote_title FROM student_votes WHERE username=%s",
        (username,)
    )
    voted_titles = [row['vote_title'] for row in cur.fetchall()]

    # -------------------------------
    # Event Updates
    # -------------------------------
    cur.execute("""
        SELECT title, description, start_date
        FROM events
        WHERE audience IN ('student','both')
        ORDER BY start_date ASC
    """)
    event_updates = cur.fetchall()

    # -------------------------------
    # Live Classes
    # -------------------------------
    cur.execute("""
        SELECT subject, standard, duration, date
        FROM live_classes
        WHERE standard=%s
          AND DATE_ADD(date, INTERVAL duration MINUTE) > NOW()
        ORDER BY date ASC
    """, (student_standard,))
    live_classes = cur.fetchall()

    # -------------------------------
    # Materials (filter by subject)
    # -------------------------------
    materials = []
    selected_subject = None

    if request.method == 'POST':
        selected_subject = request.form.get('subject')

        query = """
            SELECT
                id,
                standard,
                subject,
                title,
                filename AS file_path
            FROM materials
            WHERE standard=%s
        """
        params = [student_standard]

        if selected_subject:
            query += " AND subject=%s"
            params.append(selected_subject)

        cur.execute(query, params)
        materials = cur.fetchall()

    con.close()

    # -------------------------------
    # Render Template
    # -------------------------------
    return render_template(
        "student_home.html",
        subjects=subjects,
        materials=materials,
        selected_subject=selected_subject,
        messages=messages,
        voted_titles=voted_titles,
        student_standard=student_standard,
        event_updates=event_updates,
        live_classes=live_classes
    )


@app.route('/student/send-query', methods=['POST'])
def send_query():
    if 'student' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO student_queries
        (student_username, teacher_username, subject, message)
        VALUES (%s,%s,%s,%s)
    """, (
        session['student'],
        request.form['teacher'],
        request.form['subject'],
        request.form['message']
    ))

    con.commit()
    con.close()
    return redirect(url_for('my_queries'))

@app.route('/student/ask-query')
def ask_query():
    if 'student' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("SELECT username FROM users WHERE role='teacher'")
    teachers = [t[0] for t in cur.fetchall()]

    con.close()
    return render_template('ask_query.html', teachers=teachers)

@app.route('/student/my-queries')
def my_queries():
    if 'student' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        SELECT subject, message, reply, status, created_at
        FROM student_queries
        WHERE student_username=%s
        ORDER BY created_at DESC
    """, (session['student'],))

    my_queries = cur.fetchall()
    con.close()
    return render_template('student_queries.html', my_queries=my_queries)

@app.route('/student/standard-messages')
def student_standard_messages():
    if 'student' not in session:
        return redirect(url_for('login'))

    con = get_db_connection()
    cur = con.cursor(dictionary=True)

    # get student's standard
    cur.execute(
        "SELECT standard FROM users WHERE username=%s",
        (session['student'],)
    )
    standard = cur.fetchone()['standard']

    # fetch messages for that standard
    cur.execute("""
        SELECT teacher_username, message, created_at
        FROM teacher_broadcasts
        WHERE standard=%s
        ORDER BY created_at DESC
    """, (standard,))

    messages = cur.fetchall()
    con.close()

    return render_template(
        'student_standard_messages.html',
        messages=messages,
        standard=standard
    )




# ------------------ Host Meeting ------------------
@app.route('/host-meeting')
def host_meeting():
    if 'teacher' not in session:
        return redirect(url_for('login'))
    room_name = "classroom_" + session['teacher']
    return render_template("live_meeting.html", room_name=room_name, user=session['teacher'], role='teacher')

@app.route('/schedule-class', methods=['GET','POST'])
def schedule_class():
    if 'teacher' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        subject = request.form['subject']
        standard = request.form['standard']
        duration = request.form['duration']
        date = request.form['date']

        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
        INSERT INTO live_classes (subject, standard, duration, date)
        VALUES (%s,%s,%s,%s)
""",    (subject, standard, duration, date))
        con.commit()

        con.close()
        flash("Class Scheduled Successfully!")
        return redirect('/teacher')

    return render_template("schedule_class.html")


# ------------------ Join Meeting ------------------
@app.route('/join-meeting')
def join_meeting():
    if 'student' not in session:
        return redirect(url_for('login'))
    room_name = "classroom_teacher"  # You can make this dynamic later
    return render_template("live_meeting.html", room_name=room_name, user=session['student'], role='student')

# ------------------ Submit Feedback ------------------
@app.route('/feedback', methods=['POST'])
def feedback():
    if 'student' not in session:
        return redirect(url_for('login'))
    name = request.form['name']
    rating = request.form['rating']
    comment = request.form['comment']
    con = get_db_connection()
    cursor = con.cursor()
    cursor.execute("INSERT INTO feedback (student_name, rating, comment) VALUES (%s, %s, %s)", (name, rating, comment))
    con.commit()
    con.close()
    flash("Thanks for your feedback!")
    return redirect(url_for('student_dashboard'))

# ------------------ View Feedback ------------------
@app.route('/view-feedback')
def view_feedback():
    if 'teacher' not in session:
        return redirect(url_for('login'))
    con = get_db_connection()
    cursor = con.cursor()
    cursor.execute("SELECT student_name, rating, comment FROM feedback")
    feedbacks = cursor.fetchall()
    con.close()
    return render_template("view_feedback.html", feedbacks=feedbacks)


if __name__ == '__main__':
    app.run(debug=True)



