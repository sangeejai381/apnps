from flask_wtf import CSRFProtect

from models import db

csrf = CSRFProtect()
