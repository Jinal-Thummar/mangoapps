"""
Web routes for TaskFlow.

The UI is a single page (index.html). Every action that changes data uses
POST and then redirects back to the list (the Post/Redirect/Get pattern),
so refreshing the browser never submits a form twice.
"""
from flask import (
    Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import PRIORITIES, Task

bp = Blueprint("main", __name__)

FILTERS = ("all", "pending", "completed")
TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 1000


# --------------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------------
def get_filter(value):
    """Return a valid filter name, falling back to 'all'."""
    return value if value in FILTERS else "all"


def redirect_to_list():
    """Redirect back to the task list, keeping the current filter."""
    current = get_filter(request.form.get("filter") or request.args.get("filter"))
    return redirect(url_for("main.index", filter=current))


def validate_task_form(form):
    """Clean and validate submitted task data.

    Returns a tuple: (cleaned_data, list_of_error_messages).
    """
    title = (form.get("title") or "").strip()
    description = (form.get("description") or "").strip()
    priority = (form.get("priority") or "").strip()

    errors = []
    if not title:
        errors.append("Title is required.")
    elif len(title) > TITLE_MAX_LENGTH:
        errors.append(f"Title must be {TITLE_MAX_LENGTH} characters or fewer.")

    if len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(f"Description must be {DESCRIPTION_MAX_LENGTH} characters or fewer.")

    if priority not in PRIORITIES:
        errors.append("Priority must be Low, Medium or High.")

    data = {"title": title, "description": description, "priority": priority}
    return data, errors


def render_index(form_data=None, errors=None, edit_task=None, status=200):
    """Render the main page with task list, counts and the add/edit form."""
    current = get_filter(request.args.get("filter") or request.form.get("filter"))

    query = Task.query
    if current == "pending":
        query = query.filter_by(completed=False)
    elif current == "completed":
        query = query.filter_by(completed=True)
    tasks = query.order_by(Task.created_at.desc(), Task.id.desc()).all()

    counts = {
        "total": Task.query.count(),
        "pending": Task.query.filter_by(completed=False).count(),
        "completed": Task.query.filter_by(completed=True).count(),
    }

    # Values shown in the form: what the user just typed (after a validation
    # error), the task being edited, or empty defaults for a new task.
    if form_data is None:
        if edit_task is not None:
            form_data = {
                "title": edit_task.title,
                "description": edit_task.description or "",
                "priority": edit_task.priority,
            }
        else:
            form_data = {"title": "", "description": "", "priority": "Medium"}

    return render_template(
        "index.html",
        tasks=tasks,
        counts=counts,
        current_filter=current,
        form=form_data,
        errors=errors or [],
        edit_task=edit_task,
        priorities=PRIORITIES,
        title_max=TITLE_MAX_LENGTH,
        description_max=DESCRIPTION_MAX_LENGTH,
    ), status


# --------------------------------------------------------------------------
# Pages and actions
# --------------------------------------------------------------------------
@bp.route("/")
def index():
    """Show all tasks (optionally filtered with ?filter=pending|completed)."""
    return render_index()


@bp.route("/tasks", methods=["POST"])
def create_task():
    """Create a new task from the form."""
    data, errors = validate_task_form(request.form)
    if errors:
        return render_index(form_data=data, errors=errors, status=400)

    task = Task(
        title=data["title"],
        description=data["description"] or None,
        priority=data["priority"],
    )
    db.session.add(task)
    db.session.commit()
    current_app.logger.info("Created task id=%s", task.id)
    flash("Task added.", "success")
    return redirect_to_list()


@bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    """GET shows the edit form; POST saves the changes."""
    task = db.get_or_404(Task, task_id)

    if request.method == "GET":
        return render_index(edit_task=task)

    data, errors = validate_task_form(request.form)
    if errors:
        return render_index(form_data=data, errors=errors, edit_task=task, status=400)

    task.title = data["title"]
    task.description = data["description"] or None
    task.priority = data["priority"]
    db.session.commit()
    current_app.logger.info("Updated task id=%s", task.id)
    flash("Task updated.", "success")
    return redirect_to_list()


@bp.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    """Switch a task between completed and pending."""
    task = db.get_or_404(Task, task_id)
    task.completed = not task.completed
    db.session.commit()
    status = "completed" if task.completed else "pending"
    current_app.logger.info("Marked task id=%s as %s", task.id, status)
    flash(f"Task marked as {status}.", "success")
    return redirect_to_list()


@bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    """Delete a task permanently."""
    task = db.get_or_404(Task, task_id)
    db.session.delete(task)
    db.session.commit()
    current_app.logger.info("Deleted task id=%s", task_id)
    flash("Task deleted.", "success")
    return redirect_to_list()


# --------------------------------------------------------------------------
# Health check (used by load balancers, monitoring and Nginx)
# --------------------------------------------------------------------------
@bp.route("/health")
def health():
    """Return 200 if the app and database are working, otherwise 503."""
    try:
        # The simplest possible query: proves we can reach PostgreSQL.
        db.session.execute(text("SELECT 1"))
        return jsonify(status="healthy", application="up", database="up"), 200
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.error("Health check failed: database unreachable: %s", exc)
        return jsonify(status="unhealthy", application="up", database="down"), 503
