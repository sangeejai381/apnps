import csv
import io

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import FeeStructure, Student, StudentFee, StudentFeeItem
from constants import CLASS_CHOICES, SECTION_CHOICES, CSV_IMPORT_COLUMNS
from helpers import (
    current_academic_year, get_page_arg, login_required,
    paginate, recompute_student_fee_total,
)

bp = Blueprint("students", __name__)


@bp.route("/students")
@login_required
def students():
    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    section_filter = request.args.get("section", "").strip()

    query = Student.query
    if class_filter and class_filter in CLASS_CHOICES:
        query = query.filter(Student.class_name == class_filter)
    if section_filter and section_filter in SECTION_CHOICES:
        query = query.filter(Student.section == section_filter)
    if q:
        query = query.filter(db.or_(Student.name.ilike(f"%{q}%"), Student.roll_no.ilike(f"%{q}%")))

    total_matching = query.count()
    pagination = paginate(query.order_by(Student.class_name, Student.section, Student.name))

    return render_template(
        "students.html",
        students=pagination.items,
        pagination=pagination,
        total_matching=total_matching,
        q=q,
        class_filter=class_filter,
        section_filter=section_filter,
        class_choices=CLASS_CHOICES,
        section_choices=SECTION_CHOICES,
    )


@bp.route("/students/add", methods=["GET", "POST"])
@login_required
def add_student():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        section = request.form.get("section", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        dob = request.form.get("dob", "").strip()
        academic_year = request.form.get("academic_year", "").strip() or current_academic_year()

        if not name or not class_name or not section or not roll_no:
            flash("Name, class, section, and roll number are required.")
            return redirect(url_for("students.add_student"))
        if class_name not in CLASS_CHOICES:
            flash("Please choose a class from the list.")
            return redirect(url_for("students.add_student"))
        if section not in SECTION_CHOICES:
            flash("Please choose a section from the list.")
            return redirect(url_for("students.add_student"))

        try:
            total_fee = float(request.form.get("total_fee") or 0)
        except ValueError:
            flash("Total fee must be a number.")
            return redirect(url_for("students.add_student"))
        if total_fee < 0:
            flash("Total fee cannot be negative.")
            return redirect(url_for("students.add_student"))

        if Student.query.filter_by(class_name=class_name, roll_no=roll_no).first():
            flash(f"A student with roll number {roll_no} already exists in {class_name}.")
            return redirect(url_for("students.add_student"))

        try:
            s = Student(
                name=name, class_name=class_name, section=section, roll_no=roll_no, dob=dob,
                parent_name=request.form.get("parent_name", "").strip(),
                contact=request.form.get("contact", "").strip(),
                address=request.form.get("address", "").strip(),
                admission_date=request.form.get("admission_date", "").strip(),
            )
            db.session.add(s)
            db.session.flush()

            # Auto-populate this student's fee items from the class's fee
            # structure for the chosen year; falls back to the manual
            # "Total Fee" field as a single Tuition Fee item.
            structure_rows = FeeStructure.query.filter_by(
                class_name=class_name, academic_year=academic_year
            ).order_by(FeeStructure.id).all()
            if structure_rows:
                for row in structure_rows:
                    db.session.add(StudentFeeItem(
                        student_id=s.id, academic_year=academic_year,
                        category=row.category, custom_category=row.custom_category, amount=row.amount,
                    ))
            elif total_fee > 0:
                db.session.add(StudentFeeItem(
                    student_id=s.id, academic_year=academic_year,
                    category="Tuition Fee", custom_category="", amount=total_fee,
                ))

            # The cached StudentFee.total_fee/academic_year (read by the Fee
            # Ledger and dashboard) always reflects the school's actual
            # current academic year — even if this student's items were
            # entered for a different year — so it can't end up silently
            # showing a past/future year's total instead of "right now".
            recompute_student_fee_total(s, current_academic_year())
            s.fee.due_date = request.form.get("due_date", "").strip()
            db.session.commit()
            if structure_rows:
                flash(f"Student {s.name} added — fee items auto-filled from the {class_name} {academic_year} structure.")
            else:
                flash(f"Student {s.name} added successfully.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this student. Please try again.")
        return redirect(url_for("students.students"))

    return render_template(
        "add_student.html", class_choices=CLASS_CHOICES, section_choices=SECTION_CHOICES,
        default_academic_year=current_academic_year(),
    )


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    s = Student.query.get_or_404(student_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        section = request.form.get("section", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        dob = request.form.get("dob", "").strip()

        if not name or not class_name or not section or not roll_no:
            flash("Name, class, section, and roll number are required.")
            return redirect(url_for("students.edit_student", student_id=s.id))
        if class_name not in CLASS_CHOICES:
            flash("Please choose a class from the list.")
            return redirect(url_for("students.edit_student", student_id=s.id))
        if section not in SECTION_CHOICES:
            flash("Please choose a section from the list.")
            return redirect(url_for("students.edit_student", student_id=s.id))

        existing = Student.query.filter(
            Student.class_name == class_name, Student.roll_no == roll_no, Student.id != s.id,
        ).first()
        if existing:
            flash(f"Another student with roll number {roll_no} already exists in {class_name}.")
            return redirect(url_for("students.edit_student", student_id=s.id))

        try:
            s.name, s.class_name, s.section, s.roll_no, s.dob = name, class_name, section, roll_no, dob
            s.parent_name = request.form.get("parent_name", "").strip()
            s.contact = request.form.get("contact", "").strip()
            s.address = request.form.get("address", "").strip()
            s.admission_date = request.form.get("admission_date", "").strip()
            db.session.commit()
            flash(f"Student {s.name}'s details were updated.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save these changes. Please try again.")
        return redirect(url_for("students.students"))

    return render_template("edit_student.html", s=s, class_choices=CLASS_CHOICES, section_choices=SECTION_CHOICES)


@bp.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    s = Student.query.get_or_404(student_id)
    db.session.delete(s)
    db.session.commit()
    flash("Student record deleted.")
    return redirect(url_for("students.students"))


@bp.route("/students/import/template")
@login_required
def download_import_template():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_IMPORT_COLUMNS)
    writer.writerow(["Kavya R", "UKG", "12", "Ramesh R", "9876543210", "12 Gandhi Street, Salem", "2024-06-03", "18000", "2024-07-15"])
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=apnps_student_import_template.csv"},
    )


@bp.route("/students/import", methods=["GET", "POST"])
@login_required
def import_students():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose a CSV file to upload.")
            return redirect(url_for("students.import_students"))
        if not file.filename.lower().endswith(".csv"):
            flash("Please upload a .csv file.")
            return redirect(url_for("students.import_students"))

        try:
            raw = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Could not read that file. Please save it as a standard CSV (UTF-8) and try again.")
            return redirect(url_for("students.import_students"))

        reader = csv.DictReader(io.StringIO(raw))
        missing_cols = [c for c in ("name", "class_name", "roll_no") if c not in (reader.fieldnames or [])]
        if missing_cols:
            flash(f"The CSV is missing required column(s): {', '.join(missing_cols)}. Download the template below to see the expected format.")
            return redirect(url_for("students.import_students"))

        created = 0
        errors = []
        seen_in_file = set()

        for row_num, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            class_name = (row.get("class_name") or "").strip()
            roll_no = (row.get("roll_no") or "").strip()

            if not name or not class_name or not roll_no:
                errors.append(f"Row {row_num}: name, class, and roll number are required — skipped.")
                continue
            if class_name not in CLASS_CHOICES:
                errors.append(f"Row {row_num}: '{class_name}' is not a valid class ({', '.join(CLASS_CHOICES)}) — skipped.")
                continue

            key = (class_name, roll_no)
            if key in seen_in_file:
                errors.append(f"Row {row_num}: roll number {roll_no} in {class_name} is duplicated within this file — skipped.")
                continue
            if Student.query.filter_by(class_name=class_name, roll_no=roll_no).first():
                errors.append(f"Row {row_num}: roll number {roll_no} in {class_name} already exists — skipped.")
                continue

            total_fee_raw = (row.get("total_fee") or "0").strip()
            try:
                total_fee = float(total_fee_raw) if total_fee_raw else 0.0
                if total_fee < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Row {row_num}: total_fee '{total_fee_raw}' is not a valid non-negative number — skipped.")
                continue

            seen_in_file.add(key)
            s = Student(
                name=name, class_name=class_name, roll_no=roll_no,
                parent_name=(row.get("parent_name") or "").strip(),
                contact=(row.get("contact") or "").strip(),
                address=(row.get("address") or "").strip(),
                admission_date=(row.get("admission_date") or "").strip(),
            )
            db.session.add(s)
            db.session.flush()
            db.session.add(StudentFee(
                student_id=s.id, total_fee=total_fee, due_date=(row.get("due_date") or "").strip(),
            ))
            created += 1

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Something went wrong saving the import. No rows were added — please try again.")
            return redirect(url_for("students.import_students"))

        if created:
            flash(f"Imported {created} student(s) successfully.")
        if errors:
            flash(f"{len(errors)} row(s) were skipped — see details below.")

        return render_template(
            "import_students.html", class_choices=CLASS_CHOICES, import_errors=errors, created_count=created,
        )

    return render_template("import_students.html", class_choices=CLASS_CHOICES, import_errors=None, created_count=None)
