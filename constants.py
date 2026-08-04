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

# Same reasoning as CLASS_CHOICES: a fixed list keeps "A" / "a" / "Sec A"
# from becoming silently different sections.
SECTION_CHOICES = [
    "A",
    "B",
    "C",
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

# Fee categories a class's fee structure can be broken into. Same pattern
# as EXPENSE_CATEGORIES: a fixed list keeps "Tuition" vs "tuition" vs "Tuition
# Fee" from becoming silently different categories, with "Other" as an
# escape hatch for anything genuinely school-specific.
# Confirm this list against what the school actually charges before relying
# on it — add or remove categories here, this is the single source of truth
# used everywhere fee categories appear (Fee Structure page, student fee
# items, printable structure sheet).
FEE_CATEGORIES = [
    "Tuition Fee",
    "Book Fee",
    "Transport Fee",
    "Uniform Fee",
    "Exam Fee",
    "Other",
]

# Reasons a per-student concession/discount can be applied for. Stored as a
# StudentFeeItem with a fixed category ("Concession / Discount") and a
# negative amount, so it folds into the existing total-fee calculation
# (StudentFee.total_fee = SUM of all StudentFeeItem amounts for the year)
# without needing a separate schema or separate total-calculation path.
CONCESSION_REASONS = [
    "Sibling Discount",
    "Staff Ward Discount",
    "Merit Scholarship",
    "Need-Based Scholarship",
    "Management Discretion",
    "Other Concession",
]
CONCESSION_CATEGORY = "Concession / Discount"

# Staff notice board / chat — everyone shares one login, so there's no
# per-account message limit to worry about, just sane bounds on a single
# post so one very long paste can't break the page layout.
MESSAGE_PAGE_SIZE = 20
MESSAGE_MAX_LENGTH = 2000
MESSAGE_NAME_MAX_LENGTH = 80
