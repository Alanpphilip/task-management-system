"""TaskFlow web application and command-line interface."""

import argparse
import getpass
import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("TASKFLOW_SECRET_KEY", "change-this-local-development-secret")
DATABASE = Path(__file__).with_name("tasks.db")


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the schema and safely upgrade databases made by the first version."""
    with get_db_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Completed')),
            created_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        for name, definition in (("priority", "TEXT NOT NULL DEFAULT 'Medium'"),
                                 ("category", "TEXT NOT NULL DEFAULT 'General'"),
                                 ("due_date", "TEXT")):
            if name not in columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")


def logged_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if "user" not in g:
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
        else:
            try:
                with get_db_connection() as conn:
                    g.user = conn.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,)).fetchone()
            except sqlite3.Error:
                app.logger.exception("Could not load signed-in user")
                g.user = None
    return g.user


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def task_or_404(conn, task_id):
    user = current_user()
    if user["role"] == "admin":
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    else:
        task = conn.execute("SELECT * FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])).fetchone()
    if task is None:
        abort(404)
    return task


def valid_due_date(value):
    if not value:
        return True
    try:
        date.fromisoformat(value)
        return len(value) == 10
    except ValueError:
        return False


@app.get("/register")
def register():
    if current_user():
        return redirect(url_for("index"))
    return render_template("auth.html", mode="register")


@app.post("/register")
def create_account():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if len(username) < 3 or len(username) > 40 or not username.replace("_", "").isalnum():
        flash("Use a 3–40 character username with letters, numbers, or underscores.", "error")
        return render_template("auth.html", mode="register"), 400
    if len(password) < 8:
        flash("Choose a password with at least 8 characters.", "error")
        return render_template("auth.html", mode="register"), 400
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'user', ?)",
                                  (username, generate_password_hash(password), datetime.now().astimezone().isoformat(timespec="seconds")))
            # Adopt tasks created before accounts were added so an upgrade preserves existing data.
            conn.execute("UPDATE tasks SET owner_id = ? WHERE owner_id IS NULL", (cursor.lastrowid,))
        session.clear()
        session["user_id"] = cursor.lastrowid
        flash("Your account is ready.", "success")
        return redirect(url_for("index"))
    except sqlite3.IntegrityError:
        flash("That username is already in use.", "error")
    except sqlite3.Error:
        app.logger.exception("Could not create account")
        flash("Your account could not be created. Please try again.", "error")
    return render_template("auth.html", mode="register"), 400


@app.get("/login")
def login():
    if current_user():
        return redirect(url_for("index"))
    return render_template("auth.html", mode="login")


@app.post("/login")
def sign_in():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    try:
        with get_db_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Username or password was not recognized.", "error")
    except sqlite3.Error:
        app.logger.exception("Could not sign in")
        flash("Sign in is temporarily unavailable.", "error")
    return render_template("auth.html", mode="login"), 401


@app.post("/logout")
@logged_in
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@logged_in
def index():
    edit_id = request.args.get("edit", type=int)
    user = current_user()
    query = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "")
    priority_filter = request.args.get("priority", "")
    sort = request.args.get("sort", "newest")
    if status_filter not in ("", "Pending", "Completed"):
        status_filter = ""
    if priority_filter not in ("", "High", "Medium", "Low"):
        priority_filter = ""
    sort_sql = {"newest": "id DESC", "oldest": "id ASC",
                "due": "CASE WHEN due_date IS NULL OR due_date = '' THEN 1 ELSE 0 END, due_date ASC, id DESC",
                "priority": "CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, id DESC"}.get(sort, "id DESC")
    try:
        with get_db_connection() as conn:
            if user["role"] == "admin":
                all_tasks = conn.execute("SELECT tasks.*, users.username AS owner_name FROM tasks LEFT JOIN users ON users.id = tasks.owner_id").fetchall()
                sql = "SELECT tasks.*, users.username AS owner_name FROM tasks LEFT JOIN users ON users.id = tasks.owner_id WHERE 1=1"
                params = []
            else:
                all_tasks = conn.execute("SELECT * FROM tasks WHERE owner_id = ?", (user["id"],)).fetchall()
                sql = "SELECT * FROM tasks WHERE owner_id = ?"
                params = [user["id"]]
            if query:
                sql += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"
                params.extend([f"%{query}%"] * 3)
            if status_filter:
                sql += " AND status = ?"
                params.append(status_filter)
            if priority_filter:
                sql += " AND priority = ?"
                params.append(priority_filter)
            tasks = conn.execute(f"{sql} ORDER BY {sort_sql}", params).fetchall()
            edit_task = task_or_404(conn, edit_id) if edit_id else None
    except sqlite3.Error:
        app.logger.exception("Could not load tasks")
        flash("Tasks could not be loaded. Please refresh the page.", "error")
        tasks, all_tasks, edit_task = [], [], None
    total = len(all_tasks)
    completed = sum(task["status"] == "Completed" for task in all_tasks)
    return render_template("index.html", tasks=tasks, edit_task=edit_task,
                           total=total, completed=completed, pending=total - completed,
                           query=query, status_filter=status_filter, priority_filter=priority_filter,
                           sort=sort, today_date=date.today().isoformat())


@app.post("/tasks")
@logged_in
def add_task():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "Medium")
    category = request.form.get("category", "General").strip()[:40] or "General"
    due_date = request.form.get("due_date", "").strip() or None
    if not title or len(title) > 160:
        flash("Enter a task title with 1–160 characters.", "error")
    elif priority not in ("Low", "Medium", "High") or not valid_due_date(due_date):
        flash("Choose a valid priority and due date.", "error")
    else:
        try:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO tasks (title, description, created_at, owner_id, priority, category, due_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (title, description, datetime.now().astimezone().strftime("%b %d, %Y · %I:%M %p"), current_user()["id"], priority, category, due_date))
            flash("Task added.", "success")
        except sqlite3.Error:
            app.logger.exception("Could not add task")
            flash("The task could not be saved. Please try again.", "error")
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/edit")
@logged_in
def update_task(task_id):
    title, description = request.form.get("title", "").strip(), request.form.get("description", "").strip()
    priority = request.form.get("priority", "Medium")
    category = request.form.get("category", "General").strip()[:40] or "General"
    due_date = request.form.get("due_date", "").strip() or None
    if not title or len(title) > 160:
        flash("Enter a task title with 1–160 characters.", "error")
        return redirect(url_for("index", edit=task_id))
    if priority not in ("Low", "Medium", "High") or not valid_due_date(due_date):
        flash("Choose a valid priority and due date.", "error")
        return redirect(url_for("index", edit=task_id))
    try:
        with get_db_connection() as conn:
            task_or_404(conn, task_id)
            conn.execute("UPDATE tasks SET title = ?, description = ?, priority = ?, category = ?, due_date = ? WHERE id = ?", (title, description, priority, category, due_date, task_id))
        flash("Task updated.", "success")
    except sqlite3.Error:
        app.logger.exception("Could not update task")
        flash("The task could not be updated. Please try again.", "error")
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/toggle")
@logged_in
def toggle_task(task_id):
    try:
        with get_db_connection() as conn:
            task = task_or_404(conn, task_id)
            status = "Pending" if task["status"] == "Completed" else "Completed"
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        flash("Task marked " + status.lower() + ".", "success")
    except sqlite3.Error:
        app.logger.exception("Could not update task status")
        flash("The task status could not be changed.", "error")
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
@logged_in
def delete_task(task_id):
    try:
        with get_db_connection() as conn:
            task_or_404(conn, task_id)
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        flash("Task deleted.", "success")
    except sqlite3.Error:
        app.logger.exception("Could not delete task")
        flash("The task could not be deleted. Please try again.", "error")
    return redirect(url_for("index"))


def cli_main(argv=None):
    parser = argparse.ArgumentParser(description="TaskFlow command-line interface")
    sub = parser.add_subparsers(dest="command", required=True)
    admin_parser = sub.add_parser("create-admin", help="Create the first administrator account")
    admin_parser.add_argument("username")
    add_parser = sub.add_parser("add", help="Add a task")
    add_parser.add_argument("username")
    add_parser.add_argument("title")
    add_parser.add_argument("--description", default="")
    add_parser.add_argument("--priority", choices=("Low", "Medium", "High"), default="Medium")
    add_parser.add_argument("--category", default="General")
    add_parser.add_argument("--due-date", default=None, help="Due date in YYYY-MM-DD format")
    list_parser = sub.add_parser("list", help="List tasks belonging to a user")
    list_parser.add_argument("username")
    for command, help_text in (("complete", "Mark a task completed"), ("delete", "Delete a task")):
        action_parser = sub.add_parser(command, help=help_text)
        action_parser.add_argument("username")
        action_parser.add_argument("task_id", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "create-admin":
            password = getpass.getpass("Admin password (8+ characters): ")
            if len(password) < 8:
                parser.error("password must be at least 8 characters")
            with get_db_connection() as conn:
                conn.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
                             (args.username, generate_password_hash(password), datetime.now().astimezone().isoformat(timespec="seconds")))
            print(f"Administrator {args.username} created.")
            return 0
        with get_db_connection() as conn:
            user = conn.execute("SELECT id, role FROM users WHERE username = ?", (args.username,)).fetchone()
            if not user:
                print(f"No account found for {args.username}.")
                return 1
            if args.command == "add":
                if not valid_due_date(args.due_date):
                    print("Due date must use YYYY-MM-DD format.")
                    return 1
                conn.execute("INSERT INTO tasks (title, description, created_at, owner_id, priority, category, due_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (args.title, args.description, datetime.now().astimezone().strftime("%b %d, %Y · %I:%M %p"), user["id"], args.priority, args.category[:40] or "General", args.due_date))
                print("Task added.")
            elif args.command == "list":
                rows = conn.execute("SELECT id, title, status, priority, category, due_date, created_at FROM tasks WHERE owner_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
                if not rows:
                    print("No tasks yet.")
                for row in rows:
                    due = f" · due {row['due_date']}" if row["due_date"] else ""
                    print(f"#{row['id']} [{row['status']} · {row['priority']} · {row['category']}] {row['title']}{due} — {row['created_at']}")
            else:
                row = conn.execute("SELECT id FROM tasks WHERE id = ? AND owner_id = ?", (args.task_id, user["id"])).fetchone()
                if not row:
                    print("Task not found for that user.")
                    return 1
                if args.command == "complete":
                    conn.execute("UPDATE tasks SET status = 'Completed' WHERE id = ?", (args.task_id,))
                    print("Task completed.")
                else:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (args.task_id,))
                    print("Task deleted.")
        return 0
    except sqlite3.IntegrityError:
        print("That username already exists or the requested data is invalid.")
        return 1
    except sqlite3.Error as exc:
        print(f"Database error: {exc}")
        return 1


init_db()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        raise SystemExit(cli_main(sys.argv[2:]))
    app.run(debug=os.environ.get("TASKFLOW_DEBUG") == "1")
