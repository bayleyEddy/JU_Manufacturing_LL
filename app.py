from flask import Flask, request, render_template, redirect, jsonify, Response, session, url_for
import pyodbc
from datetime import datetime, timedelta
import time
import random
import smtplib
from email.mime.text import MIMEText
import io
import csv

app = Flask(__name__)
app.secret_key = "a8f9b1c2d3e4f5g6h7i8j9k0"

# ---------------------------------------------------------
# Azure SQL Connection
# ---------------------------------------------------------
uid = 'Lab_Sign_In'
pwd = 'Dogman123!'
driver = '{ODBC Driver 17 for SQL Server}'
server = 'signinlab.database.windows.net'
database = 'SignIn_Manufacturing'


def connect_db():
    return pyodbc.connect(
        f"DRIVER={driver};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={uid};"
        f"PWD={pwd};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

# ---------------------------------------------------------
# Email / 2FA Config
# ---------------------------------------------------------
PROFESSOR_EMAIL = "bayley.test2@gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "bayley.test2@gmail.com"
SMTP_PASS = "ohrh dzwx bfoh mssj"


def send_2fa_email(to_email, code):
    subject = "Your Professor Dashboard Verification Code"
    body = f"Your verification code is: {code}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

# ---------------------------------------------------------
# TEMPORARY STORAGE FOR PROFESSOR ID
# ---------------------------------------------------------
current_professor_id = None

# ---------------------------------------------------------
# Home Page Route
# ---------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# ---------------------------------------------------------
# Check-In / Check-Out Route (with 2FA + delay)
# ---------------------------------------------------------
@app.route("/checkin", methods=["POST"])
def checkin():
    global current_professor_id

    student_id = request.form.get("student_id")

    # Clean swipe if raw track data appears
    if ";" in student_id and "=" in student_id:
        track2 = student_id.split(";")[1]
        discretionary = track2.split("=")[1].replace("?", "")
        student_id = discretionary[-6:]

    # Convert to INT
    try:
        student_id = int(student_id)
    except:
        return {"message": "Invalid card swipe format"}

    # Small delay to throttle rapid swipes
    time.sleep(1.5)

    try:
        conn = connect_db()
        cursor = conn.cursor()

        # -------------------------------------------------
        # 1. CHECK PROFESSOR TABLE
        # -------------------------------------------------
        cursor.execute("""
            SELECT FirstName, LastName
            FROM dbo.Professor
            WHERE Teacher_ID = ?
        """, student_id)

        prof = cursor.fetchone()

        if prof:
            role = "Professor"
            first_name, last_name = prof
            waiver = 1

            current_professor_id = student_id

            # 2FA for Professor
            code = random.randint(100000, 999999)
            session["prof_2fa_code"] = str(code)
            session["prof_2fa_expiry"] = time.time() + 300
            session["professor_id"] = student_id
            session["professor_name"] = f"{first_name} {last_name}"
            session["professor_email"] = PROFESSOR_EMAIL
            session["professor_authenticated"] = False

            send_2fa_email(PROFESSOR_EMAIL, code)

        else:
            # -------------------------------------------------
            # 2. CHECK STUDENT WORKER TABLE
            # -------------------------------------------------
            cursor.execute("""
                SELECT Worker_FirstName, Worker_LastName, Worker_Email
                FROM dbo.Student_Worker
                WHERE Worker_ID = ?
            """, student_id)

            worker = cursor.fetchone()

            if worker:
                role = "StudentWorker"
                first_name, last_name, worker_email = worker
                waiver = 1

                cursor.execute("""
                    SELECT Worker_ID
                    FROM dbo.Student_Worker
                    WHERE Worker_ID = ?
                """, student_id)

                worker_row = cursor.fetchone()
                if worker_row:
                    student_id = worker_row[0]

                session["worker_id"] = student_id
                session["worker_name"] = f"{first_name} {last_name}"
                session["worker_email"] = worker_email

                # 2FA for Student Worker
                code = random.randint(100000, 999999)
                session["worker_2fa_code"] = str(code)
                session["worker_2fa_expiry"] = time.time() + 300
                session["worker_authenticated"] = False

                send_2fa_email(worker_email, code)

            else:
                # -------------------------------------------------
                # 3. CHECK STUDENT TABLE
                # -------------------------------------------------
                cursor.execute("""
                    SELECT First_Name, Last_Name, Liability_Waivers
                    FROM dbo.Student
                    WHERE Student_ID = ?
                """, student_id)

                student = cursor.fetchone()

                if not student:
                    conn.close()
                    return {"message": "ID not found in system"}

                first_name, last_name, waiver = student
                role = "Student"

                if waiver is None or waiver == 0:
                    conn.close()
                    return {"message": f"{first_name} {last_name} cannot check in - liability waiver"}

        # -------------------------------------------------
        # Check if user is already logged in
        # -------------------------------------------------
        cursor.execute("""
            SELECT LoginTime
            FROM dbo.Attendance_Log
            WHERE Attendance_ID = ? AND LogoutTime IS NULL
        """, student_id)

        active_session = cursor.fetchone()
        current_time = datetime.now()

        # -------------------------------------------------
        # Role redirect mapping
        # -------------------------------------------------
        role_redirects = {
            "Professor": "/professor_2fa",
            "StudentWorker": "/worker_2fa",
            "Student": "/student_home"
        }

        redirect_url = role_redirects.get(role, "/student_home")

        # -------------------------------------------------
        # LOG OUT
        # -------------------------------------------------
        if active_session:
            cursor.execute("""
                UPDATE dbo.Attendance_Log
                SET LogoutTime = ?
                WHERE Attendance_ID = ? AND LogoutTime IS NULL
            """, current_time, student_id)

            conn.commit()
            conn.close()

            return {
                "message": f"{first_name} {last_name} checked OUT at {current_time}",
                "redirect": redirect_url
            }

        # -------------------------------------------------
        # LOG IN
        # -------------------------------------------------
        cursor.execute("""
            INSERT INTO dbo.Attendance_Log
            (Att_FirstName, Att_LastName, Attendance_ID, LoginTime, LogoutTime, WaiverOverrideUsed, OverrideGrantedByWorkerID)
            VALUES (?, ?, ?, ?, NULL, 0, NULL)
        """, first_name, last_name, student_id, current_time)

        conn.commit()
        conn.close()

        return {
            "message": f"{first_name} {last_name} checked IN at {current_time}",
            "redirect": redirect_url
        }

    except Exception as e:
        return {"message": f"Database Error: {str(e)}"}

# ---------------------------------------------------------
# Professor 2FA
# ---------------------------------------------------------
@app.route("/professor_2fa", methods=["GET", "POST"])
def professor_2fa():
    if "prof_2fa_code" not in session:
        return redirect("/")

    # For resend functionality
    session["pending_prof_email"] = session.get("professor_email")

    if request.method == "POST":
        entered = request.form.get("code", "").strip()
        real_code = session.get("prof_2fa_code")
        expiry = session.get("prof_2fa_expiry", 0)

        if not real_code or time.time() > expiry:
            session.pop("prof_2fa_code", None)
            session.pop("prof_2fa_expiry", None)
            return render_template("professor_2fa.html",
                                   error="Code expired. Please swipe again to log in.")

        if entered == real_code:
            session["professor_authenticated"] = True
            session.pop("prof_2fa_code", None)
            session.pop("prof_2fa_expiry", None)
            return redirect("/professor_home")

        return render_template("professor_2fa.html",
                               error="Invalid code. Please try again.")

    return render_template("professor_2fa.html")

# ---------------------------------------------------------
# Worker 2FA
# ---------------------------------------------------------
@app.route("/worker_2fa", methods=["GET", "POST"])
def worker_2fa():
    if request.method == "POST":
        code_entered = request.form.get("code")

        stored_code = session.get("worker_2fa_code")
        expiry = session.get("worker_2fa_expiry")

        if not stored_code or not expiry:
            return render_template("worker_2fa.html", error="Session expired. Please log in again.")

        if time.time() > expiry:
            return render_template("worker_2fa.html", error="Code expired. Please request a new one.")

        if code_entered != stored_code:
            return render_template("worker_2fa.html", error="Incorrect code. Try again.")

        # SUCCESS
        session["worker_authenticated"] = True
        return redirect("/student_worker") 

    session["pending_worker_email"] = session.get("worker_email")
    return render_template("worker_2fa.html")



# ---------------------------------------------------------
# Resend 2FA Code (Works for both Professor & Student Worker)
# ---------------------------------------------------------
@app.route("/resend_2fa_code", methods=["POST"])
def resend_2fa_code():
    # Determine which user type is currently in 2FA
    worker_email = session.get("pending_worker_email")
    prof_email = session.get("pending_prof_email")

    if worker_email:
        email = worker_email
        code_key = "worker_2fa_code"
        expiry_key = "worker_2fa_expiry"
    elif prof_email:
        email = prof_email
        code_key = "prof_2fa_code"
        expiry_key = "prof_2fa_expiry"
    else:
        return jsonify({
            "success": False,
            "message": "No pending login session found."
        })

    # Generate new code
    new_code = str(random.randint(100000, 999999))
    expiry = time.time() + 300  # 5 minutes

    # Store new code in correct session variables
    session[code_key] = new_code
    session[expiry_key] = expiry

    # Send email
    send_2fa_email(email, new_code)

    return jsonify({
        "success": True,
        "message": "A new verification code has been sent to your email."
    })



# ---------------------------------------------------------
# Professor Dashboard
# ---------------------------------------------------------
@app.route("/professor_home")
def professor_home():
    return render_template("professor_home.html")

# ---------------------------------------------------------
# Professor Search Route
# ---------------------------------------------------------
@app.route("/professor_search", methods=["POST"])
def professor_search():
    search_value = request.form.get("student_id").strip()
    parts = search_value.split()

    try:
        conn = connect_db()
        cursor = conn.cursor()

        if search_value.isdigit():
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE Student_ID = ?
            """, int(search_value))
        elif len(parts) == 2:
            first, last = parts[0], parts[1]
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE LOWER(First_Name) = LOWER(?)
                  AND LOWER(Last_Name) = LOWER(?)
            """, first, last)
        else:
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE LOWER(First_Name) = LOWER(?)
                   OR LOWER(Last_Name) = LOWER(?)
            """, search_value, search_value)

        student = cursor.fetchone()

        if not student:
            conn.close()
            return {"error": "No matching student found"}

        student_id, first_name, last_name, waiver = student
        waiver_text = "Yes" if waiver == 1 else "No"

        cursor.execute("""
            SELECT LoginTime, LogoutTime
            FROM dbo.Attendance_Log
            WHERE Attendance_ID = ?
            ORDER BY LoginTime DESC
        """, student_id)

        logs = cursor.fetchall()
        conn.close()

        log_list = []
        for log in logs:
            log_list.append({
                "login": str(log[0]),
                "logout": str(log[1]) if log[1] else "Still logged in"
            })

        return {
            "first_name": first_name,
            "last_name": last_name,
            "student_id": student_id,
            "waiver": waiver_text,
            "logs": log_list
        }

    except Exception as e:
        return {"error": f"Database Error: {str(e)}"}

# ---------------------------------------------------------
# Professor Metrics Route
# ---------------------------------------------------------
@app.route("/professor_metrics")
def professor_metrics():
    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TOP 5
                s.Student_ID,
                s.First_Name,
                s.Last_Name,
                SUM(DATEDIFF(MINUTE, a.LoginTime, a.LogoutTime)) AS TotalMinutes
            FROM dbo.Attendance_Log a
            JOIN dbo.Student s ON a.Attendance_ID = s.Student_ID
            WHERE a.LoginTime >= DATEADD(DAY, -7, GETDATE())
              AND a.LogoutTime IS NOT NULL
            GROUP BY s.Student_ID, s.First_Name, s.Last_Name
            ORDER BY TotalMinutes DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        top_students = []
        for r in rows:
            top_students.append({
                "student_id": r[0],
                "first_name": r[1],
                "last_name": r[2],
                "minutes": r[3]
            })

        return {"top_students": top_students}

    except Exception as e:
        return {"error": f"Metrics Error: {str(e)}"}

# ---------------------------------------------------------
# Professor Logout Route
# ---------------------------------------------------------
@app.route("/professor_logout")
def professor_logout():
    global current_professor_id

    if current_professor_id is None:
        return redirect("/")

    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE dbo.Attendance_Log
            SET LogoutTime = ?
            WHERE Attendance_ID = ? AND LogoutTime IS NULL
        """, datetime.now(), current_professor_id)

        conn.commit()
        conn.close()

        current_professor_id = None

        return redirect("/")

    except Exception as e:
        return f"Error logging out: {str(e)}"



@app.route("/assign_worker_schedule", methods=["POST"])
def assign_worker_schedule():
    worker_id = request.form.get("worker_id")
    day = request.form.get("day")
    start = request.form.get("start_time")
    end = request.form.get("end_time")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Student_Worker_Schedule (Worker_ID, DayOfWeek, StartTime, EndTime)
        VALUES (?, ?, ?, ?)
    """, worker_id, day, start, end)

    conn.commit()
    conn.close()

    return jsonify({"message": "Shift assigned successfully!"})

# ---------------------------------------------------------
# Worker & Student Pages
# ---------------------------------------------------------
@app.route("/student_home")
def student_home():
    return "<h1>Student Home</h1>"

# ---------------------------------------------------------
# GET CURRENTLY SIGNED-IN USERS
# ---------------------------------------------------------
def get_signed_in_users():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Att_FirstName, Att_LastName, Attendance_ID, LoginTime
        FROM dbo.Attendance_Log
        WHERE LogoutTime IS NULL
        ORDER BY LoginTime DESC
    """)

    users = cursor.fetchall()
    conn.close()

    result = []
    for u in users:
        result.append({
            "first": u[0],
            "last": u[1],
            "id": u[2],
            "login": u[3].strftime("%I:%M %p")
        })

    return result

@app.route("/student_worker")
def worker_home():
    users = get_signed_in_users()
    return render_template("student_worker.html", users=users)

# ---------------------------------------------------------
# SEARCH (Worker)
# ---------------------------------------------------------
@app.route("/worker_search", methods=["GET", "POST"])
def worker_search():
    users = get_signed_in_users()

    # Unified GET/POST handling
    search_input = request.values.get("student_id", "").strip()

    if not search_input:
        return render_template("student_worker.html", users=users, error="Please enter a name or ID")

    conn = connect_db()
    cursor = conn.cursor()

    # Search by ID or name
    if search_input.isdigit():
        cursor.execute("""
            SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
            FROM dbo.Student
            WHERE Student_ID = ?
        """, search_input)
    else:
        parts = search_input.split()
        if len(parts) == 1:
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE First_Name LIKE ? OR Last_Name LIKE ?
            """, parts[0], parts[0])
        else:
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE First_Name LIKE ? AND Last_Name LIKE ?
            """, parts[0], parts[1])

    student = cursor.fetchone()

    if not student:
        conn.close()
        return render_template("student_worker.html", users=users, error="Student not found")

    student_id, first_name, last_name, waiver = student

    # Normalize waiver
    waiver = 1 if waiver in (1, True, '1') else 0

    # Check override
    cursor.execute("""
        SELECT Override_Date
        FROM dbo.Temporary_Waiver_Override
        WHERE Student_ID = ?
    """, student_id)

    override = cursor.fetchone()
    today = datetime.now().date()
    override_valid = override and override[0] == today

    search_result = {
        "id": student_id,
        "first": first_name,
        "last": last_name,
        "waiver": waiver,
        "override_valid": override_valid
    }

    conn.close()
    return render_template("student_worker.html", users=users, search_result=search_result)

# ---------------------------------------------------------
# SIGN IN STUDENT FROM DASHBOARD
# ---------------------------------------------------------
@app.route("/sign_in_student", methods=["POST"])
def sign_in_student():
    student_id = int(request.form.get("student_id"))

    conn = connect_db()
    cursor = conn.cursor()

    # Fetch student info
    cursor.execute("""
        SELECT First_Name, Last_Name, Liability_Waivers
        FROM dbo.Student
        WHERE Student_ID = ?
    """, student_id)

    student = cursor.fetchone()
    if not student:
        conn.close()
        return redirect("/student_worker")

    first_name, last_name, waiver = student

    # Normalize waiver (NULL → 0, 1 stays 1)
    waiver = 1 if waiver in (1, True, '1') else 0

    # Check override
    cursor.execute("""
        SELECT Override_Date
        FROM Temporary_Waiver_Override
        WHERE Student_ID = ?
    """, student_id)

    override = cursor.fetchone()
    today = datetime.now().date()
    override_valid = override and override[0] == today

    # Block sign-in if no waiver and no override
    if waiver != 1 and not override_valid:
        conn.close()
        return redirect("/student_worker")

    # Prevent duplicate sign-in
    cursor.execute("""
        SELECT LoginTime
        FROM dbo.Attendance_Log
        WHERE Attendance_ID = ? AND LogoutTime IS NULL
    """, student_id)

    active = cursor.fetchone()
    if active:
        conn.close()
        return redirect("/student_worker")

    now = datetime.now()

    # Insert full attendance record including override info
    cursor.execute("""
        INSERT INTO dbo.Attendance_Log
        (Att_FirstName, Att_LastName, Attendance_ID, LoginTime, LogoutTime,
         WaiverOverrideUsed, OverrideGrantedByWorkerID)
        VALUES (?, ?, ?, ?, NULL, ?, ?)
    """,
        first_name,
        last_name,
        student_id,
        now,
        1 if override_valid else 0,
        session.get("worker_id")
    )

    conn.commit()
    conn.close()

    return redirect("/student_worker")

# ---------------------------------------------------------
# LOGOUT ALL USERS
# ---------------------------------------------------------
@app.route("/force_logout_all", methods=["POST"])
def force_logout_all():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE dbo.Attendance_Log
        SET LogoutTime = ?
        WHERE LogoutTime IS NULL
    """, datetime.now())

    conn.commit()
    conn.close()

    session.pop("worker_id", None)

    return redirect("/")

# ---------------------------------------------------------
# WORKER LOGOUT
# ---------------------------------------------------------
@app.route("/worker_logout")
def worker_logout():
    worker_id = session.get("worker_id")

    if not worker_id:
        return redirect("/")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE dbo.Attendance_Log
        SET LogoutTime = ?
        WHERE Attendance_ID = ? AND LogoutTime IS NULL
    """, datetime.now(), worker_id)

    conn.commit()
    conn.close()

    session.pop("worker_id", None)

    return redirect("/")

# ---------------------------------------------------------
# Overrides student waiver sign in
# ---------------------------------------------------------
@app.route("/override_waiver", methods=["POST"])
def override_waiver():
    student_id = request.form.get("student_id")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        MERGE dbo.Temporary_Waiver_Override AS target
        USING (SELECT ? AS Student_ID) AS source
        ON target.Student_ID = source.Student_ID
        WHEN MATCHED THEN
            UPDATE SET Override_Date = CAST(GETDATE() AS DATE)
        WHEN NOT MATCHED THEN
            INSERT (Student_ID, Override_Date)
            VALUES (source.Student_ID, CAST(GETDATE() AS DATE));
    """, student_id)

    conn.commit()
    conn.close()

    # Redirect back to worker_search WITH the student ID
    return redirect(url_for("worker_search", student_id=student_id))


@app.route("/monthly_dashboard_data")
def monthly_dashboard_data():
    conn = connect_db()
    cursor = conn.cursor()

    month = request.args.get("month", "all")

    if month == "all":
        month_filter = ""
        params = []
    else:
        month_filter = "WHERE MONTH(a.LoginTime) = ?"
        params = [int(month)]

    # -----------------------------
    # Student totals (bar chart)
    # -----------------------------
    cursor.execute(f"""
        SELECT
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            SUM(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS TotalMinutes
        FROM Attendance_Log a
        JOIN Student s ON a.Attendance_ID = s.Student_ID
        {month_filter}
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name
        ORDER BY TotalMinutes DESC;
    """, params)

    student_rows = cursor.fetchall()

    students = [{
        "id": r[0],
        "first": r[1],
        "last": r[2],
        "minutes": r[3]
    } for r in student_rows]

    # -----------------------------
    # Daily totals (line chart)
    # -----------------------------
    cursor.execute(f"""
        SELECT
            CAST(a.LoginTime AS DATE) AS Day,
            SUM(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS TotalMinutes
        FROM Attendance_Log a
        {month_filter}
        GROUP BY CAST(a.LoginTime AS DATE)
        ORDER BY Day ASC;
    """, params)

    daily_rows = cursor.fetchall()

    daily = [{
        "day": r[0].strftime("%Y-%m-%d"),
        "minutes": r[1]
    } for r in daily_rows]

    return jsonify({
        "students": students,
        "daily": daily
    })



# ---------------------------------------------------------
# Monthly CSV Export
# ---------------------------------------------------------
@app.route('/export_all_csv')
def export_all_csv():
    import io, csv, zipfile
    from flask import send_file, request

    conn = connect_db()
    cursor = conn.cursor()

    # -----------------------------
    # Month filter
    # -----------------------------
    month = request.args.get("month", "all")

    if month == "all":
        month_filter = ""
        params = []
    else:
        month_filter = "WHERE MONTH(a.LoginTime) = ?"
        params = [int(month)]

    # -----------------------------
    # 1. Attendance Summary CSV
    # -----------------------------
    summary_output = io.StringIO()
    summary_writer = csv.writer(summary_output)

    summary_writer.writerow([
        "Student ID",
        "First Name",
        "Last Name",
        "Total Minutes",
        "Student Worker"
    ])

    cursor.execute(f"""
        SELECT 
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            COALESCE(SUM(DATEDIFF(minute, a.LoginTime, a.LogoutTime)), 0) AS total_minutes,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 'YES' ELSE '' END AS IsStudentWorker
        FROM Student s
        LEFT JOIN Attendance_Log a 
            ON s.Student_ID = a.Attendance_ID
        LEFT JOIN Student_Worker sw
            ON sw.Worker_ID = s.Student_ID
        {month_filter}
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name, sw.Worker_ID
        ORDER BY total_minutes DESC
    """, params)

    for row in cursor.fetchall():
        summary_writer.writerow(row)

    # -----------------------------
    # 2. Raw Attendance Log CSV
    # -----------------------------
    raw_output = io.StringIO()
    raw_writer = csv.writer(raw_output)

    raw_writer.writerow([
        "Student ID",
        "First Name",
        "Last Name",
        "Date",
        "Login Time",
        "Logout Time",
        "Student Worker",
        "Temporary Waiver Used",
        "Override Granted By"
    ])

    cursor.execute(f"""
        SELECT 
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            CAST(a.LoginTime AS DATE) AS LogDate,
            a.LoginTime,
            a.LogoutTime,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 'YES' ELSE '' END AS IsStudentWorker,
            CASE WHEN a.WaiverOverrideUsed = 1 THEN 'FLAG' ELSE '' END AS WaiverFlag,
            CONCAT(w.Worker_FirstName, ' ', w.Worker_LastName) AS OverrideBy
        FROM Attendance_Log a
        JOIN Student s 
            ON s.Student_ID = a.Attendance_ID
        LEFT JOIN Student_Worker sw
            ON sw.Worker_ID = s.Student_ID
        LEFT JOIN Student_Worker w
            ON w.Worker_ID = a.OverrideGrantedByWorkerID
        {month_filter}
        ORDER BY a.LoginTime DESC
    """, params)

    for row in cursor.fetchall():
        raw_writer.writerow(row)

    # -----------------------------
    # 3. ZIP both CSVs
    # -----------------------------
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("attendance_summary.csv", summary_output.getvalue())
        zf.writestr("raw_attendance_logs.csv", raw_output.getvalue())

    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype="application/zip",
        as_attachment=True,
        download_name="attendance_reports.zip"
    )


# ---------------------------------------------------------
# Students Missing Liability Waivers
# ---------------------------------------------------------
@app.route("/students_without_waivers")
def students_without_waivers():
    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT Student_ID, First_Name, Last_Name
            FROM dbo.Student
            WHERE Liability_Waivers = 0 OR Liability_Waivers IS NULL
            ORDER BY Last_Name, First_Name
        """)

        rows = cursor.fetchall()
        conn.close()

        students = []
        for r in rows:
            students.append({
                "student_id": r[0],
                "first_name": r[1],
                "last_name": r[2]
            })

        return {"students": students}

    except Exception as e:
        return {"error": f"Waiver Error: {str(e)}"}

# ---------------------------------------------------------
# Today's Student Worker + Shift Info
# ---------------------------------------------------------
@app.route("/today_worker")
def today_worker():
    conn = connect_db()
    cursor = conn.cursor()

    today = datetime.now().strftime("%A")

    cursor.execute("""
        SELECT s.Worker_ID, sw.Worker_FirstName, sw.Worker_LastName,
               s.StartTime, s.EndTime
        FROM Student_Worker_Schedule s
        JOIN Student_Worker sw ON s.Worker_ID = sw.Worker_ID
        WHERE s.DayOfWeek = ?
    """, today)

    row = cursor.fetchone()

    if not row:
        return jsonify({"message": "No student worker scheduled today."})

    worker_id, first, last, start, end = row

    shift_start = datetime.combine(datetime.today(), start)
    shift_end = datetime.combine(datetime.today(), end)

    cursor.execute("""
        SELECT LoginTime, LogoutTime
        FROM Attendance_Log
        WHERE Attendance_ID = ?
          AND CAST(LoginTime AS DATE) = CAST(GETDATE() AS DATE)
        ORDER BY LoginTime ASC
    """, worker_id)

    logs = cursor.fetchall()

    total_minutes_worked = 0
    now = datetime.now()

    for login_time, logout_time in logs:
        actual_end = logout_time if logout_time else now
        actual_start = max(login_time, shift_start)
        actual_end = min(actual_end, shift_end)

        if actual_end > actual_start:
            total_minutes_worked += int((actual_end - actual_start).total_seconds() / 60)

    shift_minutes = int((shift_end - shift_start).total_seconds() / 60)

    if now >= shift_end:
        minutes_remaining = "Shift Ended"
    else:
        minutes_remaining = max(shift_minutes - total_minutes_worked, 0)

    return jsonify({
        "first_name": first,
        "last_name": last,
        "start": start.strftime("%I:%M %p"),
        "end": end.strftime("%I:%M %p"),
        "minutes_worked": total_minutes_worked,
        "minutes_remaining": minutes_remaining
    })

@app.route("/get_all_workers")
def get_all_workers():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Worker_ID, Worker_FirstName, Worker_LastName
        FROM Student_Worker
        ORDER BY Worker_FirstName, Worker_LastName
    """)

    workers = []
    for row in cursor.fetchall():
        workers.append({
            "worker_id": row[0],
            "first_name": row[1],
            "last_name": row[2]
        })

    return jsonify({"workers": workers})


# ---------------------------------------------------------
# CSV Upload (Replace Student Table)
# ---------------------------------------------------------
@app.route("/upload_csv_replace", methods=["POST"])
def upload_csv_replace():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"})

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)

        rows = list(reader)
        if not rows:
            return jsonify({"error": "CSV file is empty"})

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM dbo.Student")

        for row in rows:
            try:
                student_id = int(row.get("Student ID", 0))
            except:
                continue

            last_access_raw = row.get("Last Access", "").strip()
            last_access = last_access_raw if last_access_raw != "" else None

            lw_raw = row.get("Liability_Waivers", "").strip()
            if lw_raw == "":
                liability = None
            else:
                try:
                    liability = int(float(lw_raw))
                except:
                    liability = None

            cursor.execute("""
                INSERT INTO dbo.Student
                    (Student_ID, Last_Name, First_Name, Username,
                     Last_Access, Availability, Liability_Waivers)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                student_id,
                row.get("Last Name", ""),
                row.get("First Name", ""),
                row.get("Username", ""),
                last_access,
                row.get("Availability", ""),
                liability
            )

        conn.commit()
        conn.close()

        return jsonify({"success": True, "inserted": len(rows)})

    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"})

# ---------------------------------------------------------
# API: Signed-In Users (for Professor Dashboard)
# ---------------------------------------------------------
@app.route("/api/signed_in_users")
def api_signed_in_users():
    users = get_signed_in_users()

    for u in users:
        if isinstance(u["login"], datetime):
            u["login"] = u["login"].strftime("%I:%M %p")

    return jsonify(users)

# ---------------------------------------------------------
# Logout User (from Professor Dashboard)
# ---------------------------------------------------------
@app.route("/logout_user", methods=["POST"])
def logout_user():
    student_id = request.form.get("student_id")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT TOP 1 LoginTime
        FROM Attendance_Log
        WHERE Attendance_ID = ?
          AND LogoutTime IS NULL
        ORDER BY LoginTime DESC
    """, student_id)

    active = cursor.fetchone()

    if active:
        cursor.execute("""
            UPDATE Attendance_Log
            SET LogoutTime = GETDATE()
            WHERE Attendance_ID = ?
              AND LogoutTime IS NULL
        """, student_id)
        conn.commit()

    conn.close()

    return redirect("/professor_home")

# ---------------------------------------------------------
# Run App
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
