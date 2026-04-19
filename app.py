from flask import Flask, request, render_template, redirect, jsonify, Response, session, url_for
# Used to connect to Azure SQL database
import pyodbc      
import io
import zipfile
import smtplib
import random
import time
from email.mime.text import MIMEText
from datetime import datetime

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

# Wraps the connection so it can be easily reused
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


PROFESSOR_EMAIL = "bayley.test2@gmail.com"  # change to real email
SMTP_SERVER = "smtp.gmail.com"             # or your mail server
SMTP_PORT = 587
SMTP_USER = "bayley.test2@gmail.com"       # sending account
SMTP_PASS = "ohrh dzwx bfoh mssj"            # app password / SMTP password


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
# Used to store the professor ID that is currently logged in,
# this is used to aide with logging out with professor_logout route
current_professor_id = None
#worker_id = None

# ---------------------------------------------------------
# Home Page Route
# ---------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# ---------------------------------------------------------
# Check-In / Check-Out Route
# ---------------------------------------------------------
@app.route("/checkin", methods=["POST"])
def checkin():
    global current_professor_id

    student_id = request.form.get("student_id")

    # Clean swipe if raw track data appears
    if ";" in student_id and "=" in student_id:
        # Splits the track data
        track2 = student_id.split(";")[1]
        # Removes the ? from the end
        discretionary = track2.split("=")[1].replace("?", "")
        # Takes the last 6 digits ands stores it as the ID
        student_id = discretionary[-6:]

    # Convert to INT
    try:
        student_id = int(student_id)
    except:
        # If the value is not numerical then an error is sent
        return {"message": "Invalid card swipe format"}

    
    try:
        # Connection is opened
        conn = connect_db()
        # Cursor is used to run SQL queries
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

            # Store professor ID for logout button
            current_professor_id = student_id

            # -------------------------------------------------
            # 2FA: generate and email code
            # -------------------------------------------------
            code = random.randint(100000, 999999)
            session["prof_2fa_code"] = str(code)
            session["prof_2fa_expiry"] = time.time() + 300  # 5 minutes
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

                # Force Attendance_ID to be Worker_ID
                cursor.execute("""
                    SELECT Worker_ID
                    FROM dbo.Student_Worker
                    WHERE Worker_ID = ?
                """, student_id)

                worker_row = cursor.fetchone()
                if worker_row:
                    student_id = worker_row[0]

                # Store worker ID in session
                session["worker_id"] = student_id
                session["worker_name"] = f"{first_name} {last_name}"
                session["worker_email"] = worker_email


                # -------------------------------
                # 2FA for Student Worker
                # -------------------------------
                code = random.randint(100000, 999999)
                session["worker_2fa_code"] = str(code)
                session["worker_2fa_expiry"] = time.time() + 300  # 5 minutes
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

                # If the waiver is not signed then block entry
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
        # Used for logging in and out
        current_time = datetime.now()

        # -------------------------------------------------
        # Role redirect mapping
        # -------------------------------------------------
        role_redirects = {
            "Professor": "/professor_2fa",
            "StudentWorker": "/worker_2fa",
            "Student": "/student_home"
        }


        # Default for if a role is not found (shouldn't happen but just in case)
        redirect_url = role_redirects.get(role, "/student_home")

        # -------------------------------------------------
        # LOG OUT
        # -------------------------------------------------
        # If the user already has an active session then the logout time is set to now
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
# Professor Dashboard
# ---------------------------------------------------------
@app.route("/professor_2fa", methods=["GET", "POST"])
def professor_2fa():
    if "prof_2fa_code" not in session:
        return redirect("/")

    # Needed for resend functionality
    session["pending_prof_email"] = PROFESSOR_EMAIL

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

@app.route("/professor_home")
def professor_home():
    if not session.get("professor_authenticated"):
        return redirect("/professor_2fa")

    return render_template("professor_home.html")

# ---------------------------------------------------------
# Professor Search Route
# ---------------------------------------------------------
@app.route("/professor_search", methods=["POST"])
def professor_search():
    search_value = request.form.get("student_id").strip()

    # Split input by spaces to detect full name searches
    parts = search_value.split()

    try:
        conn = connect_db()
        cursor = conn.cursor()

        # ---------------------------------------------------------
        # CASE 1: Search by Student ID (all digits)
        # ---------------------------------------------------------
        if search_value.isdigit():
            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE Student_ID = ?
            """, int(search_value))

        # ---------------------------------------------------------
        # CASE 2: Full name search (two words)
        # ---------------------------------------------------------
        elif len(parts) == 2:
            first, last = parts[0], parts[1]

            cursor.execute("""
                SELECT Student_ID, First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE LOWER(First_Name) = LOWER(?)
                  AND LOWER(Last_Name) = LOWER(?)
            """, first, last)

        # ---------------------------------------------------------
        # CASE 3: Single name search (first OR last)
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # Fetch attendance history
        # ---------------------------------------------------------
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

        # Get top 5 students by total time spent in the last 7 days
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
# ---------------------------------------------------------
# Professor Logout Route (Updated for 2FA)
# ---------------------------------------------------------
@app.route("/professor_logout")
def professor_logout():
    global current_professor_id

    try:
        # If professor was logged in (attendance-wise), close their session
        if current_professor_id is not None:
            conn = connect_db()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE dbo.Attendance_Log
                SET LogoutTime = ?
                WHERE Attendance_ID = ? AND LogoutTime IS NULL
            """, datetime.now(), current_professor_id)

            conn.commit()
            conn.close()

        # ---------------------------------------------------------
        # Clear ALL professor-related session data
        # ---------------------------------------------------------
        session.pop("professor_authenticated", None)
        session.pop("professor_id", None)
        session.pop("professor_name", None)
        session.pop("prof_2fa_code", None)
        session.pop("prof_2fa_expiry", None)

        # Clear global ID used for attendance tracking
        current_professor_id = None

        # Back to main check-in page
        return redirect("/")

    except Exception as e:
        return f"Error logging out: {str(e)}"




# ---------------------------------------------------------
# MONTHLY CSV EXPORT
# ---------------------------------------------------------
@app.route("/export_monthly_csv")
def export_monthly_csv():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            SUM(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS TotalMinutes,
            COUNT(*) AS TotalVisits,
            AVG(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS AvgSessionLength,
            SUM(CASE WHEN a.WaiverOverrideUsed = 1 THEN 1 ELSE 0 END) AS OverrideCount,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 1 ELSE 0 END AS IsStudentWorker
        FROM Attendance_Log a
        JOIN Student s ON a.Attendance_ID = s.Student_ID
        LEFT JOIN Student_Worker sw ON sw.Worker_ID = s.Student_ID
        WHERE a.LoginTime >= DATEADD(DAY, -30, GETDATE())
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name, sw.Worker_ID
        ORDER BY TotalMinutes DESC;
    """)

    rows = cursor.fetchall()

    output = "Student_ID,First_Name,Last_Name,TotalMinutes,TotalVisits,AvgSessionLength,OverrideCount,FLAG,StudentWorker\n"
    for r in rows:
        flag = "FLAG" if r[6] > 0 else ""
        student_worker = "YES" if r[7] == 1 else ""
        output += f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},{r[6]},{flag},{student_worker}\n"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=monthly_report.csv"}
    )


# ---------------------------------------------------------
# RAW LOGS CSV EXPORT (with month filter + no professors)
# ---------------------------------------------------------
@app.route("/export_raw_logs_csv")
def export_raw_logs_csv():
    month_param = request.args.get("month", "").strip()

    # Build month filter
    month_filter_sql = ""
    month_filter_value = None

    if month_param:
        if month_param.isdigit():
            month_filter_sql = "AND MONTH(a.LoginTime) = ?"
            month_filter_value = int(month_param)
        elif "-" in month_param:
            try:
                year, month = month_param.split("-")
                month_filter_sql = "AND YEAR(a.LoginTime) = ? AND MONTH(a.LoginTime) = ?"
                month_filter_value = (int(year), int(month))
            except:
                pass

    conn = connect_db()
    cursor = conn.cursor()

    # RAW LOGS QUERY (students only, no professors)
    base_query = f"""
        SELECT 
            a.Attendance_ID,
            s.First_Name,
            s.Last_Name,
            a.LoginTime,
            a.LogoutTime,
            CAST(a.LoginTime AS DATE) AS SignInDate,
            DATENAME(month, a.LoginTime) AS MonthName,
            MONTH(a.LoginTime) AS MonthNumber,
            DATEPART(week, a.LoginTime) AS WeekNumber,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 1 ELSE 0 END AS IsStudentWorker,
            a.WaiverOverrideUsed,
            w.Worker_FirstName,
            w.Worker_LastName
        FROM Attendance_Log a
        LEFT JOIN Student s ON a.Attendance_ID = s.Student_ID
        LEFT JOIN Student_Worker sw ON sw.Worker_ID = a.Attendance_ID
        LEFT JOIN Student_Worker w ON w.Worker_ID = a.OverrideGrantedByWorkerID
        WHERE a.Attendance_ID NOT IN (SELECT Teacher_ID FROM Professor)
        {month_filter_sql}
        ORDER BY a.LoginTime DESC;
    """

    if month_filter_value is None:
        cursor.execute(base_query)
    else:
        if isinstance(month_filter_value, tuple):
            cursor.execute(base_query, month_filter_value[0], month_filter_value[1])
        else:
            cursor.execute(base_query, month_filter_value)

    rows = cursor.fetchall()
    conn.close()

    # BUILD CSV
    output = (
        "Student_ID,First_Name,Last_Name,LoginTime,LogoutTime,SignInDate,"
        "MonthName,MonthNumber,WeekNumber,StudentWorker,FLAG,OverrideGrantedBy\n"
    )

    for r in rows:
        student_id = r[0]
        first = r[1] or ""
        last = r[2] or ""
        login = r[3]
        logout = r[4] or ""
        sign_in_date = r[5]
        month_name = r[6]
        month_number = r[7]
        week_number = r[8]
        is_worker = "YES" if r[9] == 1 else ""
        flag = "FLAG" if r[10] == 1 else ""
        override_by = f"{r[11]} {r[12]}" if r[11] else ""

        output += (
            f"{student_id},{first},{last},{login},{logout},{sign_in_date},"
            f"{month_name},{month_number},{week_number},"
            f"{is_worker},{flag},{override_by}\n"
        )

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=raw_attendance_logs.csv"}
    )


# ---------------------------------------------------------
# ZIP EXPORT (monthly + raw logs)
# ---------------------------------------------------------
@app.route("/export_all_csv")
def export_all_csv():
    conn = connect_db()
    cursor = conn.cursor()

    # ---------- MONTHLY CSV ----------
    cursor.execute("""
        SELECT 
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            SUM(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS TotalMinutes,
            COUNT(*) AS TotalVisits,
            AVG(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS AvgSessionLength,
            SUM(CASE WHEN a.WaiverOverrideUsed = 1 THEN 1 ELSE 0 END) AS OverrideCount,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 1 ELSE 0 END AS IsStudentWorker
        FROM Attendance_Log a
        JOIN Student s ON a.Attendance_ID = s.Student_ID
        LEFT JOIN Student_Worker sw ON sw.Worker_ID = s.Student_ID
        WHERE a.LoginTime >= DATEADD(DAY, -30, GETDATE())
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name, sw.Worker_ID
        ORDER BY TotalMinutes DESC;
    """)

    monthly_rows = cursor.fetchall()

    monthly_csv = "Student_ID,First_Name,Last_Name,TotalMinutes,TotalVisits,AvgSessionLength,OverrideCount,FLAG,StudentWorker\n"
    for r in monthly_rows:
        flag = "FLAG" if r[6] > 0 else ""
        student_worker = "YES" if r[7] == 1 else ""
        monthly_csv += f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},{r[6]},{flag},{student_worker}\n"

    # ---------- RAW LOGS CSV ----------
    cursor.execute("""
        SELECT 
            a.Attendance_ID,
            s.First_Name,
            s.Last_Name,
            a.LoginTime,
            a.LogoutTime,
            CAST(a.LoginTime AS DATE) AS SignInDate,
            CASE WHEN sw.Worker_ID IS NOT NULL THEN 1 ELSE 0 END AS IsStudentWorker,
            a.WaiverOverrideUsed,
            w.Worker_FirstName,
            w.Worker_LastName
        FROM Attendance_Log a
        LEFT JOIN Student s ON a.Attendance_ID = s.Student_ID
        LEFT JOIN Student_Worker sw ON sw.Worker_ID = a.Attendance_ID
        LEFT JOIN Student_Worker w ON w.Worker_ID = a.OverrideGrantedByWorkerID
        WHERE a.Attendance_ID NOT IN (SELECT Teacher_ID FROM Professor)
        ORDER BY a.LoginTime DESC;
    """)

    raw_rows = cursor.fetchall()
    conn.close()

    raw_csv = (
        "Student_ID,First_Name,Last_Name,LoginTime,LogoutTime,SignInDate,"
        "StudentWorker,FLAG,OverrideGrantedBy\n"
    )

    for r in raw_rows:
        is_worker = "YES" if r[6] == 1 else ""
        flag = "FLAG" if r[7] == 1 else ""
        override_by = f"{r[8]} {r[9]}" if r[8] else ""
        raw_csv += (
            f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},"
            f"{is_worker},{flag},{override_by}\n"
        )

    # ---------- BUILD ZIP ----------
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("monthly_report.csv", monthly_csv)
        zip_file.writestr("raw_attendance_logs.csv", raw_csv)

    zip_buffer.seek(0)

    return Response(
        zip_buffer,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment;filename=attendance_reports.zip"}
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

    # Get today's worker
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

    # Build shift window BEFORE calculating logs
    shift_start = datetime.combine(datetime.today(), start)
    shift_end = datetime.combine(datetime.today(), end)

    # Get today's logs
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
        # Determine actual end time
        actual_end = logout_time if logout_time else now

        # Clamp to shift window
        actual_start = max(login_time, shift_start)
        actual_end = min(actual_end, shift_end)

        # Only count positive time
        if actual_end > actual_start:
            total_minutes_worked += int((actual_end - actual_start).total_seconds() / 60)

    # Shift duration
    shift_minutes = int((shift_end - shift_start).total_seconds() / 60)

    # Remaining time
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

    # ---------------------------------------------------------
    # Get ALL attendance logs for this worker for TODAY
    # ---------------------------------------------------------
    cursor.execute("""
        SELECT LoginTime, LogoutTime
        FROM Attendance_Log
        WHERE Attendance_ID = ?
            AND LoginTime >= DATEADD(HOUR, -24, GETDATE())
        ORDER BY LoginTime ASC
    """, worker_id)

    logs = cursor.fetchall()

    total_minutes_worked = 0
    now = datetime.now()

    for login_time, logout_time in logs:
        # Determine the actual end time (logout or now)
        actual_end = logout_time if logout_time else now

        # Clamp the interval to the shift window
        actual_start = max(login_time, shift_start)
        actual_end = min(actual_end, shift_end)

        # Only count positive time
        if actual_end > actual_start:
            total_minutes_worked += int((actual_end - actual_start).total_seconds() / 60)


    # ---------------------------------------------------------
    # Calculate shift minutes
    # ---------------------------------------------------------
    shift_start = datetime.combine(datetime.today(), start)
    shift_end = datetime.combine(datetime.today(), end)
    shift_minutes = int((shift_end - shift_start).total_seconds() / 60)

    # Determine remaining time
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


@app.route("/assign_worker_schedule", methods=["POST"])
def assign_worker_schedule():
    worker_id = request.form.get("worker_id")
    day = request.form.get("day")
    start = request.form.get("start_time")
    end = request.form.get("end_time")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        MERGE Student_Worker_Schedule AS t
        USING (SELECT ? AS Worker_ID, ? AS DayOfWeek) AS s
        ON t.Worker_ID = s.Worker_ID AND t.DayOfWeek = s.DayOfWeek
        WHEN MATCHED THEN 
            UPDATE SET StartTime = ?, EndTime = ?
        WHEN NOT MATCHED THEN
            INSERT (Worker_ID, DayOfWeek, StartTime, EndTime)
            VALUES (?, ?, ?, ?);
    """, worker_id, day, start, end, worker_id, day, start, end)

    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Shift assigned successfully"})

    
@app.route("/get_all_workers")
def get_all_workers():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Worker_ID, Worker_FirstName, Worker_LastName
        FROM Student_Worker
    """)

    workers = [
        {"worker_id": row[0], "first_name": row[1], "last_name": row[2]}
        for row in cursor.fetchall()
    ]

    conn.close()
    return jsonify({"workers": workers})


@app.route("/worker_2fa", methods=["GET", "POST"])
def worker_2fa():
    if "worker_2fa_code" not in session:
        return redirect("/")

    # Needed for resend functionality
    session["pending_worker_email"] = session.get("worker_email")

    if request.method == "POST":
        entered = request.form.get("code", "").strip()
        real_code = session.get("worker_2fa_code")
        expiry = session.get("worker_2fa_expiry", 0)

        if not real_code or time.time() > expiry:
            session.pop("worker_2fa_code", None)
            session.pop("worker_2fa_expiry", None)
            return render_template("worker_2fa.html",
                                   error="Code expired. Please swipe again.")

        if entered == real_code:
            session["worker_authenticated"] = True
            session.pop("worker_2fa_code", None)
            session.pop("worker_2fa_expiry", None)
            return redirect("/student_worker")

        return render_template("worker_2fa.html",
                               error="Invalid code. Please try again.")

    return render_template("worker_2fa.html")



@app.route("/resend_2fa_code", methods=["POST"])
def resend_2fa_code():
    email = session.get("pending_prof_email") or session.get("pending_worker_email")

    if not email:
        return jsonify({"success": False, "message": "No pending login session found."})

    new_code = str(random.randint(100000, 999999))
    expiry = time.time() + 300  # 5 minutes

    # Update the correct session keys
    if session.get("pending_prof_email"):
        session["prof_2fa_code"] = new_code
        session["prof_2fa_expiry"] = expiry
    else:
        session["worker_2fa_code"] = new_code
        session["worker_2fa_expiry"] = expiry

    send_2fa_email(email, new_code)

    return jsonify({"success": True, "message": "A new code has been sent to your email."})





@app.route("/make_student_worker", methods=["POST"])
def make_student_worker():
    student_id = request.form.get("student_id")
    email = request.form.get("email")

    try:
        student_id = int(student_id)
    except:
        return jsonify({"success": False, "message": "Invalid student ID"})

    if not email:
        return jsonify({"success": False, "message": "Email is required"})

    conn = connect_db()
    cursor = conn.cursor()

    # Get student info
    cursor.execute("""
        SELECT First_Name, Last_Name
        FROM Student
        WHERE Student_ID = ?
    """, student_id)

    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Student not found"})

    first, last = row

    # Check if already a worker
    cursor.execute("SELECT Worker_ID FROM Student_Worker WHERE Worker_ID = ?", student_id)
    exists = cursor.fetchone()

    if not exists:
        cursor.execute("""
            INSERT INTO Student_Worker (Worker_ID, Worker_FirstName, Worker_LastName, Worker_Email)
            VALUES (?, ?, ?, ?)
        """, student_id, first, last, email)
        conn.commit()

    conn.close()

    return jsonify({"success": True, "message": "Student promoted to Student Worker"})


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
    if not session.get("worker_authenticated"):
        return redirect("/worker_2fa")
    
    return render_template("student_worker.html")




# ---------------------------------------------------------
# SEARCH (Updated)
# ---------------------------------------------------------
@app.route("/worker_search", methods=["GET", "POST"])
def worker_search():
    users = get_signed_in_users()  # <-- MUST be here for both GET and POST

    if request.method == "GET":
        # GET should behave like POST when redirected from override
        search_input = request.args.get("student_id", "")
        if not search_input:
            return redirect("/student_worker")
    else:
        search_input = request.form.get("student_id", "").strip()

    if not search_input:
        return render_template("student_worker.html", users=users, error="Please enter a name or ID")

    conn = connect_db()
    cursor = conn.cursor()

    # --- Search logic (ID or name) ---
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

    # --- Check temporary override ---
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

    # Get student info
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

    # Check override
    cursor.execute("""
        SELECT Override_Date
        FROM Temporary_Waiver_Override
        WHERE Student_ID = ?
    """, student_id)

    override = cursor.fetchone()
    today = datetime.now().date()
    override_valid = override and override[0] == today

    # Enforce waiver rules
    if waiver != 1 and not override_valid:
        conn.close()
        return redirect("/student_worker")

    # Determine override flags for logging
    worker_id = session.get("worker_id")
    if waiver == 1:
        waiver_override_used = 0
        override_worker_id = None
    else:
        # waiver not signed, but override_valid is True here
        waiver_override_used = 1
        override_worker_id = worker_id

    # Check if already signed in
    cursor.execute("""
        SELECT LoginTime
        FROM dbo.Attendance_Log
        WHERE Attendance_ID = ? AND LogoutTime IS NULL
    """, student_id)

    active = cursor.fetchone()
    if active:
        conn.close()
        return redirect("/student_worker")

    # Sign in
    now = datetime.now()
    cursor.execute("""
        INSERT INTO dbo.Attendance_Log
        (Att_FirstName, Att_LastName, Attendance_ID, LoginTime, LogoutTime, WaiverOverrideUsed, OverrideGrantedByWorkerID)
        VALUES (?, ?, ?, ?, NULL, ?, ?)
    """, first_name, last_name, student_id, now, waiver_override_used, override_worker_id)

    conn.commit()
    conn.close()

    return redirect("/student_worker")

# ---------------------------------------------------------
# FORCE LOGOUT (Updated)
# ---------------------------------------------------------
@app.route("/force_logout", methods=["POST"])
def force_logout():
    """
    Force logout a student by setting their LogoutTime to now.
    """
    student_id = request.form.get("student_id")

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE dbo.Attendance_Log
        SET LogoutTime = ?
        WHERE Attendance_ID = ? AND LogoutTime IS NULL
    """, datetime.now(), student_id)
    conn.commit()
    conn.close()

    return redirect("/student_worker")


# ---------------------------------------------------------
# LOGOUT ALL USERS
# ---------------------------------------------------------
@app.route("/force_logout_all", methods=["POST"])
def force_logout_all():
    # 1. Log out everyone
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE dbo.Attendance_Log
        SET LogoutTime = ?
        WHERE LogoutTime IS NULL
    """, datetime.now())

    conn.commit()
    conn.close()

    # 2. Clear worker session if they are logged in
    session.pop("worker_id", None)

    # 3. Redirect to home page
    return redirect("/")


# ---------------------------------------------------------
# WORKER LOGOUT (Updated for 2FA)
# ---------------------------------------------------------
@app.route("/worker_logout")
def worker_logout():
    worker_id = session.get("worker_id")

    try:
        # If worker has an active attendance session, close it
        if worker_id:
            conn = connect_db()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE dbo.Attendance_Log
                SET LogoutTime = ?
                WHERE Attendance_ID = ? AND LogoutTime IS NULL
            """, datetime.now(), worker_id)

            conn.commit()
            conn.close()

        # ---------------------------------------------------------
        # Clear ALL worker-related session data
        # ---------------------------------------------------------
        session.pop("worker_id", None)
        session.pop("worker_name", None)
        session.pop("worker_authenticated", None)
        session.pop("worker_2fa_code", None)
        session.pop("worker_2fa_expiry", None)

        # Return to main check-in page
        return redirect("/")

    except Exception as e:
        return f"Error logging out: {str(e)}"




# ---------------------------------------------------------
# Overrides student waiver sign in
# ---------------------------------------------------------
@app.route("/override_waiver", methods=["POST"])
def override_waiver():
    student_id = request.form.get("student_id")
    worker_id = session.get("worker_id")   # ← IMPORTANT

    if not worker_id:
        return redirect("/student_worker")  # worker not logged in

    conn = connect_db()
    cursor = conn.cursor()

    # Insert or update override WITH worker ID
    cursor.execute("""
        MERGE dbo.Temporary_Waiver_Override AS t
        USING (SELECT ? AS Student_ID, ? AS Worker_ID) AS s
        ON t.Student_ID = s.Student_ID
        WHEN MATCHED THEN 
            UPDATE SET Override_Date = CAST(GETDATE() AS DATE),
                       Worker_ID = s.Worker_ID
        WHEN NOT MATCHED THEN 
            INSERT (Student_ID, Override_Date, Worker_ID)
            VALUES (s.Student_ID, CAST(GETDATE() AS DATE), s.Worker_ID);
    """, student_id, worker_id)

    conn.commit()
    conn.close()

    return redirect(url_for("worker_search", student_id=student_id), code=307)


@app.route("/api/signed_in_users")
def api_signed_in_users():
    users = get_signed_in_users()

    # Convert datetimes to strings
    for u in users:
        if isinstance(u["login"], datetime):
            u["login"] = u["login"].strftime("%I:%M %p")

    return jsonify(users)



@app.route("/logout_user", methods=["POST"])
def logout_user():
    student_id = request.form.get("student_id")

    conn = connect_db()
    cursor = conn.cursor()

    # Find active session
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

@app.route("/monthly_dashboard_data")
def monthly_dashboard_data():
    conn = connect_db()
    cursor = conn.cursor()

    # Student totals
    cursor.execute("""
        SELECT 
            s.Student_ID,
            s.First_Name,
            s.Last_Name,
            SUM(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS TotalMinutes,
            COUNT(*) AS TotalVisits,
            AVG(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS AvgSessionLength
        FROM Attendance_Log a
        JOIN Student s ON a.Attendance_ID = s.Student_ID
        WHERE a.LoginTime >= DATEADD(DAY, -30, GETDATE())
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name
        ORDER BY TotalMinutes DESC;
    """)

    student_rows = cursor.fetchall()

    students = []
    for r in student_rows:
        students.append({
            "id": r[0],
            "first": r[1],
            "last": r[2],
            "minutes": r[3],
            "visits": r[4],
            "avg_session": r[5]
        })

    # Daily totals
    cursor.execute("""
        SELECT 
            CAST(LoginTime AS DATE) AS Day,
            SUM(DATEDIFF(MINUTE, LoginTime, ISNULL(LogoutTime, GETDATE()))) AS TotalMinutes
        FROM Attendance_Log
        WHERE LoginTime >= DATEADD(DAY, -30, GETDATE())
        GROUP BY CAST(LoginTime AS DATE)
        ORDER BY Day ASC;
    """)

    daily_rows = cursor.fetchall()

    daily = []
    for r in daily_rows:
        daily.append({
            "day": r[0].strftime("%Y-%m-%d"),
            "minutes": r[1]
        })

    return jsonify({
        "students": students,
        "daily": daily
    })

# ---------------------------------------------------------
# Run App
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
