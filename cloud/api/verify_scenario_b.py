"""Verify Scenario B: Existing data preserved, new tables added."""
import sqlite3

conn = sqlite3.connect('test_scenario_b.db')
cursor = conn.cursor()

# Verify existing data still exists
cursor.execute('SELECT * FROM organizations')
print("Organizations after migration:", cursor.fetchall())

cursor.execute('SELECT * FROM users')
print("Users after migration:", cursor.fetchall())

# Verify new tables exist
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print("All tables after migration:", cursor.fetchall())

# Verify new tables are empty
cursor.execute('SELECT COUNT(*) FROM orders')
print("Orders count:", cursor.fetchone()[0])

cursor.execute('SELECT COUNT(*) FROM jobs')
print("Jobs count:", cursor.fetchone()[0])

cursor.execute('SELECT COUNT(*) FROM production_history')
print("Production history count:", cursor.fetchone()[0])

conn.close()
