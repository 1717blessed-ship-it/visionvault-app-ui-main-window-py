"""Explicit outer transaction ownership for existing SQLite repositories."""
from contextlib import contextmanager
import sqlite3


class OrderTransactionError(RuntimeError):
    pass


class OrderCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        try:
            return super().execute(sql, parameters)
        except sqlite3.Error:
            if self.connection._order_managed:
                self.connection._order_failed = True
            raise

    def executemany(self, sql, parameters):
        try:
            return super().executemany(sql, parameters)
        except sqlite3.Error:
            if self.connection._order_managed:
                self.connection._order_failed = True
            raise


class OrderConnection(sqlite3.Connection):
    _order_managed = False
    _order_failed = False

    def cursor(self, factory=None):
        if self._order_managed and factory not in (None, OrderCursor):
            self._order_failed = True
            raise OrderTransactionError('Custom cursors are not managed participants.')
        return super().cursor(factory or OrderCursor)

    def executemany(self, sql, parameters):
        try:
            return super().executemany(sql, parameters)
        except sqlite3.Error:
            if self._order_managed:
                self._order_failed = True
            raise

    def commit(self):
        if not self._order_managed:
            return super().commit()

    def rollback(self):
        if self._order_managed:
            self._order_failed = True
        else:
            return super().rollback()

    def __exit__(self, exc_type, exc_value, traceback):
        if self._order_managed:
            if exc_type is not None:
                self._order_failed = True
            return False
        return super().__exit__(exc_type, exc_value, traceback)

    def execute(self, sql, parameters=()):
        if self._order_managed:
            token = sql.strip().split(None, 1)[0].upper() if sql.strip() else ''
            if token in {'BEGIN', 'COMMIT', 'END', 'ROLLBACK', 'VACUUM', 'ATTACH', 'DETACH'}:
                self._order_failed = True
                raise OrderTransactionError('Transaction control is owned by the coordinator.')
        try:
            return super().execute(sql, parameters)
        except sqlite3.Error:
            if self._order_managed:
                self._order_failed = True
            raise

    def executescript(self, sql_script):
        if self._order_managed:
            self._order_failed = True
            raise OrderTransactionError('executescript can commit implicitly; forbidden in managed orders.')
        return super().executescript(sql_script)

    def close(self):
        if self._order_managed:
            self._order_failed = True
            raise OrderTransactionError('Cannot close a managed order connection.')
        return super().close()

    def set_authorizer(self, callback):
        if self._order_managed:
            self._order_failed = True
            raise OrderTransactionError('Cannot replace transaction safeguards inside a participant.')
        return super().set_authorizer(callback)

    @contextmanager
    def order_transaction(self):
        if self._order_managed or self.in_transaction:
            raise OrderTransactionError('A clean connection is required; nested ownership is forbidden.')
        super().execute('BEGIN IMMEDIATE')
        self._order_managed = True
        self._order_failed = False
        finishing = False
        def authorize(action, arg1, arg2, database, origin):
            forbidden = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
                         sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TRIGGER}
            if (action == sqlite3.SQLITE_TRANSACTION and not finishing) or action in forbidden:
                self._order_failed = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        super().set_authorizer(authorize)
        try:
            yield self
            if self._order_failed:
                raise OrderTransactionError('A participating repository failed or requested rollback.')
            finishing = True
            super().commit()
        except BaseException:
            finishing = True
            super().rollback()
            raise
        finally:
            self._order_managed = False
            self._order_failed = False
            super().set_authorizer(None)
