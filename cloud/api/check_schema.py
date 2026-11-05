import sqlite3

conn = sqlite3.connect('test_migration.db')
cursor = conn.cursor()

cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())

cursor.execute('PRAGMA table_info(organizations)')
print('Organizations schema:', cursor.fetchall())

cursor.execute('PRAGMA table_info(jobs)')
print('Jobs schema:', cursor.fetchall())

cursor.execute('PRAGMA table_info(orders)')
print('Orders schema:', cursor.fetchall())

cursor.execute('PRAGMA table_info(users)')
print('Users schema:', cursor.fetchall())

cursor.execute('PRAGMA table_info(production_history)')
print('Production history schema:', cursor.fetchall())

conn.close()
