"""Aceptación S3.1 reproducible: copias aisladas, sin operaciones físicas."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database.database import ImageDatabase
from app.services.delivery_readiness import assert_deliverable
from app.services.order_production_service import OrderProductionService


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def main():
    folder = ROOT / 'artifacts' / 'acceptance-s31-20261023' / 'verified-run'
    folder.mkdir(parents=True, exist_ok=False)
    previous = ROOT / 'artifacts' / 'acceptance-s3-20261023'
    operative = ROOT / 'visionvault.db'
    physical = previous / 'physical-pending.db'
    protected = {str(p): digest(p) for p in (operative, physical)}
    report = {'protected_sha256': protected, 'simulated': True, 'physical_operations': False}
    with readonly(operative) as conn:
        report['operative_orders'] = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        report['operative_integrity'] = conn.execute('PRAGMA quick_check').fetchone()[0]
    for label, source in [('partial', '04-remaining.db'), ('complete', '05-closed.db'),
                          ('historical', 'premature-close-probe.db')]:
        path = folder / f'{label}.db'
        with readonly(previous / source) as src, sqlite3.connect(path) as dst:
            src.backup(dst)
        db = ImageDatabase(path, defer_automatic_maintenance=True)
        oid = db.orders()[0]['id']
        before = db.order_financials(oid)
        snapshot = OrderProductionService(db).snapshot(oid)
        result = {'database': str(path), 'snapshot': snapshot,
                  'design_quantities': [d['quantity'] for d in db.order_designs(oid)],
                  'integrity': db.connection.execute('PRAGMA integrity_check').fetchone()[0]}
        if label == 'partial':
            try:
                db.mark_order_delivered(oid)
                raise AssertionError('Se permitió entregar producción pendiente')
            except ValueError as error:
                result['delivery_block'] = str(error)
            assert db.order_financials(oid) == before
            job = snapshot['jobs'][0]
            assert (job['requested'], job['finished'], job['pending_finish']) == (100, 10, 90)
            assert sorted(result['design_quantities']) == [25, 35, 40]
        elif label == 'complete':
            assert_deliverable(db.connection, oid)
            result['verified_deliverable'] = True
        else:
            assert snapshot['anomalies']
            assert db.order(oid)['status'] == 'Entregado'
        result['pre_migration_backups'] = [str(p) for p in (folder / 'backups' / 'automatic').glob('*pre_verified_delivery*.db')]
        db.close()
        reopened = ImageDatabase(path, defer_automatic_maintenance=True)
        assert OrderProductionService(reopened).snapshot(oid) == snapshot
        reopened.close()
        result['reopen_persisted'] = True
        report[label] = result
    with readonly(physical) as conn:
        report['physical_assignments'] = conn.execute('SELECT state,COUNT(*),SUM(quantity) FROM plancha_item_assignments GROUP BY state').fetchall()
        report['physical_print_jobs'] = conn.execute('SELECT COUNT(*) FROM print_jobs').fetchone()[0]
    assert report['physical_assignments'] == [('prepared', 3, 3.0)]
    assert report['physical_print_jobs'] == 0
    assert all(digest(Path(p)) == value for p, value in protected.items())
    report['protected_unchanged'] = True
    (folder / 'observations.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
