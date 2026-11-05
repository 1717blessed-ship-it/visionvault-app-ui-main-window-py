"""Test Scenario B: Migration on existing database with organizations and users."""
import sqlite3

# Create database with existing organizations and users tables
conn = sqlite3.connect('test_scenario_b.db')
cursor = conn.cursor()

# Create organizations table (simulating existing API)
cursor.execute('''
CREATE TABLE organizations (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    slug VARCHAR(80) UNIQUE NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
''')

# Create users table (simulating existing API)
cursor.execute('''
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    email VARCHAR(320) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(24) NOT NULL,
    active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
)
''')

# Insert test data
import uuid
org_id = str(uuid.uuid4())
user_id = str(uuid.uuid4())

cursor.execute('INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, datetime("now"), datetime("now"))',
               (org_id, 'Existing Org', 'existing-org'))

cursor.execute('INSERT INTO users (id, organization_id, email, password_hash, role, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
               (user_id, org_id, 'existing@example.com', 'hashed_password', 'owner', 1))

conn.commit()

print("Created existing database with organizations and users tables")
print(f"Organization ID: {org_id}")
print(f"User ID: {user_id}")

# Verify existing data
cursor.execute('SELECT * FROM organizations')
print("Organizations:", cursor.fetchall())

cursor.execute('SELECT * FROM users')
print("Users:", cursor.fetchall())

conn.close()
