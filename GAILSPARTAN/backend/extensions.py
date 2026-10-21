"""Shared Flask extensions.

Keeping the SQLAlchemy object separate from the application factory makes it
possible to create isolated application instances in tests without creating a
database connection at import time.
"""

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
