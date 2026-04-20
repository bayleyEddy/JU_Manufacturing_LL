# Lab Check-In System 
A Flask-based web application that allows students, student workers, and professors to check in and out of a university lab using their ID cards. Attendance is logged to an Azure SQL Database, and users with elevated roles (professors and student workers) are redirected to their respective dashboards. 
---
## Features
- **Card swipe supported**
- **Role-based logic**
  - Students: Check-in/out (no redirect)
  - Student Workers: Redirected to worker dashboard (manages signed-in students)
  - Professors: Redirected to professor dashboard (manage student profiles)
- **Azure SQL Database integrated**
- **Attendance Logging**
- **Liability waiver enforcement for students**
---
## Required
To successfully run this program, you'll need:
- Python 3.8+
- pip (Python package manager)
- ODBC Driver 17 for SQL Server
---
## How to run the program:
- Open the app.py script and run it, within the terminal a url will appear. Once this happens the user will need to ctrl + click this and will be redirected to the programs home page.
---
## Database Overview:
- dbo.Student
  - Stores student information such as their name, student ID number, and if the waiver was signed
- dbo.Professor
  - Stores professor information such as name and ID number
- dbo.Attendance_Log
  - Stores the timestamps of all user types signing in/out
## Test User Credential:
- Professor:123456
- Student Worker:525838
- Student: 587794
## Required dependencies:
- Flask
- pyodbc  
