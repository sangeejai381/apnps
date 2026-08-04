# APNPS School Admin Portal

Admin-only school ERP for Annai Parvatham Nursery and Primary School — student
records, itemized fee structure, printable fee/salary receipts, staff and
salary tracking, expenses, and an internal notice board.

## Project layout

The app used to be one 1500-line `app.py`. It's now split into small,
connected files so each piece is easy to find and edit:

```
app.py                     # app factory — wires everything together, ~65 lines
config.py                  # database/env configuration
extensions.py              # shared db / csrf objects (avoids circular imports)
helpers.py                 # login guard, academic-year math, fee recompute, startup migrations
models.py                  # all database tables (unchanged from before)
constants.py               # class list, fee categories, expense categories, etc.

blueprints/
  auth.py                  # login (PIN + lockout), logout
  dashboard.py              # overview stats
  students.py               # student list/add/edit/delete, CSV import
  fee_structure.py          # class-level fee template (the "menu")
  fees.py                   # per-student fee items, payments, receipts
  teachers.py                # staff list/add/delete
  salary.py                  # salary structure, payments, receipts
  expenses.py                 # school running expenses
  messages.py                  # shared staff notice board (notifications)

templates/                 # one .html file per page, unchanged names
static/css/style.css       # single stylesheet, school's own rose/wine/gold theme
static/js/script.js        # sidebar toggle, PIN show/hide
```

Each blueprint file only contains routes for its own feature — to change how
fees work, open `blueprints/fees.py`; to change students, open
`blueprints/students.py`. Nothing else needs touching.

## What's in it

- **Students** — add/edit/delete, class + section, CSV bulk import with a
  downloadable template, search & pagination.
- **Fee Structure** — class-wide fee template per academic year (what a new
  student in that class is billed by default), with copy-from-previous-year
  and printable class sheets.
- **Fee Management** — per-student itemized fee breakdown, payments, printable
  receipts. A status banner and footnotes on every fee page make it explicit
  whether a number is "this year" or "all-time" — the main source of the old
  confusion.
- **Teachers/Staff** — records + monthly salary structure, salary payments,
  printable salary receipts.
- **Expenses** — general running costs (books, furniture, repairs, etc.).
- **Notifications** — shared staff notice board (everyone signs in with the
  one admin login, so posts are tagged with whatever name the poster typed).

## Running it

```
pip install -r requirements.txt
python app.py
```

Visit `http://127.0.0.1:5000`. Default login is in `helpers.py`
(`seed_admin`) — email `annaiparvatham.jkpm@gmail.com`, PIN `apnps@2026`.
Change the PIN directly in the `admin` table once you're live.

For production, set `DATABASE_URL` (Postgres/MySQL) and `SECRET_KEY` as
environment variables — see `.env.example`.

## Admin-only, on purpose

There's a single shared admin login — no student/teacher/parent access is
built in, matching how the school currently intends to use this.
