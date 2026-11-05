# Phase 3: Mobile Synchronization Implementation

## Overview

Complete implementation of mobile synchronization infrastructure for Doccione Mobile app, enabling real-time data sync between mobile devices and Doccione Studio backend.

## Architecture

### Database Layer (SQLite)
- **DatabaseHelper**: Manages SQLite database with versioning support (v1)
- **Repositories**: Entity-specific data access with upsert operations
  - SyncStateRepository: Manages sync state and cursor tracking
  - JobsRepository: Handles jobs data with indexing
  - OrdersRepository: Handles orders data with indexing
  - ClientsRepository: Handles clients data with indexing

### Models
- **SyncState**: Tracks synchronization state (cursor, snapshot, errors)
- **Job, Order, Client**: Entity models with JSON serialization
- **SyncResult**: Captures sync results with performance metrics

### Network Layer
- **SyncApiClient**: HTTP client for sync endpoints
  - `getCapabilities()`: GET /api/v1/mobile/capabilities
  - `syncPull()`: GET /api/v1/mobile/sync/pull with cursor pagination
  - Timeout handling (30s default)
  - Bearer token authentication
  - Comprehensive error handling

### Synchronization Service
- **SyncService**: Orchestrates synchronization workflow
  - Handler-based architecture for entity processing
  - SQLite transactions for atomic operations
  - Performance metrics tracking (HTTP, Parse, DB, Total)
  - Multi-page sync support with `syncAll()`
  - Resume incomplete sync with `continueSync()`
  - Automatic error recovery and state persistence

### Sync Handlers
- **SyncEntityHandler**: Abstract interface for entity processing
- **JobsSyncHandler**: Processes jobs data
- **OrdersSyncHandler**: Processes orders data
- **ClientsSyncHandler**: Processes clients data

### UI Components
- **SyncStatusCard**: Widget displaying sync status and controls
  - Real-time status updates
  - Progress indication
  - Performance metrics display
  - Entity count display
  - Manual sync trigger
  - Error notifications

## Database Schema

### sync_state Table
```sql
CREATE TABLE sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_completed_snapshot TEXT,
  current_next_cursor TEXT,
  last_sync_at TEXT,
  last_sync_error TEXT
);
```

### jobs Table
```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  job_number TEXT,
  title TEXT,
  status TEXT,
  priority TEXT,
  client_id TEXT,
  assigned_to TEXT,
  due_date TEXT,
  created_at TEXT,
  updated_at TEXT,
  metadata TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_updated ON jobs(updated_at DESC);
CREATE INDEX idx_jobs_client ON jobs(client_id);
```

### orders Table
```sql
CREATE TABLE orders (
  id TEXT PRIMARY KEY,
  order_number TEXT,
  job_id TEXT,
  client_id TEXT,
  status TEXT,
  total_amount REAL,
  currency TEXT,
  order_date TEXT,
  created_at TEXT,
  updated_at TEXT,
  metadata TEXT
);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_updated ON orders(updated_at DESC);
CREATE INDEX idx_orders_job ON orders(job_id);
```

### clients Table
```sql
CREATE TABLE clients (
  id TEXT PRIMARY KEY,
  name TEXT,
  email TEXT,
  phone TEXT,
  company TEXT,
  address TEXT,
  created_at TEXT,
  updated_at TEXT,
  metadata TEXT
);
CREATE INDEX idx_clients_name ON clients(name);
CREATE INDEX idx_clients_updated ON clients(updated_at DESC);
```

## Synchronization Flow

### Initial Sync
1. User clicks "Sincronizar ahora" button
2. SyncService calls `startSync()`
3. Clear any existing cursor and error state
4. Fetch first page from `/api/v1/mobile/sync/pull`
5. Parse response and extract entities
6. Begin SQLite transaction
7. Upsert jobs, orders, clients via handlers
8. Save cursor or mark complete within transaction
9. Commit transaction
10. Return SyncResult with metrics

### Continuation Sync (Multi-page)
1. Check for `next_cursor` in response
2. If present, call `continueSync()`
3. Fetch next page with cursor parameter
4. Repeat upsert process in new transaction
5. Continue until `complete: true` received

### Transaction Guarantees
- All entity upserts and cursor updates in single atomic transaction
- Automatic rollback on any error
- Cursor saved only after successful database commit
- No partial data states

### Error Handling
- Network errors: Retry with exponential backoff (future enhancement)
- HTTP errors: Display error message, save error state
- Database errors: Rollback transaction, preserve cursor
- Invalid cursor: Clear cursor and restart sync

## Performance Metrics

Each sync operation tracks:
- **HTTP Duration**: Time spent in network requests
- **Parse Duration**: Time spent parsing JSON responses
- **Database Duration**: Time spent in SQLite operations
- **Total Duration**: End-to-end sync time

Metrics displayed in UI after successful sync.

## Key Features Implemented

### ✅ Local Storage Infrastructure
- SQLite database with versioning
- Entity repositories with upsert support
- Indexed queries for performance
- Atomic transactions

### ✅ HTTP Sync Client
- RESTful API client with timeout handling
- Bearer token authentication
- Cursor-based pagination
- Comprehensive error handling

### ✅ Generic Synchronization Logic
- Handler-based architecture for extensibility
- Multi-page sync support
- Resume incomplete sync
- Performance metrics tracking
- Transaction safety

### ✅ UI Integration
- Sync status card widget
- Real-time progress updates
- Performance metrics display
- User-friendly error messages
- Manual sync trigger

### ✅ Testing
- Unit tests for database layer
- Unit tests for API client
- Unit tests for sync service
- Mocked HTTP client for testing
- Transaction rollback tests

## File Structure

```
lib/
├── database/
│   ├── database_helper.dart
│   ├── sync_state_repository.dart
│   ├── jobs_repository.dart
│   ├── orders_repository.dart
│   └── clients_repository.dart
├── models/
│   ├── sync_state.dart
│   ├── sync_result.dart
│   ├── job.dart
│   ├── order.dart
│   └── client.dart
├── services/
│   ├── sync_api_client.dart
│   ├── sync_service.dart
│   └── handlers/
│       ├── sync_entity_handler.dart
│       ├── jobs_sync_handler.dart
│       ├── orders_sync_handler.dart
│       └── clients_sync_handler.dart
├── screens/
│   └── home_screen.dart
├── widgets/
│   └── sync_status_card.dart
└── main.dart

test/
├── database/
│   ├── database_helper_test.dart
│   └── repositories_test.dart
└── services/
    ├── sync_api_client_test.dart
    └── sync_service_test.dart
```

## Usage Example

```dart
// Initialize components
final dbHelper = DatabaseHelper();
final syncStateRepo = SyncStateRepository(dbHelper);
final jobsRepo = JobsRepository(dbHelper);
final ordersRepo = OrdersRepository(dbHelper);
final clientsRepo = ClientsRepository(dbHelper);

final apiClient = SyncApiClient(
  baseUrl: 'http://localhost:8000',
  authToken: sessionToken,
);

final syncService = SyncService(
  dbHelper: dbHelper,
  syncStateRepo: syncStateRepo,
  apiClient: apiClient,
);

// Register handlers
syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));
syncService.registerHandler('orders', OrdersSyncHandler(ordersRepo));
syncService.registerHandler('clients', ClientsSyncHandler(clientsRepo));

// Perform full sync
final result = await syncService.syncAll(
  limit: 100,
  onPageComplete: (pageResult) {
    print('Page synced: ${pageResult.jobsUpdated} jobs');
  },
);

if (result.isSuccess) {
  print('Sync completed: ${result.totalDuration.inSeconds}s');
  print('Jobs: ${result.jobsUpdated}');
  print('Orders: ${result.ordersUpdated}');
  print('Clients: ${result.clientsUpdated}');
} else {
  print('Sync failed: ${result.error}');
}
```

## Future Enhancements

### Phase 4 Considerations
1. **Auto-sync on app start**: Trigger sync when app launches
2. **Background sync**: Use WorkManager for periodic background sync
3. **Conflict resolution**: Handle concurrent modifications
4. **Delta sync**: Only sync changed entities
5. **Sync scheduling**: Configure auto-sync intervals
6. **Offline queue**: Queue local changes for upload
7. **Push sync**: Implement syncPush() for local → server
8. **Network monitoring**: React to connectivity changes
9. **Battery optimization**: Respect battery saver mode
10. **Sync progress**: Granular progress reporting

## Dependencies

```yaml
dependencies:
  sqflite: ^2.3.0
  path_provider: ^2.1.1
  path: ^1.8.3
  http: ^1.6.0
  flutter_secure_storage: ^9.0.0

dev_dependencies:
  sqflite_common_ffi: ^2.3.0
```

## API Contract

### GET /api/v1/mobile/capabilities
Response:
```json
{
  "version": "1.0",
  "features": ["sync", "push_notifications"],
  "max_page_size": 1000
}
```

### GET /api/v1/mobile/sync/pull
Parameters:
- `cursor` (optional): Pagination cursor
- `limit` (optional): Page size (default: 100)

Response:
```json
{
  "snapshot_id": "snap-123",
  "next_cursor": "cursor-abc",
  "complete": false,
  "data": {
    "jobs": [...],
    "orders": [...],
    "clients": [...]
  }
}
```

## Commit History

1. **Commit 1**: Local storage infrastructure (DatabaseHelper, repositories, models)
2. **Commit 2**: HTTP sync client (SyncApiClient, SyncResult model)
3. **Commit 3**: Generic synchronization logic (SyncService, handlers, transactions)
4. **Commit 4**: UI components (SyncStatusCard, HomeScreen separation)
5. **Commit 5**: App lifecycle integration (documentation, final integration)

## Testing Coverage

- ✅ Database schema creation and versioning
- ✅ Repository upsert operations (no duplicates)
- ✅ Sync state management
- ✅ HTTP client with mocked responses
- ✅ Multi-page synchronization
- ✅ Transaction rollback on errors
- ✅ Incomplete sync detection and resumption
- ✅ Performance metrics tracking

## Implementation Status

🎉 **Phase 3 Complete**: All core synchronization infrastructure implemented, tested, and integrated into the mobile app.

---

**Implementation Date**: July 21, 2026  
**Version**: 1.0.0  
**Status**: ✅ Complete
