"""
cleanup.py
----------
Clean up test data and fix the jobs database.
Run once: python3 cleanup.py
"""

from backend.data import database

database.init_all_tables()

print("Cleaning up test data...\n")

# Delete all existing test records
records = database.select("jobs", limit=500)
deleted = 0
for r in records:
    database.delete("jobs", r["id"])
    deleted += 1

print("Deleted " + str(deleted) + " test records.")
print("Database is now clean and ready for real data.")
print("\nDone. Now use the chat to add real job applications.")