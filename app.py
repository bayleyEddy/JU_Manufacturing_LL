from flask import Flask, request, render_template, redirect, jsonify, Response, session, url_for
# Used to connect to Azure SQL database
import pyodbc      
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

        else:
            # -------------------------------------------------
            # 2. CHECK STUDENT WORKER TABLE
            # -------------------------------------------------
            cursor.execute("""
                SELECT Worker_FirstName, Worker_LastName
                FROM dbo.Student_Worker
                WHERE Worker_ID = ?
            """, student_id)

            worker = cursor.fetchone()

            if worker:
                role = "StudentWorker"
                first_name, last_name = worker
                waiver = 1

                # Force Attendance_ID to be Worker_ID
                cursor.execute("""
                    SELECT Worker_ID
                    FROM dbo.Student_Worker
                    WHERE Worker_ID = ?
                """, student_id)

                worker_row = cursor.fetchone()
                if worker_row:
                    student_id = worker_row[0]  # overwrite with Worker_ID

                # Store worker ID in session for logout
                session["worker_id"] = student_id


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
            "Professor": "/professor_home",
            "StudentWorker": "/student_worker",
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
            (Att_FirstName, Att_LastName, Attendance_ID, LoginTime, LogoutTime)
            VALUES (?, ?, ?, ?, NULL)
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
@app.route("/professor_home")
def professor_home():
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
@app.route("/professor_logout")
def professor_logout():
    global current_professor_id

    # If no professor is stored, just go back to home
    if current_professor_id is None:
        return redirect("/")

    try:
        conn = connect_db()
        cursor = conn.cursor()

        # Close any active session for this professor
        cursor.execute("""
            UPDATE dbo.Attendance_Log
            SET LogoutTime = ?
            WHERE Attendance_ID = ? AND LogoutTime IS NULL
        """, datetime.now(), current_professor_id)

        conn.commit()
        conn.close()

        # Clear the stored professor ID
        current_professor_id = None

        # Send them back to the main check-in page
        return redirect("/")

    except Exception as e:
        return f"Error logging out: {str(e)}"



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
            AVG(DATEDIFF(MINUTE, a.LoginTime, ISNULL(a.LogoutTime, GETDATE()))) AS AvgSessionLength
        FROM Attendance_Log a
        JOIN Student s ON a.Attendance_ID = s.Student_ID
        WHERE a.LoginTime >= DATEADD(DAY, -30, GETDATE())
        GROUP BY s.Student_ID, s.First_Name, s.Last_Name
        ORDER BY TotalMinutes DESC;
    """)

    rows = cursor.fetchall()

    output = "Student_ID,First_Name,Last_Name,TotalMinutes,TotalVisits,AvgSessionLength\n"
    for r in rows:
        output += f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}\n"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=monthly_report.csv"}
    )





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
        if logout_time is None:
            total_minutes_worked += int((now - login_time).total_seconds() / 60)
        else:
            total_minutes_worked += int((logout_time - login_time).total_seconds() / 60)

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
        (Att_FirstName, Att_LastName, Attendance_ID, LoginTime, LogoutTime)
        VALUES (?, ?, ?, ?, NULL)
    """, first_name, last_name, student_id, now)

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

    # Clear worker session
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
        MERGE dbo.Temporary_Waiver_Override AS t
        USING (SELECT ? AS Student_ID) AS s
        ON t.Student_ID = s.Student_ID
        WHEN MATCHED THEN UPDATE SET Override_Date = CAST(GETDATE() AS DATE)
        WHEN NOT MATCHED THEN INSERT (Student_ID, Override_Date)
        VALUES (s.Student_ID, CAST(GETDATE() AS DATE));
    """, student_id)

    conn.commit()
    conn.close()

    # Redirect back to worker_search WITH student_id
    return redirect(url_for("worker_search", student_id=student_id), code=307)



# ---------------------------------------------------------
# Run App
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
