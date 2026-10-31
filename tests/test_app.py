"""
Automated tests for TaskFlow.

They use an in-memory SQLite database (see TestingConfig), so PostgreSQL does
not need to be running. Run with:  pytest -v
"""
import pytest
from sqlalchemy.exc import OperationalError

from app import create_app, db
from app.models import Task
from config import TestingConfig


@pytest.fixture
def app():
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def add_task(client, title="Write report", description="", priority="Medium"):
    return client.post(
        "/tasks",
        data={"title": title, "description": description, "priority": priority},
        follow_redirects=True,
    )


# ---------------------------------------------------------------- Basic pages
def test_index_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"TaskFlow" in response.data
    assert b"No tasks yet" in response.data


def test_unknown_page_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


# ---------------------------------------------------------------- Create
def test_create_task(client):
    response = add_task(client, "Deploy app", "Use Gunicorn", "High")
    assert response.status_code == 200
    assert b"Deploy app" in response.data
    assert b"Task added." in response.data

    task = Task.query.one()
    assert task.title == "Deploy app"
    assert task.description == "Use Gunicorn"
    assert task.priority == "High"
    assert task.completed is False
    assert task.created_at is not None


def test_title_is_trimmed(client):
    add_task(client, "   Spaces around   ")
    assert Task.query.one().title == "Spaces around"


# ---------------------------------------------------------------- Validation
@pytest.mark.parametrize(
    "form, message",
    [
        ({"title": "", "priority": "Low"}, b"Title is required."),
        ({"title": "   ", "priority": "Low"}, b"Title is required."),
        ({"title": "x" * 201, "priority": "Low"}, b"Title must be 200 characters or fewer."),
        ({"title": "ok", "description": "d" * 1001, "priority": "Low"},
         b"Description must be 1000 characters or fewer."),
        ({"title": "ok", "priority": "Urgent"}, b"Priority must be Low, Medium or High."),
        ({"title": "ok"}, b"Priority must be Low, Medium or High."),
    ],
)
def test_invalid_input_is_rejected(client, form, message):
    response = client.post("/tasks", data=form)
    assert response.status_code == 400
    assert message in response.data
    assert Task.query.count() == 0


def test_invalid_input_keeps_user_text(client):
    response = client.post("/tasks", data={"title": "Keep me", "priority": "Bad"})
    assert b'value="Keep me"' in response.data


# ---------------------------------------------------------------- Edit
def test_edit_task(client):
    add_task(client, "Old title")
    task_id = Task.query.one().id

    response = client.get(f"/tasks/{task_id}/edit")
    assert response.status_code == 200
    assert b"Edit task" in response.data

    response = client.post(
        f"/tasks/{task_id}/edit",
        data={"title": "New title", "description": "Updated", "priority": "Low"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    task = db.session.get(Task, task_id)
    assert task.title == "New title"
    assert task.description == "Updated"
    assert task.priority == "Low"


def test_edit_with_invalid_data_is_rejected(client):
    add_task(client, "Original")
    task_id = Task.query.one().id
    response = client.post(f"/tasks/{task_id}/edit", data={"title": "", "priority": "Low"})
    assert response.status_code == 400
    assert db.session.get(Task, task_id).title == "Original"


def test_edit_missing_task_returns_404(client):
    assert client.get("/tasks/999/edit").status_code == 404


# ---------------------------------------------------------------- Toggle / delete
def test_toggle_task(client):
    add_task(client)
    task_id = Task.query.one().id

    client.post(f"/tasks/{task_id}/toggle")
    assert db.session.get(Task, task_id).completed is True

    client.post(f"/tasks/{task_id}/toggle")
    assert db.session.get(Task, task_id).completed is False


def test_delete_task(client):
    add_task(client)
    task_id = Task.query.one().id
    response = client.post(f"/tasks/{task_id}/delete", follow_redirects=True)
    assert response.status_code == 200
    assert Task.query.count() == 0


def test_delete_requires_post(client):
    add_task(client)
    task_id = Task.query.one().id
    assert client.get(f"/tasks/{task_id}/delete").status_code == 405
    assert Task.query.count() == 1


# ---------------------------------------------------------------- Filters & counts
def test_filters(client):
    add_task(client, "Pending one")
    add_task(client, "Done one")
    done = Task.query.filter_by(title="Done one").one()
    client.post(f"/tasks/{done.id}/toggle")

    all_page = client.get("/?filter=all").data
    assert b"Pending one" in all_page and b"Done one" in all_page

    pending_page = client.get("/?filter=pending").data
    assert b"Pending one" in pending_page and b"Done one" not in pending_page

    completed_page = client.get("/?filter=completed").data
    assert b"Done one" in completed_page and b"Pending one" not in completed_page

    # Unknown filter values fall back to "all".
    bogus_page = client.get("/?filter=bogus").data
    assert b"Pending one" in bogus_page and b"Done one" in bogus_page


def test_counts_are_displayed(client):
    add_task(client, "A")
    add_task(client, "B")
    add_task(client, "C")
    first = Task.query.filter_by(title="A").one()
    client.post(f"/tasks/{first.id}/toggle")

    page = client.get("/").get_data(as_text=True)
    # Stat cards show: total 3, pending 2, completed 1.
    assert 'Total</div>\n      <div class="stat-value">3</div>' in page
    assert ">2</div>" in page
    assert ">1</div>" in page


# ---------------------------------------------------------------- Health check
def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "healthy", "application": "up", "database": "up"}


def test_health_returns_503_when_database_down(client, monkeypatch):
    def broken_execute(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(db.session, "execute", broken_execute)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["status"] == "unhealthy"
    assert response.get_json()["database"] == "down"
