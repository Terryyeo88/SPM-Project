"""
In-memory stand-in for the Supabase client, for unit tests of
app.events.event_service.

Unit tests can't reach a database (see _forbid_database_in_unit_tests in
conftest.py), so tests that need to see what the service actually WRITES --
which rows were inserted, updated or deleted, and how each query was scoped
-- swap this in for the module's client:

    monkeypatch.setattr(event_service, "supabase", FakeSupabase())

It models only what event_service uses on the events table:
table().select / insert / update / delete, filtered by .eq() / .in_(),
then .execute().
"""

from __future__ import annotations

from types import SimpleNamespace


class FakeSupabase:
    """Rows live in `rows`; every executed query is appended to `calls` as
    {"op", "payload", "filters"} so a test can assert on exactly what was
    written, and how it was filtered."""

    def __init__(self, rows=()):
        self.rows = [dict(row) for row in rows]
        self.calls = []
        self._next_id = 0

    def table(self, name):
        assert name == "events", f"FakeSupabase only models the events table, not {name!r}"
        return _FakeQuery(self)

    def new_id(self):
        self._next_id += 1
        return f"new-event-{self._next_id}"

    def get(self, event_id):
        return next((row for row in self.rows if row["id"] == event_id), None)


class _FakeQuery:
    def __init__(self, db):
        self.db = db
        self.op = "select"
        self.payload = None
        self.filters = []

    def select(self, *args, **kwargs):
        return self  # after insert/update this just asks for the rows back

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, tuple(values)))
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "in" and row.get(column) not in value:
                return False
        return True

    def execute(self):
        self.db.calls.append({"op": self.op, "payload": self.payload, "filters": list(self.filters)})
        if self.op == "insert":
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for row in new_rows:
                stored = {"id": self.db.new_id(), "coordinator_id": None, **row}
                self.db.rows.append(stored)
                created.append(dict(stored))
            return SimpleNamespace(data=created)

        matched = [row for row in self.db.rows if self._matches(row)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        elif self.op == "delete":
            self.db.rows = [row for row in self.db.rows if row not in matched]
        return SimpleNamespace(data=[dict(row) for row in matched])
