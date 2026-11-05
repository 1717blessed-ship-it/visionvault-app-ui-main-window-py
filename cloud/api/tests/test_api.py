"""Tests for Doccione Cloud API.

Tests organization isolation, CRUD operations, and synchronization conflicts.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from urllib.parse import quote

# Set test environment variables
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["BOOTSTRAP_TOKEN"] = "test-bootstrap-token"

from app.main import app
from app.config import engine, SessionLocal
from app.dependencies import get_session
from pwdlib import PasswordHash
password_hash = PasswordHash.recommended()
from app.models import Base, Organization, User, Order, Job, ProductionHistory

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend():
    """Run the API contract suite on the asyncio backend used by FastAPI."""
    return "asyncio"


# Test database setup
TEST_DATABASE_URL = "sqlite:///./test.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session: Session):
    """Create a test client with database session override."""
    def override_get_session():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(db_session: Session) -> dict[str, str]:
    """Create a test organization and user, return auth headers."""
    # Create organization
    org = Organization(name="Test Org", slug="test-org")
    db_session.add(org)
    db_session.flush()

    # Create user
    user = User(
        organization_id=org.id,
        email="test@example.com",
        password_hash=password_hash.hash("TestPassword123"),
        role="seller",
        active=True,
    )
    db_session.add(user)
    db_session.commit()

    # Generate token directly to avoid circular import
    import jwt
    from datetime import datetime, timedelta, timezone
    token = jwt.encode(
        {"sub": str(user.id), "org": str(user.organization_id), "role": user.role, "exp": datetime.now(timezone.utc) + timedelta(days=30)},
        "test-secret-key-for-testing-only",
        algorithm="HS256",
    )

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_org_headers(db_session: Session) -> dict[str, str]:
    """Create a second organization and user for isolation tests."""
    # Create different organization
    org = Organization(name="Other Org", slug="other-org")
    db_session.add(org)
    db_session.flush()

    # Create user
    user = User(
        organization_id=org.id,
        email="other@example.com",
        password_hash=password_hash.hash("TestPassword123"),
        role="seller",
        active=True,
    )
    db_session.add(user)
    db_session.commit()

    # Generate token directly to avoid circular import
    import jwt
    from datetime import datetime, timedelta, timezone
    token = jwt.encode(
        {"sub": str(user.id), "org": str(user.organization_id), "role": user.role, "exp": datetime.now(timezone.utc) + timedelta(days=30)},
        "test-secret-key-for-testing-only",
        algorithm="HS256",
    )

    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# Organization Isolation Tests
# ============================================================================

async def test_order_isolation(client: AsyncClient, auth_headers: dict, other_org_headers: dict, db_session: Session):
    """Test that orders are isolated by organization."""
    # Create order in first organization
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    assert response.status_code == 201
    order_id = response.json()["id"]

    # Try to access with second organization's token
    response = await client.get(f"/api/v1/orders/{order_id}", headers=other_org_headers)
    assert response.status_code == 404

    # Verify first organization can still access
    response = await client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(order_id)


async def test_job_isolation(client: AsyncClient, auth_headers: dict, other_org_headers: dict, db_session: Session):
    """Test that jobs are isolated by organization."""
    # Create order in first organization
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Create job in first organization
    job_data = {
        "order_id": order_id,
        "product_name": "Test Product",
        "quantity": 1,
        "unit_price": "50.00",
        "subtotal": "50.00",
    }
    response = await client.post("/api/v1/jobs", json=job_data, headers=auth_headers)
    assert response.status_code == 201
    job_id = response.json()["id"]

    # Try to access with second organization's token
    response = await client.get(f"/api/v1/jobs/{job_id}", headers=other_org_headers)
    assert response.status_code == 404


async def test_list_orders_isolation(client: AsyncClient, auth_headers: dict, other_org_headers: dict, db_session: Session):
    """Test that order lists are isolated by organization."""
    # Create order in first organization
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    await client.post("/api/v1/orders", json=order_data, headers=auth_headers)

    # List orders for first organization
    response = await client.get("/api/v1/orders", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    # List orders for second organization (should be empty)
    response = await client.get("/api/v1/orders", headers=other_org_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 0


# ============================================================================
# CRUD Operation Tests
# ============================================================================

async def test_create_order(client: AsyncClient, auth_headers: dict):
    """Test creating an order."""
    order_data = {
        "customer_name": "Test Customer",
        "customer_phone": "555-1234",
        "notes": "Test notes",
        "urgency": "high",
        "subtotal": "100.00",
        "total": "110.00",
        "payment_status": "pending",
        "status": "pending",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    assert response.status_code == 201

    data = response.json()
    assert data["customer_name"] == "Test Customer"
    assert data["customer_phone"] == "555-1234"
    assert data["notes"] == "Test notes"
    assert data["urgency"] == "high"
    assert float(data["subtotal"]) == 100.00
    assert float(data["total"]) == 110.00
    assert data["payment_status"] == "pending"
    assert data["status"] == "pending"
    assert data["version"] == 1
    assert data["deleted_at"] is None


async def test_get_order(client: AsyncClient, auth_headers: dict):
    """Test retrieving an order."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Get order
    response = await client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == order_id


async def test_update_order(client: AsyncClient, auth_headers: dict):
    """Test updating an order."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Update order
    update_data = {
        "customer_name": "Updated Customer",
        "status": "accepted",
    }
    response = await client.put(f"/api/v1/orders/{order_id}", json=update_data, headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["customer_name"] == "Updated Customer"
    assert data["status"] == "accepted"
    assert data["version"] == 2  # Version should increment


async def test_archive_order(client: AsyncClient, auth_headers: dict, db_session: Session):
    """Test soft-deleting an order."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Archive order
    response = await client.delete(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify it's soft-deleted
    order = db_session.get(Order, UUID(order_id))
    assert order.deleted_at is not None
    assert order.version == 2


async def test_list_orders_with_pagination(client: AsyncClient, auth_headers: dict):
    """Test listing orders with pagination."""
    # Create multiple orders
    for i in range(25):
        order_data = {
            "customer_name": f"Customer {i}",
            "urgency": "normal",
            "subtotal": "100.00",
            "total": "100.00",
        }
        await client.post("/api/v1/orders", json=order_data, headers=auth_headers)

    # Get first page
    response = await client.get("/api/v1/orders?page=1&page_size=20", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 25
    assert len(data["items"]) == 20
    assert data["page"] == 1
    assert data["has_next"] is True
    assert data["has_previous"] is False

    # Get second page
    response = await client.get("/api/v1/orders?page=2&page_size=20", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["page"] == 2
    assert data["has_next"] is False
    assert data["has_previous"] is True


async def test_list_orders_with_filters(client: AsyncClient, auth_headers: dict):
    """Test listing orders with filters."""
    # Create orders with different statuses
    for status in ["pending", "accepted", "in_production"]:
        order_data = {
            "customer_name": f"Customer {status}",
            "urgency": "normal",
            "subtotal": "100.00",
            "total": "100.00",
            "status": status,
        }
        await client.post("/api/v1/orders", json=order_data, headers=auth_headers)

    # Filter by status
    response = await client.get("/api/v1/orders?status=accepted", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["status"] == "accepted"


async def test_create_job(client: AsyncClient, auth_headers: dict):
    """Test creating a job."""
    # Create order first
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Create job
    job_data = {
        "order_id": order_id,
        "product_name": "Sticker Sheet",
        "material": "Vinyl",
        "dimensions": "10x10",
        "job_type": "sticker_sheet",
        "quantity": 10,
        "unit_price": "5.00",
        "subtotal": "50.00",
        "production_status": "pending",
        "design_status": "pending",
    }
    response = await client.post("/api/v1/jobs", json=job_data, headers=auth_headers)
    assert response.status_code == 201

    data = response.json()
    assert data["product_name"] == "Sticker Sheet"
    assert data["material"] == "Vinyl"
    assert data["dimensions"] == "10x10"
    assert data["job_type"] == "sticker_sheet"
    assert data["quantity"] == 10
    assert float(data["unit_price"]) == 5.00
    assert float(data["subtotal"]) == 50.00


async def test_update_job(client: AsyncClient, auth_headers: dict):
    """Test updating a job."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Create job
    job_data = {
        "order_id": order_id,
        "product_name": "Sticker Sheet",
        "quantity": 10,
        "unit_price": "5.00",
        "subtotal": "50.00",
    }
    response = await client.post("/api/v1/jobs", json=job_data, headers=auth_headers)
    job_id = response.json()["id"]

    # Update job
    update_data = {
        "product_name": "Updated Sticker",
        "production_status": "in_progress",
    }
    response = await client.put(f"/api/v1/jobs/{job_id}", json=update_data, headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["production_status"] == "in_progress"
    assert data["print_count"] == 0
    assert data["version"] == 2


async def test_create_production_history(client: AsyncClient, auth_headers: dict):
    """Test creating a production history entry."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Create job
    job_data = {
        "order_id": order_id,
        "product_name": "Sticker Sheet",
        "quantity": 10,
        "unit_price": "5.00",
        "subtotal": "50.00",
    }
    response = await client.post("/api/v1/jobs", json=job_data, headers=auth_headers)
    job_id = response.json()["id"]

    # Create production history
    history_data = {
        "job_id": job_id,
        "new_status": "in_progress",
        "note": "Started production",
    }
    response = await client.post("/api/v1/production-history", json=history_data, headers=auth_headers)
    assert response.status_code == 201

    data = response.json()
    assert data["job_id"] == job_id
    assert data["previous_status"] is None
    assert data["new_status"] == "in_progress"
    assert data["note"] == "Started production"


# ============================================================================
# Synchronization Conflict Tests
# ============================================================================

async def test_sync_pull(client: AsyncClient, auth_headers: dict):
    """Test sync pull endpoint."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    await client.post("/api/v1/orders", json=order_data, headers=auth_headers)

    # Pull all changes
    response = await client.get("/api/v1/sync/pull", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["customer_name"] == "Test Customer"
    assert "last_sync" in data


async def test_sync_pull_with_since(client: AsyncClient, auth_headers: dict):
    """Test sync pull with timestamp filter."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    await client.post("/api/v1/orders", json=order_data, headers=auth_headers)

    # Pull with future timestamp (should return empty)
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    encoded_timestamp = quote(future_time.isoformat())
    response = await client.get(f"/api/v1/sync/pull?since={encoded_timestamp}", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert len(data["orders"]) == 0


async def test_sync_push_new_order(client: AsyncClient, auth_headers: dict):
    """Test sync push with new order."""
    new_order_id = str(uuid4())
    # Get organization_id from token
    import jwt
    token = auth_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, "test-secret-key-for-testing-only", algorithms=["HS256"])
    org_id = payload["org"]

    push_data = {
        "orders": [
            {
                "id": new_order_id,
                "organization_id": org_id,
                "customer_name": "Synced Customer",
                "customer_phone": None,
                "notes": None,
                "urgency": "normal",
                "delivery_date": None,
                "subtotal": "100.00",
                "total": "100.00",
                "payment_status": "pending",
                "status": "pending",
                "version": 1,
                "deleted_at": None,
            }
        ],
        "jobs": [],
    }

    response = await client.post("/api/v1/sync/push", json=push_data, headers=auth_headers)
    if response.status_code != 200:
        print(f"Error response: {response.text}")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["orders_accepted"] == 1
    assert len(data["conflicts"]) == 0


async def test_sync_push_version_conflict(client: AsyncClient, auth_headers: dict):
    """Test sync push with version conflict."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Try to push with wrong version
    import jwt
    token = auth_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, "test-secret-key-for-testing-only", algorithms=["HS256"])
    org_id = payload["org"]

    push_data = {
        "orders": [
            {
                "id": order_id,
                "organization_id": org_id,
                "customer_name": "Updated Customer",
                "customer_phone": None,
                "notes": None,
                "urgency": "normal",
                "delivery_date": None,
                "subtotal": "100.00",
                "total": "100.00",
                "payment_status": "pending",
                "status": "pending",
                "version": 99,  # Wrong version
                "deleted_at": None,
            }
        ],
        "jobs": [],
    }

    response = await client.post("/api/v1/sync/push", json=push_data, headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is False
    assert data["orders_accepted"] == 0
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["type"] == "order"
    assert data["conflicts"][0]["id"] == order_id
    assert "Version conflict" in data["conflicts"][0]["message"]


async def test_sync_push_organization_conflict(client: AsyncClient, auth_headers: dict, other_org_headers: dict):
    """Test sync push with organization ownership conflict."""
    # Create order in first organization
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Try to push from second organization
    import jwt
    token = other_org_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, "test-secret-key-for-testing-only", algorithms=["HS256"])
    org_id = payload["org"]

    push_data = {
        "orders": [
            {
                "id": order_id,
                "organization_id": org_id,
                "customer_name": "Updated Customer",
                "customer_phone": None,
                "notes": None,
                "urgency": "normal",
                "delivery_date": None,
                "subtotal": "100.00",
                "total": "100.00",
                "payment_status": "pending",
                "status": "pending",
                "version": 1,
                "deleted_at": None,
            }
        ],
        "jobs": [],
    }

    response = await client.post("/api/v1/sync/push", json=push_data, headers=other_org_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is False
    assert len(data["conflicts"]) == 1
    assert "different organization" in data["conflicts"][0]["message"]


async def test_sync_push_new_job(client: AsyncClient, auth_headers: dict):
    """Test sync push with new job."""
    # Create order
    order_data = {
        "customer_name": "Test Customer",
        "urgency": "normal",
        "subtotal": "100.00",
        "total": "100.00",
    }
    response = await client.post("/api/v1/orders", json=order_data, headers=auth_headers)
    order_id = response.json()["id"]

    # Push new job
    new_job_id = str(uuid4())
    import jwt
    token = auth_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, "test-secret-key-for-testing-only", algorithms=["HS256"])
    org_id = payload["org"]

    push_data = {
        "orders": [],
        "jobs": [
            {
                "id": new_job_id,
                "organization_id": org_id,
                "order_id": order_id,
                "product_name": "Synced Job",
                "material": None,
                "dimensions": None,
                "job_type": "sticker_sheet",
                "quantity": 5,
                "unit_price": "10.00",
                "subtotal": "50.00",
                "production_status": "pending",
                "design_status": "pending",
                "print_count": 0,
                "error_count": 0,
                "meta_data": None,
                "version": 1,
                "deleted_at": None,
            }
        ],
    }

    response = await client.post("/api/v1/sync/push", json=push_data, headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["jobs_accepted"] == 1
    assert len(data["conflicts"]) == 0


async def test_sync_push_job_order_not_found(client: AsyncClient, auth_headers: dict):
    """Test sync push with job referencing non-existent order."""
    new_job_id = str(uuid4())
    fake_order_id = str(uuid4())
    import jwt
    token = auth_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, "test-secret-key-for-testing-only", algorithms=["HS256"])
    org_id = payload["org"]

    push_data = {
        "orders": [],
        "jobs": [
            {
                "id": new_job_id,
                "organization_id": org_id,
                "order_id": fake_order_id,
                "product_name": "Synced Job",
                "material": None,
                "dimensions": None,
                "job_type": "sticker_sheet",
                "quantity": 5,
                "unit_price": "10.00",
                "subtotal": "50.00",
                "production_status": "pending",
                "design_status": "pending",
                "print_count": 0,
                "error_count": 0,
                "meta_data": None,
                "version": 1,
                "deleted_at": None,
            }
        ],
    }

    response = await client.post("/api/v1/sync/push", json=push_data, headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is False
    assert len(data["conflicts"]) == 1
    assert "Order not found" in data["conflicts"][0]["message"]


# ============================================================================
# Health Check Test
# ============================================================================

async def test_health_check(client: AsyncClient):
    """Test the health check endpoint."""
    response = await client.get("/api/v1/mobile/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "doccione-studio"
    assert data["api_version"] == "v1"
    assert data["mobile_api"] is True
    assert data["deployment"] == "cloud"
