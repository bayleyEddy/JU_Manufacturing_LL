from flask import Flask, request, render_template
import sqlite3
from pathlib import Path
import csv
from datetime import datetime

# Creates a Flask web app instance (web server)
app = Flask(__name__)

# Path for database table
DB_Path = "bridge_troll.db"
# Path for csv file containing necessary student information
CSV_Path = Path("student_data/gc_JUID_ULTRA_Manufacturing_Lab_Safety_Training_columns_2026-01-22-14-39-36.csv")

#--------------------------------------------------------------------------------------------------------------------------
# Initializing database
def initialize_database():
    # Creates a connection object to interact with the SQLite database
    connect_to_db = sqlite3.connect(DB_Path)
    # Creates a cursor object that lets us execute SQL commands
    db_cursor = connect_to_db.cursor()

    # execute() will run SQL commands on the database
    # Student info table will be created if it doesn't exist
    # Stores basic student information which will be pulled from csv file
    db_cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            waiver_signed TEXT
        )
    """)

    # Login records table is created if it doesn't exist
    # Tracks logins and logouts
    db_cursor.execute("""
        CREATE TABLE IF NOT EXISTS logins (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            student_id TEXT NOT NULL,
            login_time TEXT,
            logout_time TEXT,
            FOREIGN KEY(student_id) REFERENCES students(student_id)
        )                  
    """)

    # commit() saves all changes made to the database permanently
    connect_to_db.commit()
    # close() closes the database connecion to free up resources
    connect_to_db.close()


#--------------------------------------------------------------------------------------------------------------------------
# Importing CSV file
def import_csv():
    connect_to_db = sqlite3.connect(DB_Path)
    db_cursor = connect_to_db.cursor()

    # Open and read the CSV file containing students data
    with CSV_Path.open("r", encoding="utf-8") as file:
        reader = csv.reader(file)
        # Skips the header row
        header = next(reader)

        # Loops through each row in the CSV file
        for row in reader:
            last_name = row[0].strip()
            first_name = row[1].strip()
            student_id = row[3].strip()
            waiver_signed = row[10].strip()
            
            # INSERT OR IGNORE means to add the data, but to skip it if the student_id already exists
            # ? are used as placeholders to prevent SQL injection attacks
            db_cursor.execute("""
                    INSERT OR IGNORE INTO students (student_id, first_name, last_name, waiver_signed)
                    VALUES (?, ?, ?, ?)
            """, (student_id, first_name, last_name, waiver_signed))
    
    connect_to_db.commit()
    connect_to_db.close()

#--------------------------------------------------------------------------------------------------------------------------
# Login Functionality
def record_login(student_id):
    connect_to_db = sqlite3.connect(DB_Path)
    db_cursor = connect_to_db.cursor()

    # Get the current date and time as a string for login
    login_time = datetime.now().isoformat(timespec="seconds")

    # Add a new login record to the database
    db_cursor.execute("""
        INSERT INTO logins (student_id, login_time)
        Values (?, ?)
    """, (student_id, login_time))

    # Save and close the database
    connect_to_db.commit()
    connect_to_db.close()
    return login_time

# Logout Functionality
def record_logout(student_id):
    connect_to_db = sqlite3.connect(DB_Path)
    db_cursor = connect_to_db.cursor()

    # Get the current date and time as a string for logout
    logout_time = datetime.now().isoformat(timespec="seconds")

    # Find the most recent login record for this student that 
    # doesn't have a logout time and update it with the logout time
    db_cursor.execute("""
            UPDATE logins
            SET logout_time = ?
            WHERE student_id = ?
            AND logout_time IS NULL
            ORDER BY id DESC
            LIMIT 1
    """, (logout_time, student_id))

    connect_to_db.commit()
    connect_to_db.close()
    return logout_time

#--------------------------------------------------------------------------------------------------------------------------
# Maps URL to python function
@app.route("/", methods = ["GET"])
def home():
    return render_template("index.html")

# This only responds when form data is submitted
@app.route("/checkin", methods = ["POST"])
def checkin():
    # retrieves data sent from the HTML form
    student_id = request.form.get("student_id")

    connect_to_db = sqlite3.connect(DB_Path)
    db_cursor = connect_to_db.cursor()

    # Looking up student information using their ID
    db_cursor.execute("SELECT first_name, last_name, waiver_signed FROM students WHERE student_id = ?", (student_id,))
    # Returns the first matching row as a tuple
    student = db_cursor.fetchone()

    # If a student does not have this ID
    if not student:
        connect_to_db.close()
        return {"message": "Student ID not found"}

    # Unpacking the fetchone generated tuple into independent variables
    first_name, last_name, waiver_signed = student

    # Roadblock, if waiver hasn't been signed then prevent entry
    if waiver_signed.strip() == "" or waiver_signed == "0":
        connect_to_db.close()
        return {"message": f"{first_name} {last_name} cannot check in - liability waiver"}
    
    # Checks if the student's already logged in (and has a login record without logout time)
    db_cursor.execute("""
       SELECT id FROM logins
        WHERE student_id = ? AND logout_time IS NULL
        ORDER BY id DESC LIMIT 1
    """, (student_id,))
    active_session = db_cursor.fetchone()

    if active_session:
        # Logout the student
        logout_time = datetime.now().isoformat(timespec="seconds")
        db_cursor.execute("""
            UPDATE logins SET logout_time = ?
            WHERE id = ?
        """, (logout_time, active_session[0]))

        connect_to_db.commit()
        connect_to_db.close()
        return {"message": f"{first_name} {last_name} checked OUT at {logout_time}"}
    
    else:
        # Login the student
        login_time = datetime.now().isoformat(timespec="seconds")
        db_cursor.execute("""
            INSERT INTO logins (student_id, login_time)
            VALUES (?, ?)
        """, (student_id, login_time))

        connect_to_db.commit()
        connect_to_db.close()
        return {"message": f"{first_name} {last_name} checked IN at {login_time}"}
    

#--------------------------------------------------------------------------------------------------------------------------
# This will only run when the script is executed directly
if __name__ == "__main__":
    # Setup database tables
    initialize_database()
    # Load CSV student data
    import_csv()
    # Start the web server
    app.run(debug=True)