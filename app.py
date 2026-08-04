import os

from flask import Flask, redirect, render_template, url_for

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import Config
from extensions import csrf, db
from helpers import backfill_legacy_fee_items, ensure_schema_migrations, seed_admin

from blueprints.auth import bp as auth_bp
from blueprints.dashboard import bp as dashboard_bp
from blueprints.students import bp as students_bp
from blueprints.fee_structure import bp as fee_structure_bp
from blueprints.fees import bp as fees_bp
from blueprints.teachers import bp as teachers_bp
from blueprints.salary import bp as salary_bp
from blueprints.expenses import bp as expenses_bp
from blueprints.messages import bp as messages_bp
from blueprints.reports import bp as reports_bp
from blueprints.assistant import bp as assistant_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)

    for bp in (auth_bp, dashboard_bp, students_bp, fee_structure_bp, fees_bp, teachers_bp, salary_bp, expenses_bp, messages_bp, reports_bp, assistant_bp):
        app.register_blueprint(bp)

    @app.route("/")
    def home():
        return redirect(url_for("auth.login"))

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="That page doesn't exist."), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template(
            "error.html", code=500,
            message="Something went wrong on our end. Your last action may not have been saved — please try again.",
        ), 500

    with app.app_context():
        db.create_all()
        ensure_schema_migrations()
        backfill_legacy_fee_items()
        seed_admin()

    return app


app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="127.0.0.1", port=5000)
