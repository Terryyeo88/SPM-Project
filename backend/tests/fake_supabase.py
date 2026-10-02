"""
In-memory stand-in for the Supabase client, for unit tests of
app.events.event_service.

Unit tests can't reach a database (see _forbid_database_in_unit_tests in
conftest.py), so tests that need to see what the service actually WRITES --
which rows were inserted, updated or deleted, and how each query was scoped
-- swap this in for the module's client:

    monkeypatch.setattr(event_service, "supabase", FakeSupabase())

It models only what event_service and coordinator_service use:
table().select / insert / update / delete, filtered by .eq() / .neq() /
.in_() / .or_() (only "column.eq.value" conditions), optionally .order(),
then .execute(). Any table name works; rows for "events" are also
reachable as `fake.rows`, other tables through `fake.tables[name]`.
"""

from __future__ import annotations

from types import SimpleNamespace


class FakeSupabase:
    """Rows live in `tables` (events also as `rows`); every executed query
    is appended to `calls` as {"table", "op", "payload", "filters"} so a
    test can assert on exactly what was written, and how it was filtered."""

    def __init__(self, rows=()):
        self.tables = {"events": [dict(row) for row in rows]}
        self.calls = []
        self._next_id = 0

    @property
    def rows(self):
        return self.tables["events"]

    @rows.setter
    def rows(self, value):
        self.tables["events"] = value

    def table(self, name):
        self.tables.setdefault(name, [])
        return _FakeQuery(self, name)

    def new_id(self):
        self._next_id += 1
        return f"new-event-{self._next_id}"

    def get(self, event_id):
        return next((row for row in self.rows if row["id"] == event_id), None)


class _FakeQuery:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.op = "select"
        self.payload = None
        self.filters = []
        self.single_row = False
        self.ordering = None

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

    def single(self):
        self.single_row = True  # .data becomes one row (or None), not a list
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, tuple(values)))
        return self

    def or_(self, conditions):
        # PostgREST syntax "a.eq.1,b.eq.2": a row matches if ANY condition does.
        parsed = tuple(tuple(condition.split(".eq.", 1)) for condition in conditions.split(","))
        self.filters.append(("or", None, parsed))
        return self

    def order(self, column, desc=False):
        self.ordering = (column, desc)
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "neq" and row.get(column) == value:
                return False
            if kind == "in" and row.get(column) not in value:
                return False
            if kind == "or" and not any(str(row.get(col)) == val for col, val in value):
                return False
        return True

    def execute(self):
        self.db.calls.append(
            {"table": self.name, "op": self.op, "payload": self.payload, "filters": list(self.filters)}
        )
        rows = self.db.tables[self.name]
        if self.op == "insert":
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for row in new_rows:
                stored = {"id": self.db.new_id(), "coordinator_id": None, **row}
                rows.append(stored)
                created.append(dict(stored))
            return SimpleNamespace(data=created)

        matched = [row for row in rows if self._matches(row)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        elif self.op == "delete":
            self.db.tables[self.name] = [row for row in rows if row not in matched]
        data = [dict(row) for row in matched]
        if self.ordering:
            column, desc = self.ordering
            data.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.single_row:
            return SimpleNamespace(data=data[0] if data else None)
        return SimpleNamespace(data=data)
