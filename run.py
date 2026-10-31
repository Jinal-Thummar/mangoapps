"""
Entry point for TaskFlow.

Development:  python run.py
Production:   gunicorn --bind 127.0.0.1:8000 --workers 3 run:app
"""
import os

from app import create_app

# Gunicorn imports this module and looks for the `app` variable.
app = create_app()

if __name__ == "__main__":
    # Flask's built-in server is for local development only.
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=app.config["DEBUG"],
    )
