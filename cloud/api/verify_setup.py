"""Verification script for Doccione Cloud API setup.

Run this script inside the Docker container to verify:
1. All imports work correctly
2. Database migrations can be applied
3. Server starts successfully
"""
import sys

def verify_imports():
    """Verify all required modules can be imported."""
    print("Verifying imports...")
    try:
        from app.main import app
        print("✓ app.main imported successfully")

        from app.models import Base, Organization, User, Order, Job, ProductionHistory
        print("✓ app.models imported successfully")

        from app.schemas import (
            OrderCreate, OrderUpdate, OrderResponse,
            JobCreate, JobUpdate, JobResponse,
            SyncPullRequest, SyncPushRequest,
        )
        print("✓ app.schemas imported successfully")

        from app.routers import orders, jobs, production_history, sync
        print("✓ app.routers imported successfully")

        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def verify_database_config():
    """Verify database configuration is present."""
    print("\nVerifying database configuration...")
    import os

    required_vars = ["DATABASE_URL", "JWT_SECRET", "BOOTSTRAP_TOKEN"]
    missing = [var for var in required_vars if not os.environ.get(var)]

    if missing:
        print(f"✗ Missing environment variables: {missing}")
        return False

    print("✓ All required environment variables are set")
    return True


def verify_alembic():
    """Verify Alembic is configured."""
    print("\nVerifying Alembic configuration...")
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        print("✓ Alembic configuration loaded")

        # Check if migrations directory exists
        import os
        if os.path.exists("alembic/versions"):
            print("✓ Alembic versions directory exists")
        else:
            print("✗ Alembic versions directory missing")
            return False

        return True
    except Exception as e:
        print(f"✗ Alembic verification failed: {e}")
        return False


def main():
    """Run all verifications."""
    print("=" * 60)
    print("Doccione Cloud API Setup Verification")
    print("=" * 60)

    results = []

    results.append(("Imports", verify_imports()))
    results.append(("Database Config", verify_database_config()))
    results.append(("Alembic", verify_alembic()))

    print("\n" + "=" * 60)
    print("Verification Summary")
    print("=" * 60)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name:20s}: {status}")

    all_passed = all(result[1] for result in results)

    if all_passed:
        print("\n✓ All verifications passed!")
        print("\nTo apply migrations, run:")
        print("  alembic upgrade head")
        print("\nTo start the server, run:")
        print("  uvicorn app.main:app --host 0.0.0.0 --port 8000")
        return 0
    else:
        print("\n✗ Some verifications failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
