# Doccione Cloud API - Example Requests and Responses

This document provides example API requests and responses for the Doccione Cloud API.

## Base URL

```
https://api.doccione.com
```

## Authentication

All API endpoints (except health check and bootstrap) require Bearer token authentication.

### Login

```bash
curl -X POST https://api.doccione.com/api/v1/mobile/auth/login \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "user@example.com",
    "password": "YourPassword123"
  }'
```

**Response:**

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "seller",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001"
  }
}
```

Use the token in the `Authorization` header for subsequent requests:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## Health Check

### GET /api/v1/mobile/health

Check if the API is running and compatible with the mobile app.

```bash
curl https://api.doccione.com/api/v1/mobile/health
```

**Response:**

```json
{
  "status": "ok",
  "service": "doccione-studio",
  "api_version": "v1",
  "mobile_api": true,
  "deployment": "cloud"
}
```

---

## Bootstrap (First Organization Setup)

### POST /api/v1/platform/bootstrap

Create the first organization and owner user. Requires bootstrap token.

```bash
curl -X POST https://api.doccione.com/api/v1/platform/bootstrap \
  -H 'Content-Type: application/json' \
  -H 'X-Bootstrap-Token: YOUR_BOOTSTRAP_TOKEN' \
  -d '{
    "organization_name": "Mi Empresa",
    "organization_slug": "mi-empresa",
    "owner_email": "admin@example.com",
    "owner_password": "SecurePassword123"
  }'
```

**Response (201 Created):**

```json
{
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "owner_id": "550e8400-e29b-41d4-a716-446655440002"
}
```

---

## Orders

### Create Order

### POST /api/v1/orders

Create a new order.

```bash
curl -X POST https://api.doccione.com/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "customer_name": "Juan Pérez",
    "customer_phone": "+54 11 1234-5678",
    "notes": "Entregar por la tarde",
    "urgency": "normal",
    "delivery_date": "2026-08-15T14:00:00Z",
    "subtotal": 1500.00,
    "total": 1650.00,
    "payment_status": "pending",
    "status": "pending"
  }'
```

**Response (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "customer_name": "Juan Pérez",
  "customer_phone": "+54 11 1234-5678",
  "notes": "Entregar por la tarde",
  "urgency": "normal",
  "delivery_date": "2026-08-15T14:00:00Z",
  "subtotal": 1500.00,
  "total": 1650.00,
  "payment_status": "pending",
  "status": "pending",
  "version": 1,
  "deleted_at": null,
  "created_at": "2026-07-30T14:00:00Z",
  "updated_at": "2026-07-30T14:00:00Z"
}
```

### List Orders

### GET /api/v1/orders

List orders with pagination and filtering.

```bash
curl "https://api.doccione.com/api/v1/orders?page=1&page_size=20&status=pending&urgency=high" \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "customer_name": "Juan Pérez",
      "customer_phone": "+54 11 1234-5678",
      "notes": "Entregar por la tarde",
      "urgency": "high",
      "delivery_date": "2026-08-15T14:00:00Z",
      "subtotal": 1500.00,
      "total": 1650.00,
      "payment_status": "pending",
      "status": "pending",
      "version": 1,
      "deleted_at": null,
      "created_at": "2026-07-30T14:00:00Z",
      "updated_at": "2026-07-30T14:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_next": false,
  "has_previous": false
}
```

**Query Parameters:**
- `page` (int, default: 1) - Page number
- `page_size` (int, default: 20, max: 100) - Items per page
- `status` (string) - Filter by status: `pending`, `accepted`, `in_design`, `in_production`, `ready`, `delivered`, `cancelled`
- `payment_status` (string) - Filter by payment status: `pending`, `partial`, `paid`, `cancelled`
- `urgency` (string) - Filter by urgency: `normal`, `high`, `urgent`
- `customer_name` (string) - Filter by customer name (partial match)
- `since` (datetime) - Only return orders updated after this timestamp

### Get Order

### GET /api/v1/orders/{order_id}

Retrieve a specific order by ID.

```bash
curl https://api.doccione.com/api/v1/orders/550e8400-e29b-41d4-a716-446655440010 \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "customer_name": "Juan Pérez",
  "customer_phone": "+54 11 1234-5678",
  "notes": "Entregar por la tarde",
  "urgency": "normal",
  "delivery_date": "2026-08-15T14:00:00Z",
  "subtotal": 1500.00,
  "total": 1650.00,
  "payment_status": "pending",
  "status": "pending",
  "version": 1,
  "deleted_at": null,
  "created_at": "2026-07-30T14:00:00Z",
  "updated_at": "2026-07-30T14:00:00Z"
}
```

### Update Order

### PUT /api/v1/orders/{order_id}

Update an existing order.

```bash
curl -X PUT https://api.doccione.com/api/v1/orders/550e8400-e29b-41d4-a716-446655440010 \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "status": "accepted",
    "payment_status": "partial"
  }'
```

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "customer_name": "Juan Pérez",
  "customer_phone": "+54 11 1234-5678",
  "notes": "Entregar por la tarde",
  "urgency": "normal",
  "delivery_date": "2026-08-15T14:00:00Z",
  "subtotal": 1500.00,
  "total": 1650.00,
  "payment_status": "partial",
  "status": "accepted",
  "version": 2,
  "deleted_at": null,
  "created_at": "2026-07-30T14:00:00Z",
  "updated_at": "2026-07-30T14:05:00Z"
}
```

### Archive Order

### DELETE /api/v1/orders/{order_id}

Soft-delete (archive) an order.

```bash
curl -X DELETE https://api.doccione.com/api/v1/orders/550e8400-e29b-41d4-a716-446655440010 \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response (204 No Content)**

---

## Jobs

### Create Job

### POST /api/v1/jobs

Create a new job for an order.

```bash
curl -X POST https://api.doccione.com/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "order_id": "550e8400-e29b-41d4-a716-446655440010",
    "product_name": "Sticker Sheet Personalizada",
    "material": "Vinyl",
    "dimensions": "10x10cm",
    "job_type": "sticker_sheet",
    "quantity": 10,
    "unit_price": 150.00,
    "subtotal": 1500.00,
    "production_status": "pending",
    "design_status": "pending",
    "print_count": 0,
    "error_count": 0,
    "metadata": {
      "design_file": "design123.pdf",
      "colors": ["red", "blue", "green"]
    }
  }'
```

**Response (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440020",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "order_id": "550e8400-e29b-41d4-a716-446655440010",
  "product_name": "Sticker Sheet Personalizada",
  "material": "Vinyl",
  "dimensions": "10x10cm",
  "job_type": "sticker_sheet",
  "quantity": 10,
  "unit_price": 150.00,
  "subtotal": 1500.00,
  "production_status": "pending",
  "design_status": "pending",
  "print_count": 0,
  "error_count": 0,
  "metadata": {
    "design_file": "design123.pdf",
    "colors": ["red", "blue", "green"]
  },
  "version": 1,
  "deleted_at": null,
  "created_at": "2026-07-30T14:10:00Z",
  "updated_at": "2026-07-30T14:10:00Z"
}
```

**Job Types:**
- `sticker_sheet` - Sheet of multiple stickers
- `individual_sticker` - Single sticker
- `print` - General print job
- `sublimation` - Sublimation print
- `custom_product` - Custom product

### List Jobs

### GET /api/v1/jobs

List jobs with pagination and filtering.

```bash
curl "https://api.doccione.com/api/v1/jobs?page=1&page_size=20&order_id=550e8400-e29b-41d4-a716-446655440010&production_status=pending" \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440020",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "order_id": "550e8400-e29b-41d4-a716-446655440010",
      "product_name": "Sticker Sheet Personalizada",
      "material": "Vinyl",
      "dimensions": "10x10cm",
      "job_type": "sticker_sheet",
      "quantity": 10,
      "unit_price": 150.00,
      "subtotal": 1500.00,
      "production_status": "pending",
      "design_status": "pending",
      "print_count": 0,
      "error_count": 0,
      "metadata": {
        "design_file": "design123.pdf",
        "colors": ["red", "blue", "green"]
      },
      "version": 1,
      "deleted_at": null,
      "created_at": "2026-07-30T14:10:00Z",
      "updated_at": "2026-07-30T14:10:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_next": false,
  "has_previous": false
}
```

**Query Parameters:**
- `page` (int, default: 1) - Page number
- `page_size` (int, default: 20, max: 100) - Items per page
- `order_id` (UUID) - Filter by order ID
- `production_status` (string) - Filter by production status: `pending`, `in_progress`, `completed`, `cancelled`
- `design_status` (string) - Filter by design status: `pending`, `in_progress`, `approved`, `cancelled`
- `job_type` (string) - Filter by job type
- `since` (datetime) - Only return jobs updated after this timestamp

### Get Job

### GET /api/v1/jobs/{job_id}

Retrieve a specific job by ID.

```bash
curl https://api.doccione.com/api/v1/jobs/550e8400-e29b-41d4-a716-446655440020 \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440020",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "order_id": "550e8400-e29b-41d4-a716-446655440010",
  "product_name": "Sticker Sheet Personalizada",
  "material": "Vinyl",
  "dimensions": "10x10cm",
  "job_type": "sticker_sheet",
  "quantity": 10,
  "unit_price": 150.00,
  "subtotal": 1500.00,
  "production_status": "pending",
  "design_status": "pending",
  "print_count": 0,
  "error_count": 0,
  "metadata": {
    "design_file": "design123.pdf",
    "colors": ["red", "blue", "green"]
  },
  "version": 1,
  "deleted_at": null,
  "created_at": "2026-07-30T14:10:00Z",
  "updated_at": "2026-07-30T14:10:00Z"
}
```

### Update Job

### PUT /api/v1/jobs/{job_id}

Update an existing job.

```bash
curl -X PUT https://api.doccione.com/api/v1/jobs/550e8400-e29b-41d4-a716-446655440020 \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "production_status": "in_progress",
    "design_status": "approved",
    "print_count": 5
  }'
```

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440020",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "order_id": "550e8400-e29b-41d4-a716-446655440010",
  "product_name": "Sticker Sheet Personalizada",
  "material": "Vinyl",
  "dimensions": "10x10cm",
  "job_type": "sticker_sheet",
  "quantity": 10,
  "unit_price": 150.00,
  "subtotal": 1500.00,
  "production_status": "in_progress",
  "design_status": "approved",
  "print_count": 5,
  "error_count": 0,
  "metadata": {
    "design_file": "design123.pdf",
    "colors": ["red", "blue", "green"]
  },
  "version": 2,
  "deleted_at": null,
  "created_at": "2026-07-30T14:10:00Z",
  "updated_at": "2026-07-30T14:15:00Z"
}
```

### Archive Job

### DELETE /api/v1/jobs/{job_id}

Soft-delete (archive) a job.

```bash
curl -X DELETE https://api.doccione.com/api/v1/jobs/550e8400-e29b-41d4-a716-446655440020 \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response (204 No Content)**

---

## Production History

### Create Production History Entry

### POST /api/v1/production-history

Record a job status change.

```bash
curl -X POST https://api.doccione.com/api/v1/production-history \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "job_id": "550e8400-e29b-41d4-a716-446655440020",
    "previous_status": "pending",
    "new_status": "in_progress",
    "note": "Started production on machine A1"
  }'
```

**Response (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440030",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "job_id": "550e8400-e29b-41d4-a716-446655440020",
  "user_id": "550e8400-e29b-41d4-a716-446655440002",
  "previous_status": "pending",
  "new_status": "in_progress",
  "note": "Started production on machine A1",
  "created_at": "2026-07-30T14:20:00Z"
}
```

### Get Job Production History

### GET /api/v1/production-history/job/{job_id}

Retrieve all production history entries for a specific job.

```bash
curl https://api.doccione.com/api/v1/production-history/job/550e8400-e29b-41d4-a716-446655440020 \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440030",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "job_id": "550e8400-e29b-41d4-a716-446655440020",
    "user_id": "550e8400-e29b-41d4-a716-446655440002",
    "previous_status": "pending",
    "new_status": "in_progress",
    "note": "Started production on machine A1",
    "created_at": "2026-07-30T14:20:00Z"
  },
  {
    "id": "550e8400-e29b-41d4-a716-446655440031",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "job_id": "550e8400-e29b-41d4-a716-446655440020",
    "user_id": "550e8400-e29b-41d4-a716-446655440002",
    "previous_status": "in_progress",
    "new_status": "completed",
    "note": "Production completed successfully",
    "created_at": "2026-07-30T15:30:00Z"
  }
]
```

---

## Synchronization

### Sync Pull

### GET /api/v1/sync/pull

Pull changed records from the server for offline synchronization.

```bash
curl "https://api.doccione.com/api/v1/sync/pull?since=2026-07-30T10:00:00Z&table=orders" \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response:**

```json
{
  "orders": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "customer_name": "Juan Pérez",
      "customer_phone": "+54 11 1234-5678",
      "notes": "Entregar por la tarde",
      "urgency": "normal",
      "delivery_date": "2026-08-15T14:00:00Z",
      "subtotal": 1500.00,
      "total": 1650.00,
      "payment_status": "partial",
      "status": "accepted",
      "version": 2,
      "deleted_at": null,
      "created_at": "2026-07-30T14:00:00Z",
      "updated_at": "2026-07-30T14:05:00Z"
    }
  ],
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440020",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "order_id": "550e8400-e29b-41d4-a716-446655440010",
      "product_name": "Sticker Sheet Personalizada",
      "material": "Vinyl",
      "dimensions": "10x10cm",
      "job_type": "sticker_sheet",
      "quantity": 10,
      "unit_price": 150.00,
      "subtotal": 1500.00,
      "production_status": "in_progress",
      "design_status": "approved",
      "print_count": 5,
      "error_count": 0,
      "metadata": {
        "design_file": "design123.pdf",
        "colors": ["red", "blue", "green"]
      },
      "version": 2,
      "deleted_at": null,
      "created_at": "2026-07-30T14:10:00Z",
      "updated_at": "2026-07-30T14:15:00Z"
    }
  ],
  "production_history": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440030",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "job_id": "550e8400-e29b-41d4-a716-446655440020",
      "user_id": "550e8400-e29b-41d4-a716-446655440002",
      "previous_status": "pending",
      "new_status": "in_progress",
      "note": "Started production on machine A1",
      "created_at": "2026-07-30T14:20:00Z"
    }
  ],
  "last_sync": "2026-07-30T16:00:00Z"
}
```

**Query Parameters:**
- `since` (datetime, optional) - Only return records updated after this timestamp
- `table` (string, optional) - Filter by table type: `orders`, `jobs`, `production_history`

### Sync Push

### POST /api/v1/sync/push

Push offline changes to the server with conflict detection.

```bash
curl -X POST https://api.doccione.com/api/v1/sync/push \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -d '{
    "orders": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440040",
        "customer_name": "María García",
        "customer_phone": "+54 11 9876-5432",
        "notes": "Pedido creado offline",
        "urgency": "normal",
        "delivery_date": null,
        "subtotal": 500.00,
        "total": 550.00,
        "payment_status": "pending",
        "status": "pending",
        "version": 1,
        "deleted_at": null
      }
    ],
    "jobs": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440050",
        "order_id": "550e8400-e29b-41d4-a716-446655440040",
        "product_name": "Sticker Individual",
        "material": "Vinyl",
        "dimensions": "5x5cm",
        "job_type": "individual_sticker",
        "quantity": 5,
        "unit_price": 100.00,
        "subtotal": 500.00,
        "production_status": "pending",
        "design_status": "pending",
        "print_count": 0,
        "error_count": 0,
        "metadata": null,
        "version": 1,
        "deleted_at": null
      }
    ]
  }'
```

**Success Response:**

```json
{
  "success": true,
  "conflicts": [],
  "orders_accepted": 1,
  "jobs_accepted": 1,
  "last_sync": "2026-07-30T16:05:00Z"
}
```

**Conflict Response:**

```json
{
  "success": false,
  "conflicts": [
    {
      "type": "order",
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "server_version": 3,
      "client_version": 2,
      "message": "Version conflict: server has newer version"
    }
  ],
  "orders_accepted": 0,
  "jobs_accepted": 0,
  "last_sync": "2026-07-30T16:05:00Z"
}
```

---

## Error Responses

### 401 Unauthorized

```json
{
  "detail": "Invalid token"
}
```

### 404 Not Found

```json
{
  "detail": "Order not found"
}
```

### 409 Conflict

```json
{
  "detail": "Organization already exists"
}
```

### 422 Validation Error

```json
{
  "detail": [
    {
      "loc": ["body", "customer_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Status Values

### Order Status
- `pending` - Order created, not yet accepted
- `accepted` - Order accepted by seller
- `in_design` - Design phase in progress
- `in_production` - Production in progress
- `ready` - Order ready for delivery
- `delivered` - Order delivered to customer
- `cancelled` - Order cancelled

### Payment Status
- `pending` - No payment received
- `partial` - Partial payment received
- `paid` - Full payment received
- `cancelled` - Payment cancelled/refunded

### Urgency
- `normal` - Standard delivery time
- `high` - Priority delivery
- `urgent` - Urgent delivery

### Job Type
- `sticker_sheet` - Sheet of multiple stickers
- `individual_sticker` - Single sticker
- `print` - General print job
- `sublimation` - Sublimation print
- `custom_product` - Custom product

### Production Status
- `pending` - Not started
- `in_progress` - Currently being produced
- `completed` - Production finished
- `cancelled` - Production cancelled

### Design Status
- `pending` - Design not started
- `in_progress` - Design in progress
- `approved` - Design approved
- `cancelled` - Design cancelled
