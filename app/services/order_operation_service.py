"""Internal coordinator only. No HTTP route, no Mobile payload adapter.

Participants are trusted Desktop repositories using the supplied connection.
No filesystem/network/second connection side effects are allowed in apply().
"""
import hashlib
import json

from app.database.order_transaction import OrderConnection, OrderTransactionError


class OrderOperationConflict(ValueError):
    pass


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _sources(connection):
    sources = {}
    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        table = row[0]
        if table.startswith(('sqlite_', 'order_integrity_', 'remote_order_')):
            continue
        columns = {r[1] for r in connection.execute(f'PRAGMA table_info({_identifier(table)})')}
        if table == 'orders':
            sources[table] = 'id'
        elif 'order_id' in columns:
            sources[table] = 'order_id'
        elif 'order_job_id' in columns:
            sources[table] = 'order_job_id'
    return sources


def install_order_integrity(connection):
    """Explicit idempotent migration; never executed merely by importing/reading.

    Caller must back up a deployed DB first. Existing orders start at revision 1.
    A revision is a monotonic mutation token, not a count of user operations.
    """
    if connection.in_transaction:
        raise OrderTransactionError('Migration requires a clean connection.')
    # The existing publisher writes only this durable outbox, never network I/O.
    from app.events.event_repository import EventRepository
    EventRepository(connection).create_tables()
    with connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS order_integrity_revisions (
            order_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0))''')
        connection.execute('''CREATE TABLE IF NOT EXISTS remote_order_operations (
            actor TEXT NOT NULL, operation_id TEXT NOT NULL, operation_type TEXT NOT NULL,
            order_id INTEGER NOT NULL, payload_hash TEXT NOT NULL, revision INTEGER NOT NULL,
            result_json TEXT NOT NULL, PRIMARY KEY(actor,operation_id))''')
        connection.execute('''INSERT OR IGNORE INTO order_integrity_revisions(order_id,revision)
                              SELECT id,1 FROM orders''')
        for table, column in _sources(connection).items():
            for action in ('INSERT', 'UPDATE', 'DELETE'):
                refs = ['NEW'] if action == 'INSERT' else ['OLD'] if action == 'DELETE' else ['OLD', 'NEW']
                statements = []
                for ref in refs:
                    order = f'{ref}.{_identifier(column)}'
                    if column == 'order_job_id':
                        order = f'(SELECT order_id FROM order_jobs WHERE id={order})'
                    # An UPDATE increments once if ownership is unchanged, twice
                    # only when it moves data between two different orders.
                    condition = f'{order} IS NOT NULL'
                    if action == 'UPDATE' and ref == 'NEW':
                        condition += f' AND NEW.{_identifier(column)} IS NOT OLD.{_identifier(column)}'
                    initial = 1 if table == 'orders' and action == 'INSERT' else 2
                    statements.append(f'''INSERT INTO order_integrity_revisions(order_id,revision)
                        SELECT {order},{initial} WHERE {condition}
                        ON CONFLICT(order_id) DO UPDATE SET revision=revision+1;''')
                trigger = _identifier(f'order_integrity_{table}_{action.lower()}')
                connection.execute(f'''CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {action}
                    ON {_identifier(table)} BEGIN {' '.join(statements)} END''')


class OrderOperationService:
    def __init__(self, database):
        self.database = database

    def revision(self, order_id):
        row = self.database.connection.execute(
            'SELECT revision FROM order_integrity_revisions WHERE order_id=?', (order_id,)).fetchone()
        if row is None:
            raise OrderOperationConflict('order_not_found')
        return row[0]

    def execute(self, *, actor, operation_id, operation_type, payload, order_id,
                expected_revision, authorize, apply, before_commit=None, result_data=None):
        """Authorize on every replay, lock, replay/check, apply existing services,
        history/revision, journal, commit, then return. Exceptions roll back all.

        apply(database) returns the created/updated order ID. All price,
        production and payload validation remains in the trusted participant;
        this primitive alone must never be exposed as an arbitrary HTTP action.
        """
        if any(not isinstance(v, str) or not v.strip() or len(v)>120
               for v in (actor, operation_id, operation_type)):
            raise ValueError('Invalid operation identity.')
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('Invalid expected revision.')
        if (order_id is None) != (expected_revision == 0):
            raise ValueError('Create requires revision 0; update requires an order and revision.')
        encoded = json.dumps({'type':operation_type,'order_id':order_id,
            'expected_revision':expected_revision,'payload':payload}, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        connection = self.database.connection
        if not isinstance(connection, OrderConnection):
            raise OrderTransactionError('Repositories must share an OrderConnection.')
        with connection.order_transaction():
            if not authorize(actor, order_id):
                raise PermissionError('Operation not authorized.')
            # No automatic migrations while handling an operation.
            for table in _sources(connection):
                for action in ('insert','update','delete'):
                    trigger = f'order_integrity_{table}_{action}'
                    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)).fetchone():
                        raise OrderTransactionError('Revision coverage requires migration before writes.')
            previous = connection.execute('''SELECT payload_hash,result_json FROM remote_order_operations
                WHERE actor=? AND operation_id=?''', (actor,operation_id)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise OrderOperationConflict('operation_mismatch')
                result = json.loads(previous[1])
                if not authorize(actor, result['order_id']):
                    raise PermissionError('Operation result not authorized.')
            else:
                if order_id is not None and self.revision(order_id) != expected_revision:
                    raise OrderOperationConflict('revision_conflict')
                persisted_id = apply(self.database)
                if type(persisted_id) is not int or (order_id is not None and persisted_id != order_id):
                    raise OrderTransactionError('Participant returned another order.')
                if not connection.execute('SELECT 1 FROM orders WHERE id=?',(persisted_id,)).fetchone():
                    raise OrderTransactionError('Order was not persisted by participant.')
                # The audit record itself is relevant and advances the token.
                connection.execute('''INSERT INTO order_events(order_id,event_type,message,data_json,created_at)
                    VALUES(?,'order.operation','Internal coordinated operation',?,datetime('now'))''',
                    (persisted_id,json.dumps({'actor':actor,'operation_id':operation_id})))
                revision = self.revision(persisted_id)
                result = {'operation_id':operation_id,'order_id':persisted_id,'revision':revision,
                          'payload_hash':digest,'persisted':True}
                if result_data is not None:
                    additional = result_data(connection, persisted_id)
                    if not isinstance(additional, dict) or set(additional) & set(result):
                        raise OrderTransactionError('Invalid confirmed result fields.')
                    result.update(additional)
                connection.execute('''INSERT INTO remote_order_operations
                    (actor,operation_id,operation_type,order_id,payload_hash,revision,result_json)
                    VALUES(?,?,?,?,?,?,?)''',
                    (actor,operation_id,operation_type,persisted_id,digest,revision,json.dumps(result)))
                if before_commit is not None:
                    before_commit(connection)
                if self.revision(persisted_id) != revision:
                    raise OrderTransactionError('Order mutated after receipt preparation.')
        return result
