"""Persistence: a deliberately small single-table interface with two backends.

* DynamoTable  — Amazon DynamoDB (used on AWS).
* SqliteTable  — a local SQLite file, used ONLY in local mode and always
  reported as such by /api/runtime. It is not presented as DynamoDB.

Items are dicts with string keys ``pk``/``sk`` and optional GSI keys
``gsi1pk``/``gsi1sk`` and ``gsi2pk``/``gsi2sk``. Writes can be conditional:
``if_not_exists`` (used for alert de-duplication) or ``expect_version``
(optimistic concurrency between the scheduler and coordinators).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


class ConditionFailed(Exception):
    """A conditional write did not apply (item exists / version changed)."""


class Table(Protocol):
    kind: str

    def put(self, item: dict, *, if_not_exists: bool = False, expect_version: int | None = None) -> None: ...
    def get(self, pk: str, sk: str) -> dict | None: ...
    def query(self, pk: str, sk_prefix: str = "", *, index: str | None = None, reverse: bool = False, limit: int | None = None) -> list[dict]: ...
    def delete(self, pk: str, sk: str) -> None: ...


_INDEX_KEYS = {None: ("pk", "sk"), "gsi1": ("gsi1pk", "gsi1sk"), "gsi2": ("gsi2pk", "gsi2sk")}


# --------------------------------------------------------------------------- SQLite (local mode)
class SqliteTable:
    kind = "sqlite-local"

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS items (pk TEXT NOT NULL, sk TEXT NOT NULL, gsi1pk TEXT, gsi1sk TEXT,"
                " gsi2pk TEXT, gsi2sk TEXT, version INTEGER, data TEXT NOT NULL, PRIMARY KEY (pk, sk))"
            )
            self._db.execute("CREATE INDEX IF NOT EXISTS i_gsi1 ON items (gsi1pk, gsi1sk)")
            self._db.execute("CREATE INDEX IF NOT EXISTS i_gsi2 ON items (gsi2pk, gsi2sk)")
            self._db.commit()

    def put(self, item: dict, *, if_not_exists: bool = False, expect_version: int | None = None) -> None:
        data = json.dumps(item, ensure_ascii=False, default=_json_default)
        row = (item["pk"], item["sk"], item.get("gsi1pk"), item.get("gsi1sk"), item.get("gsi2pk"),
               item.get("gsi2sk"), item.get("version"), data)
        with self._lock:
            cur = self._db.cursor()
            if if_not_exists:
                try:
                    cur.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", row)
                except sqlite3.IntegrityError as exc:
                    raise ConditionFailed("item exists") from exc
            elif expect_version is not None:
                cur.execute(
                    "UPDATE items SET gsi1pk=?, gsi1sk=?, gsi2pk=?, gsi2sk=?, version=?, data=? WHERE pk=? AND sk=? AND version=?",
                    (*row[2:], item["pk"], item["sk"], expect_version),
                )
                if cur.rowcount != 1:
                    raise ConditionFailed("version changed")
            else:
                cur.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?)", row)
            self._db.commit()

    def get(self, pk: str, sk: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT data FROM items WHERE pk=? AND sk=?", (pk, sk)).fetchone()
        return json.loads(r[0]) if r else None

    def query(self, pk, sk_prefix="", *, index=None, reverse=False, limit=None):
        kp, ks = _INDEX_KEYS[index]
        sql = f"SELECT data FROM items WHERE {kp}=? AND {ks} LIKE ? ESCAPE '\\' ORDER BY {ks} {'DESC' if reverse else 'ASC'}"
        prefix = sk_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._db.execute(sql, (pk, prefix)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, pk: str, sk: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM items WHERE pk=? AND sk=?", (pk, sk))
            self._db.commit()


# --------------------------------------------------------------------------- DynamoDB (AWS)
class DynamoTable:
    kind = "dynamodb"

    def __init__(self, table_name: str, resource: Any | None = None):
        if resource is None:
            import boto3
            from botocore.config import Config

            resource = boto3.resource("dynamodb", config=Config(retries={"max_attempts": 4, "mode": "standard"}))
        self.table = resource.Table(table_name)
        self.name = table_name

    def put(self, item: dict, *, if_not_exists: bool = False, expect_version: int | None = None) -> None:
        from botocore.exceptions import ClientError

        kwargs: dict[str, Any] = {"Item": _to_dynamo(item)}
        if if_not_exists:
            kwargs["ConditionExpression"] = "attribute_not_exists(pk)"
        elif expect_version is not None:
            kwargs["ConditionExpression"] = "#v = :v"
            kwargs["ExpressionAttributeNames"] = {"#v": "version"}
            kwargs["ExpressionAttributeValues"] = {":v": expect_version}
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionFailed(str(exc)) from exc
            raise

    def get(self, pk: str, sk: str) -> dict | None:
        r = self.table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True)
        return _from_dynamo(r["Item"]) if "Item" in r else None

    def query(self, pk, sk_prefix="", *, index=None, reverse=False, limit=None):
        from boto3.dynamodb.conditions import Key

        kp, ks = _INDEX_KEYS[index]
        cond = Key(kp).eq(pk)
        if sk_prefix:
            cond = cond & Key(ks).begins_with(sk_prefix)
        kwargs: dict[str, Any] = {"KeyConditionExpression": cond, "ScanIndexForward": not reverse}
        if index:
            kwargs["IndexName"] = index
        out: list[dict] = []
        while True:
            r = self.table.query(**kwargs)
            out.extend(_from_dynamo(i) for i in r.get("Items", []))
            if limit and len(out) >= limit:
                return out[:limit]
            if "LastEvaluatedKey" not in r:
                return out
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def delete(self, pk: str, sk: str) -> None:
        self.table.delete_item(Key={"pk": pk, "sk": sk})


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"not serialisable: {type(o)}")


def _to_dynamo(item: dict) -> dict:
    # DynamoDB needs Decimal instead of float; drop None GSI keys (sparse indexes).
    clean = {k: v for k, v in item.items() if not (k.startswith("gsi") and v is None)}
    return json.loads(json.dumps(clean, default=_json_default), parse_float=Decimal)


def _from_dynamo(item: dict) -> dict:
    return json.loads(json.dumps(item, default=_json_default))
