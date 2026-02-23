from flask import Flask, request, render_template, redirect
import pyodbc
from datetime import datetime

app = Flask(__name__)

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
# TEMPORARY STORAGE FOR PROFESSOR ID (simple + no sessions)
# ---------------------------------------------------------
current_professor_id = None

# ---------------------------------------------------------
# Home Page
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
        track2 = student_id.split(";")[1]
        discretionary = track2.split("=")[1].replace("?", "")
        student_id = discretionary[-6:]

    # Convert to INT
    try:
        student_id = int(student_id)
    except:
        return {"message": "Invalid card swipe format"}

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

            # ⭐ Store professor ID for logout button
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
            "Professor": "/professor_home",
            "StudentWorker": "/worker_home",
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
    student_id = request.form.get("student_id")

    try:
        student_id = int(student_id)
    except:
        return {"error": "Invalid student ID format"}

    try:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT First_Name, Last_Name, Liability_Waivers
            FROM dbo.Student
            WHERE Student_ID = ?
        """, student_id)

        student = cursor.fetchone()

        if not student:
            conn.close()
            return {"error": "Student not found"}

        first_name, last_name, waiver = student
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
# Logs out professor + redirects
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

        current_professor_id = None  # clear stored ID

        return redirect("/")

    except Exception as e:
        return f"Error logging out: {str(e)}"

# ---------------------------------------------------------
# Worker & Student Pages
# ---------------------------------------------------------
@app.route("/worker_home")
def worker_home():
    return "<h1>Student Worker Dashboard</h1>"

@app.route("/student_home")
def student_home():
    return "<h1>Student Home</h1>"

# ---------------------------------------------------------
# Run App
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
