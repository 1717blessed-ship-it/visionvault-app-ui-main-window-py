from copy import deepcopy
import json
import sqlite3
import pytest

from app.database.database import ImageDatabase
from app.services.mobile_order_contract import MobileOrderContract as Contract, MobileOrderContractError


def payload():
    # Exact field names and tuple association encoding emitted by OrderSyncProposal.
    return {"contract_version": 1, "operation_id": "op-1", "client_order_id": "local-1",
            "desktop_order_id": None, "expected_revision": 0, "client": "Cliente prueba",
            "whatsapp": "", "observations": "", "jobs": [{
                "client_job_id": "job-1", "product_code": "fixture", "variant_code": "",
                "material": "", "size": "", "quantity": 100, "unit_kind": "item", "notes": "",
                "designs": [{"association_id": '["job-1","opaque:a"]',
                             "catalog_design_id": "opaque:a", "quantity": 40}]}]}


def test_flutter_v1_partial_complete_and_multiple_jobs():
    data = payload()
    second = deepcopy(data['jobs'][0])
    second.update(client_job_id='job-2', unit_kind='sheet', quantity=2, designs=[])
    data['jobs'].append(second)
    assert Contract.validate(json.loads(json.dumps(data))) == data
    data['jobs'][0]['designs'][0]['quantity'] = 100
    assert Contract.validate(data) == data


@pytest.mark.parametrize('value', [0, -1, True, 1.2, '10', None, 10001])
def test_reject_quantity_without_coercion(value):
    data = payload(); data['jobs'][0]['quantity'] = value
    with pytest.raises(MobileOrderContractError): Contract.validate(data)


@pytest.mark.parametrize('field,value', [('contract_version', True), ('contract_version', 2),
    ('expected_revision', 1), ('operation_id', ''), ('client', ''), ('jobs', []),
    ('desktop_order_id', '0'), ('desktop_order_id', '../1')])
def test_reject_invalid_root(field, value):
    data = payload(); data[field] = value
    with pytest.raises(MobileOrderContractError): Contract.validate(data)


@pytest.mark.parametrize('field', ['price', 'paid_amount', 'status', 'cost_total', 'creator_device_id'])
def test_reject_administrative_fields(field):
    data = payload(); data[field] = 100
    with pytest.raises(MobileOrderContractError): Contract.validate(data)


def test_stable_fingerprint_is_not_persistence_or_idempotency_receipt():
    data = payload()
    reordered = dict(reversed(list(data.items())))
    assert Contract.fingerprint(data) == Contract.fingerprint(reordered)
    changed = deepcopy(data); changed['observations'] = 'edición'
    assert Contract.fingerprint(data) != Contract.fingerprint(changed)
    assert 'persisted' not in Contract.validate(data)
    assert Contract.validate(data) is not data


@pytest.mark.parametrize('duplicate', ['job', 'design', 'association', 'overflow', 'unit'])
def test_no_duplicate_demands_or_mixed_units(duplicate):
    data = payload(); job = data['jobs'][0]
    if duplicate == 'job': data['jobs'].append(deepcopy(job))
    elif duplicate == 'design': job['designs'].append(deepcopy(job['designs'][0]))
    elif duplicate == 'association':
        second = deepcopy(job); second['client_job_id'] = 'different'
        data['jobs'].append(second)
    elif duplicate == 'overflow': job['designs'][0]['quantity'] = 101
    else: job['unit_kind'] = 'units'
    with pytest.raises(MobileOrderContractError): Contract.validate(data)


def test_edit_requires_revision_but_does_not_claim_it_is_current():
    data = payload(); data.update(desktop_order_id='123', expected_revision=2)
    assert Contract.validate(data)['expected_revision'] == 2


def test_size_limit_and_safe_error():
    data = payload(); data['observations'] = 'x' * 70000
    with pytest.raises(MobileOrderContractError) as exc: Contract.validate(data)
    assert exc.value.status == 413
    assert exc.value.response()['persisted'] is False
    assert 'x' * 100 not in json.dumps(exc.value.response())


@pytest.fixture
def catalog(tmp_path):
    db = ImageDatabase(tmp_path/'isolated.db')
    db.connection.execute("INSERT INTO products(code,name,active,created_at,updated_at) VALUES('fixture','Fixture',1,'now','now')")
    product_id = db.connection.execute("SELECT id FROM products WHERE code='fixture'").fetchone()[0]
    db.connection.execute("INSERT INTO product_variants(product_id,code,name,material,size,active,created_at,updated_at) VALUES(?,'variant','Real','Vinilo','5 cm',1,'now','now')", (product_id,))
    db.connection.commit()
    yield db
    db.close()


def test_real_catalog_lookup_is_read_only(catalog):
    data = payload(); data['jobs'][0].update(variant_code='variant', material='Vinilo', size='5 cm')
    before = catalog.connection.total_changes
    assert Contract.check_catalog(catalog.connection, data, lambda opaque: opaque == 'opaque:a') == data
    assert catalog.connection.total_changes == before
    assert catalog.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


@pytest.mark.parametrize('problem,code', [('product','product_invalid'),('variant','variant_invalid'),
    ('inactive','variant_invalid'),('material','catalog_stale'),('design','design_not_found')])
def test_catalog_rejections_never_mutate(catalog, problem, code):
    data = payload(); job = data['jobs'][0]
    if problem == 'product': job['product_code'] = 'missing'
    elif problem == 'variant': job['variant_code'] = 'missing'
    elif problem == 'inactive':
        job['variant_code'] = 'variant'
        catalog.connection.execute("UPDATE product_variants SET active=0 WHERE code='variant'")
        catalog.connection.commit()
    elif problem == 'material': job.update(variant_code='variant', material='Otro', size='5 cm')
    before = catalog.connection.total_changes
    with pytest.raises(MobileOrderContractError) as exc:
        Contract.check_catalog(catalog.connection, data, lambda _: problem != 'design')
    assert exc.value.code == code
    assert catalog.connection.total_changes == before


def test_diagnostic_existing_snapshot_commits_outer_savepoint(tmp_path):
    """Evidence of the blocker, NOT a successful remote-transaction test.

    An outer savepoint wrapper cannot turn this existing UI service into the
    required operation+receipt atomic boundary. Only an isolated DB is used.
    """
    db = ImageDatabase(tmp_path/'commit-boundary.db')
    try:
        order_id = db.create_order_with_details('Antes', jobs=[{
            'title':'Prueba', 'quantity':1, 'unit_kind':'item', 'subtotal':10}])
        values = dict(db.order(order_id)); values['client'] = 'Después'
        db.connection.execute('SAVEPOINT mobile_outer')
        db.save_order_snapshot(order_id, values, [], db.order_jobs(order_id))
        with pytest.raises(sqlite3.OperationalError, match='no such savepoint'):
            db.connection.execute('ROLLBACK TO mobile_outer')
        persisted = db.connection.execute('SELECT client FROM orders WHERE id=?',(order_id,)).fetchone()[0]
        assert persisted == 'Después'
    finally:
        db.close()
