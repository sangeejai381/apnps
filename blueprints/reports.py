import csv
import io
from datetime import datetime

from flask import Blueprint, Response, render_template, request

from sqlalchemy import func

from constants import CLASS_CHOICES, CONCESSION_CATEGORY, EXPENSE_CATEGORIES, SECTION_CHOICES
from extensions import db
from helpers import current_academic_year, login_required
from models import Expense, SalaryPayment, Student, StudentFee, StudentFeeItem, Teacher, TeacherSalary

bp = Blueprint("reports", __name__)

REPORT_KINDS = ["fee", "classwise", "salary", "expenses"]


# =============================================================================
# Shared helpers
# =============================================================================

def _read_common():
    kind = request.args.get("kind", "fee").strip()
    return kind if kind in REPORT_KINDS else "fee"


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _csv_response(buf, filename):
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# =============================================================================
# Kind: fee — student / class / whole-school fee & concession detail
# (per-student breakdown, unchanged from the original Reports feature)
# =============================================================================

def _fee_read_filters():
    return (
        request.args.get("report_type", "all").strip() or "all",
        request.args.get("class_name", "").strip(),
        request.args.get("section", "").strip(),
        request.args.get("student_id", "").strip(),
    )


def _fee_matching_students(report_type, class_name, section, student_id):
    query = Student.query
    if report_type == "student" and student_id:
        query = query.filter(Student.id == student_id)
    elif report_type == "class" and class_name:
        query = query.filter(Student.class_name == class_name)
        if section:
            query = query.filter(Student.section == section)
    return query.order_by(Student.class_name, Student.section, Student.name).all()


def _fee_student_detail(s):
    year = (s.fee.academic_year if s.fee else None) or current_academic_year()
    items = StudentFeeItem.query.filter_by(student_id=s.id, academic_year=year).order_by(StudentFeeItem.id).all()
    fee_lines = [i for i in items if i.category != CONCESSION_CATEGORY]
    concession_lines = [i for i in items if i.category == CONCESSION_CATEGORY]
    concession_total = abs(sum(i.amount for i in concession_lines))

    total_fee = s.fee.total_fee if s.fee else 0
    paid = sum(p.amount for p in s.payments)
    balance = total_fee - paid
    status = (
        "Paid" if balance <= 0 and total_fee > 0
        else ("Not Set" if total_fee == 0 else ("Partial" if paid > 0 else "Due"))
    )
    payments = sorted(s.payments, key=lambda p: p.id, reverse=True)

    return {
        "student": s, "academic_year": year, "fee_lines": fee_lines, "concession_lines": concession_lines,
        "concession_total": concession_total, "total_fee": total_fee, "paid": paid, "balance": balance,
        "status": status, "due_date": s.fee.due_date if s.fee else None, "payments": payments,
    }


def _fee_summarize(rows):
    return {
        "count": len(rows),
        "total_fee": sum(r["total_fee"] for r in rows),
        "concession": sum(r["concession_total"] for r in rows),
        "paid": sum(r["paid"] for r in rows),
        "balance": sum(r["balance"] for r in rows),
    }


def _fee_scope_label(report_type, class_name, section, rows):
    if report_type == "class" and class_name:
        return f"{class_name} {section}".strip()
    if report_type == "student" and rows:
        return rows[0]["student"].name
    return "Whole School"


def _fee_reports_context():
    report_type, class_name, section, student_id = _fee_read_filters()
    students = _fee_matching_students(report_type, class_name, section, student_id)
    rows = [_fee_student_detail(s) for s in students]
    all_students = Student.query.order_by(Student.class_name, Student.name).all()
    total_expenses = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar() if report_type == "all" else None
    )
    return dict(
        rows=rows, summary=_fee_summarize(rows), report_type=report_type, class_name=class_name,
        section=section, student_id=student_id, class_choices=CLASS_CHOICES, section_choices=SECTION_CHOICES,
        students=all_students, total_expenses=total_expenses,
    )


def _fee_print():
    report_type, class_name, section, student_id = _fee_read_filters()
    students = _fee_matching_students(report_type, class_name, section, student_id)
    rows = [_fee_student_detail(s) for s in students]

    expense_summary = None
    if report_type == "all":
        by_category = (
            db.session.query(Expense.category, func.sum(Expense.amount))
            .group_by(Expense.category).order_by(func.sum(Expense.amount).desc()).all()
        )
        expense_summary = {"by_category": by_category, "total": sum(amt for _, amt in by_category)}

    return render_template(
        "report_print.html", rows=rows, summary=_fee_summarize(rows), report_type=report_type,
        scope_label=_fee_scope_label(report_type, class_name, section, rows),
        expense_summary=expense_summary, printed_on=_timestamp(),
    )


def _fee_csv():
    report_type, class_name, section, student_id = _fee_read_filters()
    students = _fee_matching_students(report_type, class_name, section, student_id)
    rows = [_fee_student_detail(s) for s in students]
    summary = _fee_summarize(rows)
    scope_label = _fee_scope_label(report_type, class_name, section, rows)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([f"APNPS Fee & Concession Report — {scope_label}"])
    writer.writerow([f"Generated: {_timestamp()}"])
    writer.writerow([])
    writer.writerow([
        "Student Name", "Roll No", "Class", "Section", "Parent Name", "Contact", "Academic Year",
        "Total Fee", "Concession", "Concession Reason(s)", "Paid", "Balance", "Status", "Due Date",
    ])
    for r in rows:
        s = r["student"]
        reasons = "; ".join(i.custom_category for i in r["concession_lines"]) or "-"
        writer.writerow([
            s.name, s.roll_no, s.class_name, s.section or "", s.parent_name or "", s.contact or "",
            r["academic_year"], f"{r['total_fee']:.2f}", f"{r['concession_total']:.2f}", reasons,
            f"{r['paid']:.2f}", f"{r['balance']:.2f}", r["status"], r["due_date"] or "",
        ])
    writer.writerow([])
    writer.writerow([
        "TOTALS", "", "", "", "", "", "", f"{summary['total_fee']:.2f}", f"{summary['concession']:.2f}",
        "", f"{summary['paid']:.2f}", f"{summary['balance']:.2f}", "", "",
    ])

    if report_type == "all":
        by_category = (
            db.session.query(Expense.category, func.sum(Expense.amount))
            .group_by(Expense.category).order_by(func.sum(Expense.amount).desc()).all()
        )
        writer.writerow([])
        writer.writerow(["EXPENSES BY CATEGORY"])
        writer.writerow(["Category", "Amount"])
        total_expenses = 0
        for cat, amt in by_category:
            writer.writerow([cat, f"{amt:.2f}"])
            total_expenses += amt
        writer.writerow(["Total Expenses", f"{total_expenses:.2f}"])

    return buf, f"apnps-fee-report-{report_type}-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"


# =============================================================================
# Kind: classwise — one row per class+section: expected/concession/payable/
# paid/balance, so the admin can see collection performance across the
# whole school at a glance.
# =============================================================================

def _classwise_rows():
    from models import FeePayment
    paid_by_student = (
        db.session.query(FeePayment.student_id.label("student_id"), func.sum(FeePayment.amount).label("paid"))
        .group_by(FeePayment.student_id).subquery()
    )
    concession_by_student = (
        db.session.query(
            StudentFeeItem.student_id.label("student_id"),
            StudentFeeItem.academic_year.label("academic_year"),
            func.sum(StudentFeeItem.amount).label("concession_total"),
        )
        .filter(StudentFeeItem.category == CONCESSION_CATEGORY)
        .group_by(StudentFeeItem.student_id, StudentFeeItem.academic_year)
        .subquery()
    )

    q = (
        db.session.query(
            Student.class_name, Student.section,
            func.count(Student.id.distinct()).label("student_count"),
            func.coalesce(func.sum(StudentFee.total_fee), 0).label("net_total"),
            func.coalesce(func.sum(concession_by_student.c.concession_total), 0).label("concession_total"),
            func.coalesce(func.sum(paid_by_student.c.paid), 0).label("paid_total"),
        )
        .outerjoin(StudentFee, StudentFee.student_id == Student.id)
        .outerjoin(paid_by_student, paid_by_student.c.student_id == Student.id)
        .outerjoin(
            concession_by_student,
            db.and_(
                concession_by_student.c.student_id == Student.id,
                concession_by_student.c.academic_year == StudentFee.academic_year,
            ),
        )
        .group_by(Student.class_name, Student.section)
        .order_by(Student.class_name, Student.section)
    )

    rows = []
    for class_name, section, count, net_total, concession_total, paid_total in q.all():
        concession_total = abs(concession_total)
        rows.append({
            "class_name": class_name, "section": section or "-", "student_count": count,
            "gross_total": net_total + concession_total, "concession": concession_total,
            "payable": net_total, "paid": paid_total, "balance": net_total - paid_total,
        })
    return rows


def _classwise_context():
    rows = _classwise_rows()
    summary = {
        "classes": len(rows), "students": sum(r["student_count"] for r in rows),
        "gross_total": sum(r["gross_total"] for r in rows), "concession": sum(r["concession"] for r in rows),
        "payable": sum(r["payable"] for r in rows), "paid": sum(r["paid"] for r in rows),
        "balance": sum(r["balance"] for r in rows),
    }
    return dict(classwise_rows=rows, classwise_summary=summary)


def _classwise_print():
    rows = _classwise_rows()
    summary = {
        "classes": len(rows), "students": sum(r["student_count"] for r in rows),
        "gross_total": sum(r["gross_total"] for r in rows), "concession": sum(r["concession"] for r in rows),
        "payable": sum(r["payable"] for r in rows), "paid": sum(r["paid"] for r in rows),
        "balance": sum(r["balance"] for r in rows),
    }
    return render_template("report_print_classwise.html", rows=rows, summary=summary, printed_on=_timestamp())


def _classwise_csv():
    rows = _classwise_rows()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["APNPS Class & Section-wise Fee Summary"])
    writer.writerow([f"Generated: {_timestamp()}"])
    writer.writerow([])
    writer.writerow(["Class", "Section", "Students", "Total Fee", "Concession", "Payable", "Paid", "Balance"])
    for r in rows:
        writer.writerow([
            r["class_name"], r["section"], r["student_count"], f"{r['gross_total']:.2f}",
            f"{r['concession']:.2f}", f"{r['payable']:.2f}", f"{r['paid']:.2f}", f"{r['balance']:.2f}",
        ])
    writer.writerow([])
    writer.writerow([
        "TOTAL", "", sum(r["student_count"] for r in rows), f"{sum(r['gross_total'] for r in rows):.2f}",
        f"{sum(r['concession'] for r in rows):.2f}", f"{sum(r['payable'] for r in rows):.2f}",
        f"{sum(r['paid'] for r in rows):.2f}", f"{sum(r['balance'] for r in rows):.2f}",
    ])
    return buf, f"apnps-classwise-report-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"


# =============================================================================
# Kind: salary — every staff member's monthly salary, paid-to-date, balance,
# plus the full salary payment log (optionally date-filtered) underneath.
# =============================================================================

def _salary_read_filters():
    return request.args.get("date_from", "").strip(), request.args.get("date_to", "").strip()


def _salary_rows():
    paid_subq = (
        db.session.query(SalaryPayment.teacher_id.label("teacher_id"), func.sum(SalaryPayment.amount).label("paid"))
        .group_by(SalaryPayment.teacher_id).subquery()
    )
    q = (
        db.session.query(Teacher, func.coalesce(TeacherSalary.monthly_salary, 0), func.coalesce(paid_subq.c.paid, 0))
        .outerjoin(TeacherSalary, TeacherSalary.teacher_id == Teacher.id)
        .outerjoin(paid_subq, paid_subq.c.teacher_id == Teacher.id)
        .order_by(Teacher.name)
    )
    rows = []
    for t, monthly, paid in q.all():
        balance = monthly - paid
        status = "Paid" if balance <= 0 and monthly > 0 else ("Not Set" if monthly == 0 else ("Partial" if paid > 0 else "Due"))
        rows.append({"teacher": t, "monthly": monthly, "paid": paid, "balance": balance, "status": status})
    return rows


def _salary_payments(date_from, date_to):
    q = SalaryPayment.query.order_by(SalaryPayment.date.desc(), SalaryPayment.id.desc())
    if date_from:
        q = q.filter(SalaryPayment.date >= date_from)
    if date_to:
        q = q.filter(SalaryPayment.date <= date_to)
    return q.all()


def _salary_context():
    date_from, date_to = _salary_read_filters()
    rows = _salary_rows()
    payments = _salary_payments(date_from, date_to)
    summary = {
        "count": len(rows), "monthly_total": sum(r["monthly"] for r in rows),
        "paid": sum(r["paid"] for r in rows), "balance": sum(r["balance"] for r in rows),
        "period_paid": sum(p.amount for p in payments),
    }
    return dict(salary_rows=rows, salary_payments=payments, salary_summary=summary, date_from=date_from, date_to=date_to)


def _salary_print():
    date_from, date_to = _salary_read_filters()
    rows = _salary_rows()
    payments = _salary_payments(date_from, date_to)
    summary = {
        "count": len(rows), "monthly_total": sum(r["monthly"] for r in rows),
        "paid": sum(r["paid"] for r in rows), "balance": sum(r["balance"] for r in rows),
        "period_paid": sum(p.amount for p in payments),
    }
    return render_template(
        "report_print_salary.html", rows=rows, payments=payments, summary=summary,
        date_from=date_from, date_to=date_to, printed_on=_timestamp(),
    )


def _salary_csv():
    date_from, date_to = _salary_read_filters()
    rows = _salary_rows()
    payments = _salary_payments(date_from, date_to)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["APNPS Staff Salary Report"])
    writer.writerow([f"Generated: {_timestamp()}"])
    writer.writerow([])
    writer.writerow(["Staff Name", "Subject / Role", "Monthly Salary", "Paid to Date", "Balance", "Status"])
    for r in rows:
        t = r["teacher"]
        writer.writerow([t.name, t.subject or "", f"{r['monthly']:.2f}", f"{r['paid']:.2f}", f"{r['balance']:.2f}", r["status"]])
    writer.writerow([])
    writer.writerow([
        "TOTAL", "", f"{sum(r['monthly'] for r in rows):.2f}", f"{sum(r['paid'] for r in rows):.2f}",
        f"{sum(r['balance'] for r in rows):.2f}", "",
    ])

    writer.writerow([])
    writer.writerow([f"SALARY PAYMENTS{f' ({date_from} to {date_to})' if date_from or date_to else ' (all time)'}"])
    writer.writerow(["Date", "Staff Name", "Amount", "Note"])
    for p in payments:
        writer.writerow([p.date, p.teacher.name if p.teacher else "", f"{p.amount:.2f}", p.note or ""])
    writer.writerow(["Total Paid in Period", "", f"{sum(p.amount for p in payments):.2f}", ""])

    return buf, f"apnps-salary-report-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"


# =============================================================================
# Kind: expenses — category breakdown + the filtered list of entries.
# =============================================================================

def _expenses_read_filters():
    return (
        request.args.get("date_from", "").strip(), request.args.get("date_to", "").strip(),
        request.args.get("category", "").strip(),
    )


def _expenses_rows(date_from, date_to, category):
    q = Expense.query.order_by(Expense.date.desc(), Expense.id.desc())
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    if category:
        q = q.filter(Expense.category == category)
    return q.all()


def _expenses_by_category(rows):
    totals = {}
    for e in rows:
        totals[e.category] = totals.get(e.category, 0) + e.amount
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def _expenses_context():
    date_from, date_to, category = _expenses_read_filters()
    rows = _expenses_rows(date_from, date_to, category)
    by_category = _expenses_by_category(rows)
    total = sum(e.amount for e in rows)
    return dict(
        expense_rows=rows, expense_by_category=by_category, expense_total=total,
        date_from=date_from, date_to=date_to, expense_category=category, expense_categories=EXPENSE_CATEGORIES,
    )


def _expenses_print():
    date_from, date_to, category = _expenses_read_filters()
    rows = _expenses_rows(date_from, date_to, category)
    by_category = _expenses_by_category(rows)
    total = sum(e.amount for e in rows)
    return render_template(
        "report_print_expenses.html", rows=rows, by_category=by_category, total=total,
        date_from=date_from, date_to=date_to, category=category, printed_on=_timestamp(),
    )


def _expenses_csv():
    date_from, date_to, category = _expenses_read_filters()
    rows = _expenses_rows(date_from, date_to, category)
    by_category = _expenses_by_category(rows)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["APNPS Expenses Report"])
    writer.writerow([f"Generated: {_timestamp()}"])
    if date_from or date_to:
        writer.writerow([f"Period: {date_from or 'earliest'} to {date_to or 'latest'}"])
    if category:
        writer.writerow([f"Category: {category}"])
    writer.writerow([])
    writer.writerow(["EXPENSES BY CATEGORY"])
    writer.writerow(["Category", "Amount"])
    for cat, amt in by_category:
        writer.writerow([cat, f"{amt:.2f}"])
    writer.writerow([])
    writer.writerow(["Title", "Category", "Amount", "Date", "Note"])
    for e in rows:
        writer.writerow([e.title, e.category, f"{e.amount:.2f}", e.date, e.note or ""])
    writer.writerow([])
    writer.writerow(["TOTAL", "", f"{sum(e.amount for e in rows):.2f}", "", ""])

    return buf, f"apnps-expenses-report-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"


# =============================================================================
# Routes
# =============================================================================

@bp.route("/reports")
@login_required
def reports():
    kind = _read_common()
    context = dict(kind=kind)
    if kind == "fee":
        context.update(_fee_reports_context())
    elif kind == "classwise":
        context.update(_classwise_context())
    elif kind == "salary":
        context.update(_salary_context())
    elif kind == "expenses":
        context.update(_expenses_context())
    return render_template("reports.html", **context)


@bp.route("/reports/print")
@login_required
def report_print():
    kind = _read_common()
    if kind == "classwise":
        return _classwise_print()
    if kind == "salary":
        return _salary_print()
    if kind == "expenses":
        return _expenses_print()
    return _fee_print()


@bp.route("/reports/download.csv")
@login_required
def report_csv():
    kind = _read_common()
    if kind == "classwise":
        buf, filename = _classwise_csv()
    elif kind == "salary":
        buf, filename = _salary_csv()
    elif kind == "expenses":
        buf, filename = _expenses_csv()
    else:
        buf, filename = _fee_csv()
    return _csv_response(buf, filename)
