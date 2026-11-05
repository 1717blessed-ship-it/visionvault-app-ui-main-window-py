from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from app.database.database import ImageDatabase
from app.database.order_transaction import OrderTransactionError
from app.services.order_operation_service import install_order_integrity, OrderOperationService, OrderOperationConflict


@pytest.fixture
def db(tmp_path):
    value = ImageDatabase(tmp_path/'isolated.db')
    install_order_integrity(value.connection)
    yield value
    value.close()


def create(db):
    return db.create_order_with_details('Cliente',jobs=[{'title':'A','quantity':10,'unit_kind':'item','subtotal':100},
        {'title':'B','quantity':5,'unit_kind':'sheet','subtotal':50}])


def run(db, key='op', order=None, revision=0, apply=create, **kwargs):
    return OrderOperationService(db).execute(actor='device:1',operation_id=key,
        operation_type='snapshot',payload={'fixture':True},order_id=order,expected_revision=revision,
        authorize=lambda actor,oid: True,apply=apply,**kwargs)


def test_create_replay_and_restart(db):
    result = run(db)
    assert result['persisted'] is True
    assert len(db.order_jobs(result['order_id'])) == 2
    assert run(db,apply=lambda _:pytest.fail('replayed')) == result
    db.connection.close()
    # ImageDatabase creates another connection lazily for this thread.
    db._thread_connections.conn = db._create_connection()
    assert run(db,apply=lambda _:pytest.fail('replayed after restart')) == result


@pytest.mark.parametrize('stage',['creation','second_job','design','quantity','commercial','history','revision','journal','before_commit'])
def test_failure_rolls_back_everything(db,stage):
    conn=db.connection
    tables={'creation':'orders','second_job':'order_jobs','design':'order_design_demand_lines',
        'history':'order_events','revision':'order_integrity_revisions','journal':'remote_order_operations'}
    if stage in tables:
        table=tables[stage]
        when="WHEN NEW.title='B'" if stage=='second_job' else ''
        conn.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} {when} BEGIN SELECT RAISE(ABORT,'injected'); END")
        conn.commit()
    def participant(database):
        oid=create(database)
        if stage=='design':
            job=database.order_jobs(oid)[0]
            database.save_order_snapshot(oid,dict(database.order(oid)),[
                {'image_path':'fixture.png','quantity':1,'size_cm':5,'order_job_id':job['id'],'design_line_id':'line'}],database.order_jobs(oid))
        if stage in {'quantity','commercial'}:
            raise ValueError('injected validation')
        return oid
    def fail(_): raise RuntimeError('injected precommit')
    with pytest.raises((ValueError,RuntimeError,sqlite3.DatabaseError)):
        run(db,apply=participant,before_commit=fail if stage=='before_commit' else None)
    for table in ['orders','order_jobs','order_events','order_design_demand_lines','remote_order_operations','order_integrity_revisions','app_events','notification_outbox']:
        assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0,table


def test_direct_desktop_invalidates_revision_and_rollback_does_not(db):
    oid=create(db); service=OrderOperationService(db); before=service.revision(oid)
    db.connection.execute("UPDATE order_jobs SET notes='desktop' WHERE order_id=?",(oid,));db.connection.commit()
    assert service.revision(oid)>before
    with pytest.raises(OrderOperationConflict,match='revision_conflict'):
        run(db,order=oid,revision=before,apply=lambda _:oid)
    current=service.revision(oid)
    with pytest.raises(RuntimeError):
        with db.connection.order_transaction():
            db.connection.execute("UPDATE orders SET client='bad' WHERE id=?",(oid,))
            raise RuntimeError()
    assert service.revision(oid)==current


def test_update_preserves_snapshots_payments_and_detects_collision(db):
    oid=create(db);db.register_order_payment(oid,20,'Efectivo',idempotency_key='payment')
    service=OrderOperationService(db);before=service.revision(oid)
    jobs=db.order_jobs(oid); snapshot=jobs[0]['subtotal']
    def update(database):
        values=dict(database.order(oid));values['observations']='edit'
        database.save_order_snapshot(oid,values,[],database.order_jobs(oid));return oid
    result=run(db,order=oid,revision=before,apply=update)
    assert run(db,order=oid,revision=before,apply=lambda _:pytest.fail('replay'))==result
    assert db.order_jobs(oid)[0]['subtotal']==snapshot
    assert len(db.order_payments(oid))==1
    with pytest.raises(OrderOperationConflict,match='operation_mismatch'):
        run(db,key='op',order=oid,revision=result['revision'],apply=update)


def test_unauthorized_replay(db):
    run(db)
    with pytest.raises(PermissionError):
        OrderOperationService(db).execute(actor='device:1',operation_id='op',operation_type='snapshot',
            payload={'fixture':True},order_id=None,expected_revision=0,authorize=lambda *_:False,apply=create)


def test_same_operation_concurrent(db):
    # ImageDatabase supplies a separate connection for each thread.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:run(db),range(2)))
    assert results[0]==results[1]
    assert db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1
    assert db.connection.execute("SELECT COUNT(*) FROM app_events WHERE event_type='order.created'").fetchone()[0]==1


def test_same_revision_concurrent_only_one_wins(db):
    oid=create(db);revision=OrderOperationService(db).revision(oid)
    def update(database):
        values=dict(database.order(oid));values['observations']='change'
        database.save_order_snapshot(oid,values,[],database.order_jobs(oid));return oid
    def task(key):
        try:return run(db,key=key,order=oid,revision=revision,apply=update)
        except OrderOperationConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(task,['a','b']))
    assert results.count('conflict')==1


def test_cursor_commit_cannot_escape(db):
    with pytest.raises(sqlite3.DatabaseError):
        with db.connection.order_transaction():
            create(db)
            db.connection.cursor().execute('COMMIT')
    assert db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0


def test_migration_historical_copy_is_repeatable_and_raw_connection_updates_revision(db,tmp_path):
    oid=create(db);before=OrderOperationService(db).revision(oid)
    backup=tmp_path/'copy.db'
    with sqlite3.connect(backup) as target: db.connection.backup(target)
    copy=ImageDatabase(backup)
    install_order_integrity(copy.connection)
    assert OrderOperationService(copy).revision(oid)==before
    with sqlite3.connect(backup) as raw:
        raw.execute("UPDATE orders SET observations='legacy route' WHERE id=?",(oid,))
    assert OrderOperationService(copy).revision(oid)>before
    assert OrderOperationService(db).revision(oid)==before
    copy.close()


def test_reservations_reject_reduction_inside_coordinator(tmp_path):
    from tests.test_order_production_service import scenario
    from app.services.order_production_service import OrderProductionService
    from app.services.production_batch_service import ProductionBatchService
    database,oid,jid=scenario(tmp_path,quantity=5,assigned=5)
    install_order_integrity(database.connection)
    ProductionBatchService(database).save(OrderProductionService(database).preview(oid,{jid:3}))
    service=OrderOperationService(database);revision=service.revision(oid)
    def reduce(db):
        jobs=db.order_jobs(oid);jobs[0]['quantity']=1
        db.save_order_snapshot(oid,dict(db.order(oid)),[],jobs);return oid
    with pytest.raises(ValueError):run(database,order=oid,revision=revision,apply=reduce)
    assert service.revision(oid)==revision
    assert database.order_jobs(oid)[0]['quantity']==5
    assert database.connection.execute('SELECT COUNT(*) FROM remote_order_operations').fetchone()[0]==0
    database.close()


def test_migrate_copy_without_touching_historical_source(tmp_path):
    original=ImageDatabase(tmp_path/'legacy.db');oid=create(original)
    copy_path=tmp_path/'migrate-copy.db'
    with sqlite3.connect(copy_path) as target:original.connection.backup(target)
    migrated=ImageDatabase(copy_path)
    install_order_integrity(migrated.connection)
    service=OrderOperationService(migrated)
    assert service.revision(oid)==1
    for _ in range(3):
        migrated.order(oid);migrated.order_jobs(oid);service.revision(oid)
    assert service.revision(oid)==1
    assert original.connection.execute("SELECT 1 FROM sqlite_master WHERE name='order_integrity_revisions'").fetchone() is None
    migrated.close();original.close()


def test_swallowed_outbox_failure_still_aborts_transaction(db):
    db.connection.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON app_events BEGIN SELECT RAISE(ABORT,'outbox fail'); END")
    db.connection.commit()
    with pytest.raises(OrderTransactionError):run(db)
    assert db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
    assert db.connection.execute('SELECT COUNT(*) FROM remote_order_operations').fetchone()[0]==0


def test_cannot_disable_guard_or_mutate_after_receipt(db):
    with pytest.raises(OrderTransactionError):
        with db.connection.order_transaction():db.connection.set_authorizer(None)
    def late(connection):connection.execute("UPDATE orders SET observations='late'")
    with pytest.raises(OrderTransactionError):run(db,before_commit=late)
    assert db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
