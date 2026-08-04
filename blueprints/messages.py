from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Message
from constants import MESSAGE_MAX_LENGTH, MESSAGE_NAME_MAX_LENGTH, MESSAGE_PAGE_SIZE
from helpers import get_page_arg, login_required

bp = Blueprint("messages", __name__)


@bp.route("/messages", methods=["GET", "POST"])
@login_required
def messages():
    if request.method == "POST":
        posted_by = request.form.get("posted_by", "").strip()
        content = request.form.get("content", "").strip()

        if not posted_by or not content:
            flash("Please enter your name and a message.")
            return redirect(url_for("messages.messages"))
        if len(posted_by) > MESSAGE_NAME_MAX_LENGTH:
            flash(f"Name must be {MESSAGE_NAME_MAX_LENGTH} characters or fewer.")
            return redirect(url_for("messages.messages"))
        if len(content) > MESSAGE_MAX_LENGTH:
            flash(f"Message must be {MESSAGE_MAX_LENGTH} characters or fewer.")
            return redirect(url_for("messages.messages"))

        try:
            db.session.add(Message(posted_by=posted_by, content=content))
            db.session.commit()
            session["chat_name"] = posted_by
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not post this message. Please try again.")
        return redirect(url_for("messages.messages"))

    page = get_page_arg()
    pagination = Message.query.order_by(Message.posted_at.desc()).paginate(page=page, per_page=MESSAGE_PAGE_SIZE, error_out=False)
    thread = list(reversed(pagination.items))
    return render_template("messages.html", thread=thread, pagination=pagination, remembered_name=session.get("chat_name", ""))


@bp.route("/messages/<int:message_id>/delete", methods=["POST"])
@login_required
def delete_message(message_id):
    m = Message.query.get_or_404(message_id)
    db.session.delete(m)
    db.session.commit()
    flash("Message removed.")
    return redirect(url_for("messages.messages"))
