"""Database models for TaskFlow."""
from datetime import datetime, timezone

from app import db

# Allowed priority values (used by the model, the form and validation).
PRIORITIES = ("Low", "Medium", "High")


def utc_now():
    """Current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


class Task(db.Model):
    """A single to-do item stored in the `tasks` table."""

    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(10), nullable=False, default="Medium")
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    # Database-level safety net: only allow the known priority values.
    __table_args__ = (
        db.CheckConstraint(
            "priority IN ('Low', 'Medium', 'High')", name="ck_tasks_priority"
        ),
    )

    def __repr__(self):
        return f"<Task id={self.id} title={self.title!r} completed={self.completed}>"
