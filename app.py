from flask import Flask, request, render_template
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
# Home Page
# ---------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# ---------------------------------------------------------
# Check-In / Check-Out Route (with Roles)
# ---------------------------------------------------------
@app.route("/checkin", methods=["POST"])
def checkin():
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
        # Determine User Role
        # -------------------------------------------------
        cursor.execute("""
            SELECT Role
            FROM dbo.User_Roles
            WHERE User_ID = ?
        """, student_id)

        role_row = cursor.fetchone()
        role = role_row[0] if role_row else "Student"

        # -------------------------------------------------
        # Lookup user based on role
        # -------------------------------------------------
        if role == "Professor":
            cursor.execute("""
                SELECT FirstName, LastName
                FROM dbo.Professor
                WHERE Teacher_ID = ?
            """, student_id)

            prof = cursor.fetchone()
            if not prof:
                conn.close()
                return {"message": "Professor ID not found"}

            first_name, last_name = prof
            waiver = 1  # professors always allowed

        else:
            # Student or StudentWorker
            cursor.execute("""
                SELECT First_Name, Last_Name, Liability_Waivers
                FROM dbo.Student
                WHERE Student_ID = ?
            """, student_id)

            student = cursor.fetchone()
            if not student:
                conn.close()
                return {"message": "Student ID not found"}

            first_name, last_name, waiver = student

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
# Role-Based Homepages
# ---------------------------------------------------------
@app.route("/professor_home")
def professor_home():
    return "<h1>Professor Dashboard</h1>"

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
