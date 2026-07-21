from app.database.database import ImageDatabase

db = ImageDatabase()
cursor = db.connection.execute('SELECT name FROM sqlite_master WHERE type="table" ORDER BY name')
print('Tablas en la base de datos:')
for row in cursor.fetchall():
    print(f'  - {row[0]}')
db.close()
