import re
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from constants import CLASS_CHOICES, CONCESSION_CATEGORY
from extensions import db
from helpers import login_required
from models import Expense, FeePayment, SalaryPayment, Student, StudentFee, StudentFeeItem, Teacher, TeacherSalary

bp = Blueprint("assistant", __name__)

EXAMPLES = [
    "How many students do we have?",
    "What's the total fees pending?",
    "Pending fees for Std 3",
    "How much did we collect today?",
    "How much did we collect this month?",
    "Total salary due",
    "Total expenses",
    "Which class has the highest balance due?",
    "Payment mode breakdown",
    "How much concession have we given?",
    "How do I add a concession?",
    "How do I record a payment?",
]


def _money(n):
    return f"₹{n:,.2f}"


def _match_class(text):
    """Loosely map phrases like 'grade 3' / 'class 3' / 'standard 3' to 'Std 3', plus direct matches."""
    norm = text.lower()
    norm = re.sub(r"\b(grade|class|standard)\b", "std", norm)
    for choice in CLASS_CHOICES:
        if choice.lower() in norm:
            return choice
        # "std 3" vs choice "Std 3" already covered by the substring check above;
        # also handle "std3" (no space)
        if choice.lower().replace(" ", "") in norm.replace(" ", ""):
            return choice
    return None


def _class_balance(class_name):
    paid_subq = (
        db.session.query(FeePayment.student_id.label("student_id"), func.sum(FeePayment.amount).label("paid"))
        .group_by(FeePayment.student_id).subquery()
    )
    q = (
        db.session.query(
            func.coalesce(func.sum(StudentFee.total_fee), 0), func.coalesce(func.sum(paid_subq.c.paid), 0),
        )
        .select_from(Student)
        .outerjoin(StudentFee, StudentFee.student_id == Student.id)
        .outerjoin(paid_subq, paid_subq.c.student_id == Student.id)
        .filter(Student.class_name == class_name)
    )
    total, paid = q.first()
    return total, paid, total - paid


def _highest_balance_class():
    rows = []
    for class_name in CLASS_CHOICES:
        total, paid, balance = _class_balance(class_name)
        if total > 0:
            rows.append((class_name, balance))
    if not rows:
        return None
    return max(rows, key=lambda r: r[1])


HOW_TO = [
    (["add student", "new student", "register student", "enroll student", "enrol student"],
     "Go to Students → Add Student in the sidebar. Fill in the student's name, class, section, and fee — the "
     "fee can auto-fill from that class's Fee Structure if one's already set up."),
    (["add concession", "add discount", "give scholarship", "apply discount", "give discount"],
     "Open the student's Fee Detail page (Fee Management → Manage next to their name), then use the "
     "'Add Concession / Discount' panel — pick a reason and amount and it reduces their total fee automatically."),
    (["record payment", "add payment", "collect payment", "take payment", "enter payment"],
     "On a student's Fee Detail page, use the 'Due Date & Payment' panel — choose which fee category the "
     "payment is for (or leave it 'General'), then enter the amount, date, and mode."),
    (["add teacher", "add staff", "new teacher", "register teacher", "new staff"],
     "Go to Teachers / Staff → Add Teacher in the sidebar and fill in their name, subject, contact, and "
     "monthly salary."),
    (["add expense", "record expense", "new expense", "enter expense"],
     "Go to Total Expenses → Add Expense and fill in the title, category, amount, and date."),
    (["download report", "export report", "print report", "generate report", "get a report"],
     "Go to Reports in the sidebar, pick a report type (Student & Class Fee, Class-wise Summary, Salary, or "
     "Expenses), then use Download CSV or Open Detailed Report to save it as a PDF."),
    (["fee structure", "set fee for class", "class fee amount"],
     "Go to Fee Structure in the sidebar to set the default fee categories and amounts for each class — "
     "new students in that class will pick these up automatically."),
    (["reset password", "forgot password", "forgot pin", "change pin", "change password"],
     "Use the 'Forgot PIN?' link on the login page to reset it."),
    (["import student", "bulk add student", "upload student", "csv"],
     "Go to Students → Import (CSV) to bulk-upload students from a spreadsheet — there's a downloadable "
     "template with the exact columns it expects."),
    (["edit", "fix", "correct", "mistake", "wrong entry", "typo", "undo", "delete"],
     "Most records — students, teachers, expenses, fee items, and payments — have an Edit link or an inline "
     "Save button right on their page, so mistakes can be corrected without deleting and re-adding."),
]


def _phrase_matches(text, phrase):
    """True if every word in `phrase` appears somewhere in `text`, regardless
    of order or filler words in between — so 'add student' matches both
    'add student' and 'how do I add a new student', not just an exact
    substring."""
    return all(word in text for word in phrase.split())


def _how_to_answer(text):
    for phrases, answer in HOW_TO:
        if any(_phrase_matches(text, p) for p in phrases):
            return answer
    return None


def _find_student(name_query):
    name_query = name_query.strip(" ?.!,")
    if not name_query:
        return None
    return Student.query.filter(Student.name.ilike(f"%{name_query}%")).order_by(Student.name).first()


def _students_in_class(class_name):
    return db.session.query(func.count(Student.id)).filter(Student.class_name == class_name).scalar()


def _answer(message):
    text = message.lower().strip()
    if not text:
        return "Ask me something about students, fees, salaries, expenses, or how to use the portal — or tap one of the examples below."

    # Greetings / thanks / identity
    if re.search(r"\b(hi|hello|hey)\b", text) and len(text) < 20:
        return "Hi! I can answer questions about fees, concessions, salaries, and expenses using your school's live data, and I can point you to how to do things in the portal. Try one of the example questions below."
    if re.search(r"\b(thanks|thank you|thx)\b", text):
        return "You're welcome! Let me know if there's anything else you'd like to check."
    if "who are you" in text or "what is this" in text or "what are you" in text:
        return (
            "I'm the built-in School Data Assistant for the APNPS Admin Portal. I answer questions from your "
            "school's live records (fees, concessions, salaries, expenses) and can point you to the right "
            "page for common tasks. I'm rule-based, not a general AI, so I work best with the kinds of "
            "questions in the examples below."
        )
    if "help" in text or "what can you" in text:
        return "I can answer things like: " + "; ".join(EXAMPLES[:5]) + ". I can also explain how to do things — try asking 'how do I add a student' or 'how do I add a concession'."

    # How-to / usage questions — checked before topic keywords below, since
    # e.g. "how do I add a concession" would otherwise get caught by the
    # concession-total lookup instead of answered as a how-to question.
    how_to = _how_to_answer(text)
    if how_to:
        return how_to

    # Salary (checked before generic "due"/"balance" so it doesn't get
    # caught by the fee-balance branch below)
    if "salary" in text:
        total_monthly = db.session.query(func.coalesce(func.sum(TeacherSalary.monthly_salary), 0)).scalar()
        total_paid = db.session.query(func.coalesce(func.sum(SalaryPayment.amount), 0)).scalar()
        due = total_monthly - total_paid
        return (
            f"Total monthly salary across all staff is {_money(total_monthly)}, "
            f"{_money(total_paid)} paid to date, leaving {_money(due)} due."
        )

    # Expenses
    if "expense" in text:
        total = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()
        top = (
            db.session.query(Expense.category, func.sum(Expense.amount))
            .group_by(Expense.category).order_by(func.sum(Expense.amount).desc()).first()
        )
        extra = f" The biggest category is {top[0]} at {_money(top[1])}." if top else ""
        return f"Total expenses recorded so far: {_money(total)}.{extra}"

    # Concession / discount
    if "concession" in text or "discount" in text or "scholarship" in text:
        total = abs(
            db.session.query(func.coalesce(func.sum(StudentFeeItem.amount), 0))
            .filter(StudentFeeItem.category == CONCESSION_CATEGORY).scalar()
        )
        return f"Total concession/discount given to students across all recorded years: {_money(total)}."

    # Payment mode breakdown
    if "payment mode" in text or "mode breakdown" in text or "cash vs" in text or "upi vs" in text:
        rows = (
            db.session.query(FeePayment.mode, func.count(FeePayment.id), func.sum(FeePayment.amount))
            .group_by(FeePayment.mode).order_by(func.sum(FeePayment.amount).desc()).all()
        )
        if not rows:
            return "No fee payments recorded yet."
        parts = [f"{mode}: {_money(amt)} ({count} payment{'s' if count != 1 else ''})" for mode, count, amt in rows]
        return "Payment mode breakdown — " + "; ".join(parts) + "."

    # Highest balance class
    if "highest" in text and ("balance" in text or "due" in text or "pending" in text):
        result = _highest_balance_class()
        if not result:
            return "No class has any fee set up yet."
        class_name, balance = result
        return f"{class_name} has the highest balance due, at {_money(balance)}."

    # How many students in a specific class
    if ("how many" in text or "number of" in text) and "student" in text:
        class_name = _match_class(text)
        if class_name:
            count = _students_in_class(class_name)
            return f"{class_name} has {count} student{'s' if count != 1 else ''}."
        count = db.session.query(func.count(Student.id)).scalar()
        return f"There are {count} students on file."

    # Collected today / this month / all time
    if "collect" in text and "today" in text:
        today = datetime.now().strftime("%Y-%m-%d")
        total = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).filter(FeePayment.date == today).scalar()
        return f"Collected today ({today}): {_money(total)}."
    if "collect" in text and ("this month" in text or "month" in text):
        month_prefix = datetime.now().strftime("%Y-%m")
        total = (
            db.session.query(func.coalesce(func.sum(FeePayment.amount), 0))
            .filter(FeePayment.date.like(f"{month_prefix}%")).scalar()
        )
        return f"Collected this month ({month_prefix}): {_money(total)}."
    if "collect" in text:
        total = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).scalar()
        return f"Total fees collected (all time): {_money(total)}."

    # Pending / due / balance — scoped to a class, a named student, or the whole school
    if any(k in text for k in ["pending", "due", "balance", "outstanding", "owe"]):
        class_name = _match_class(text)
        if class_name:
            total, paid, balance = _class_balance(class_name)
            return f"{class_name}: total fee {_money(total)}, paid {_money(paid)}, balance due {_money(balance)}."

        name_match = re.search(r"(?:for|of)\s+([a-zA-Z][a-zA-Z .]{1,40})$", text)
        if name_match:
            student = _find_student(name_match.group(1))
            if student:
                total = student.fee.total_fee if student.fee else 0
                paid = sum(p.amount for p in student.payments)
                balance = total - paid
                where = f"{student.class_name}{' ' + student.section if student.section else ''}"
                return f"{student.name} ({where}): total fee {_money(total)}, paid {_money(paid)}, balance due {_money(balance)}."

        total = db.session.query(func.coalesce(func.sum(StudentFee.total_fee), 0)).scalar()
        paid = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).scalar()
        return f"School-wide: total fee expected {_money(total)}, collected {_money(paid)}, balance due {_money(total - paid)}."

    # Direct "fees for <student name>" / "status of <student name>" lookups
    name_match = re.search(r"(?:fees?|status|record)\s+(?:for|of)\s+([a-zA-Z][a-zA-Z .]{1,40})$", text)
    if name_match:
        student = _find_student(name_match.group(1))
        if student:
            total = student.fee.total_fee if student.fee else 0
            paid = sum(p.amount for p in student.payments)
            balance = total - paid
            where = f"{student.class_name}{' ' + student.section if student.section else ''}"
            return f"{student.name} ({where}): total fee {_money(total)}, paid {_money(paid)}, balance due {_money(balance)}."

    # Counts
    if "how many student" in text or "total student" in text or "number of student" in text:
        count = db.session.query(func.count(Student.id)).scalar()
        return f"There are {count} students on file."
    if "how many teacher" in text or "how many staff" in text or "total teacher" in text or "total staff" in text:
        count = db.session.query(func.count(Teacher.id)).scalar()
        return f"There are {count} staff members on file."

    return (
        "I'm not sure how to answer that yet — I can help with student counts, pending/due fees "
        "(overall, per class, or per student), today's/this month's collections, salary dues, expenses, "
        "concessions, payment mode breakdowns, and how-to questions like 'how do I add a student'. Try one "
        "of the example questions below, or visit the Reports page for full downloadable reports."
    )


@bp.route("/assistant/examples")
@login_required
def examples():
    return jsonify({"examples": EXAMPLES})


@bp.route("/assistant/ask", methods=["POST"])
@login_required
def ask():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", ""))[:300]
    try:
        reply = _answer(message)
    except Exception:
        reply = "Sorry, I couldn't work that out. Try rephrasing, or check the Reports page for full detail."
    return jsonify({"reply": reply})
