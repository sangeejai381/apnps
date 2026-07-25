# ---------------------------------------------------------------------------
# Shared constants used across app.py and templates.
# Keeping the class list here (instead of a free-text field) is what fixes
# drawback #4: "UKG" vs "ukg" vs "U.K.G" can no longer happen because every
# student record is forced to pick one of these exact values.
# ---------------------------------------------------------------------------

CLASS_CHOICES = [
    "Playgroup",
    "Nursery",
    "LKG",
    "UKG",
    "Std 1",
    "Std 2",
    "Std 3",
    "Std 4",
    "Std 5",
]

PAGE_SIZE = 30

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 10

CSV_IMPORT_COLUMNS = [
    "name",
    "class_name",
    "roll_no",
    "parent_name",
    "contact",
    "address",
    "admission_date",
    "total_fee",
    "due_date",
]

# Fixed list — same reasoning as CLASS_CHOICES: keeps "Books", "books",
# "BOOKS" etc. from becoming silently different categories.
EXPENSE_CATEGORIES = [
    "Books & Stationery",
    "Furniture & Fixtures",
    "Electronics & Equipment",
    "Building & Maintenance",
    "Events & Activities",
    "Transport",
    "Utilities",
    "Other",
]
