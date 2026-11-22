TaskFlow – Task Management System

TaskFlow is a task management application built with Flask and SQLite. It provides a responsive web interface, user accounts, role-based access, and a command-line interface for managing tasks.

Features

- User registration and login
- Create, edit, complete, and delete tasks
- Admin and regular user roles
- Task search, filters, and sorting
- Priority, categories, and due dates
- SQLite database storage
- Command-line task management
- Responsive web interface

Technologies Used

- Python
- Flask
- SQLite
- HTML
- CSS

How to Run

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py

Open "http://127.0.0.1:5000" in your browser.

Project Structure

TaskFlow/
├── app.py
├── requirements.txt
├── templates/
│   ├── index.html
│   └── auth.html
└── static/
    └── style.css

The "tasks.db" database is created automatically when the application starts.

Author

Alan P philip
