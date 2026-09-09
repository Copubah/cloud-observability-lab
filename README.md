# Cloud Observability Lab

A Python API lab for learning how metrics explain what happened, traces
locate where it happened, and logs explain why.

## Current stage

Phase 3: FastAPI with seeded SQLite users, persistent orders, and
OpenTelemetry request, business, and SQL traces. Metrics, correlated logs,
incident simulation, and infrastructure arrive in later phases.

At the end of each phase, verify the changes, commit them, and push to the
GitHub repository before waiting for explicit confirmation to start the next
phase. The initial commit contains the completed Phases 1–3.

This checkout uses `observer/` as the repository root; no nested project
directory is needed. `app/routes/` holds HTTP handlers and
`app/services/` holds business logic.

## Run locally

Prerequisite: Python 3.12 with pip and venv support.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run commands from the repository root. Development reload restarts the
server when Python files change. It is not a production setting.
No environment variables or external services are required in Phase 3:
traces print to the console by default.
If port 8000 is occupied, use `--port 8001` and update the URLs below.

## Verify

In another terminal:

```bash
curl --fail-with-body -i http://127.0.0.1:8000/health
```

Expect HTTP 200 and `{"status":"healthy"}`. Interactive API documentation
is available at <http://127.0.0.1:8000/docs> and the OpenAPI schema at
<http://127.0.0.1:8000/openapi.json>.

The health endpoint only checks that the process can respond; it does not
claim that a database or telemetry destination is ready.

Stop the server with Ctrl+C and leave the virtual environment with
`deactivate`.

## Database and order flow

Startup creates `data/lab.db` and seeds three fictional users (IDs 1–3).
Restarting preserves orders and does not duplicate seeded users. The default
path is anchored to the repository, regardless of the working directory.
To override it, set `DATABASE_PATH` before starting Uvicorn:

```bash
export DATABASE_PATH=/tmp/observability-lab.db
```

`.env.example` documents this option. The app does not automatically load
`.env` files; use an exported environment variable. The database directory
must be writable. Blank paths and `:memory:` are rejected because separate
connections need the same persistent file.

Each database operation owns its connection and closes it in the same worker
thread. Writes commit on success and roll back on failure. Foreign keys
are enabled on every connection. WAL permits concurrent readers, but SQLite
still allows only one writer at a time; lock contention waits up to five
seconds before raising an error. SQLite here is for a single-instance lab,
not shared storage across ECS tasks. Schema migrations are not implemented.

```text
POST /orders
  validate_order → lookup_customer → calculate_total → save_order
```

Each of these four function calls now has its own OpenTelemetry span.
Request validation requires positive integer IDs and quantities, a product
of 1–100 characters after trimming, and a positive price with at most six
integer digits and two decimal places. Unknown fields are rejected.
The business rule in `validate_order()` caps quantity at 1,000.
Money uses Python Decimal and integer cents in SQLite, avoiding floating-point
arithmetic. JSON responses serialize monetary values as strings.

## API examples

With the server running:

```bash
curl --fail-with-body http://127.0.0.1:8000/users
curl --fail-with-body http://127.0.0.1:8000/users/1
curl -i http://127.0.0.1:8000/users/999

curl --fail-with-body -i http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product":"Cloud Lab Notebook","quantity":2,"price":"19.99"}'

curl -i http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product":"Cloud Lab Notebook","quantity":0,"price":"19.99"}'
```

Expect 200 for user retrieval, 404 for user 999, 201 for the valid order
(price `"19.99"`, total `"39.98"`, generated ID and UTC creation timestamp),
and 422 for zero quantity. An order with customer 999 returns 404 without
saving a row. Malformed input returns 422 before business processing starts.
Unexpected database failures remain server errors rather than being
misreported as client validation errors.

To confirm the order was persisted, using the same environment as the server:

```bash
python - <<'PY'
from app.database import connect, database_path

with connect(database_path()) as connection:
    row = connection.execute(
        "SELECT id, customer_id, quantity, price_cents, total_cents "
        "FROM orders ORDER BY id DESC LIMIT 1"
    ).fetchone()
    print(dict(row) if row else "No orders saved")
PY
```

After the valid example, expect customer 1, quantity 2, price 1999 cents,
and total 3998 cents. Repeat after restarting the server to verify persistence.

## Phase 3: tracing

`app/telemetry.py` configures one process-wide OpenTelemetry SDK provider,
a service resource, a batch processor, and a console or OTLP/HTTP exporter.
FastAPI instrumentation creates a SERVER span for each request and extracts
incoming W3C `traceparent` context. The four business spans share that request's
trace ID and have its span ID as their parent. SQL spans nest inside the
business step that executes them.

```text
POST /orders                          SERVER
├── validate_order                    INTERNAL
├── lookup_customer                   INTERNAL
│   ├── PRAGMA                        CLIENT
│   └── SELECT                        CLIENT
├── calculate_total                   INTERNAL
└── save_order                        INTERNAL
    ├── PRAGMA                        CLIENT
    └── INSERT                        CLIENT
```

The PRAGMA spans come from enabling foreign keys on each connection.
Startup SQL is grouped under a separate `database.initialize` span.
FastAPI's internal ASGI send/receive spans are excluded to keep the tree readable.
Database queries use explicit cursors because the SQLite instrumentation does
not trace `connection.execute()` shortcuts. SQL text contains placeholders;
bound parameters are not captured. Query spans measure execute calls, while
the enclosing business span also covers fetching, connection setup, and commit.

By default, HTTP spans use stable attributes: `http.request.method`,
`http.route`, and `http.response.status_code`. For `/users/1`, the route is
`/users/{id}`. Duration is the span's end time minus its start time.
An exception escaping a business span is recorded as an `exception` event
with a stack trace and marks that span ERROR. Unhandled server failures
produce an ERROR server span and HTTP 500. A handled 404 or 422 leaves the
SERVER span status UNSET, following HTTP tracing semantics; a failed business
child can still be ERROR. Successful spans also normally use UNSET.
Malformed request bodies are rejected before business spans begin.

### Console walkthrough

Install updated dependencies, then start from the repository root:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
export OTEL_SERVICE_NAME=cloud-observability-lab
export OTEL_TRACES_EXPORTER=console
export OTEL_TRACES_SAMPLER=parentbased_always_on
export OTEL_SEMCONV_STABILITY_OPT_IN=http
export OTEL_BSP_SCHEDULE_DELAY=1000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, send an order with a known upstream context:

```bash
curl --fail-with-body -i http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -H 'traceparent: 00-11111111111111111111111111111111-2222222222222222-01' \
  -d '{"customer_id":1,"product":"Cloud Lab Notebook","quantity":2,"price":"19.99"}'
```

Expect HTTP 201. Within roughly one second, the server terminal prints span
JSON with `context.trace_id` equal to `0x11111111111111111111111111111111`.
Find `POST /orders`: its `parent_id` is `0x2222222222222222`. Its generated
`context.span_id` must match the `parent_id` of each of the four business spans.
The request span has `http.response.status_code: 201` and resource
`service.name: cloud-observability-lab`. Children usually print before parents
because they finish first. This demonstrates remote-parent propagation; the
lab still has only one application service at this stage.

To inspect an exception in `validate_order`, send:

```bash
curl -i http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product":"Cloud Lab Notebook","quantity":1001,"price":"19.99"}'
```

Expect HTTP 422 and an ERROR `validate_order` span with an exception event.
The later steps should be absent. Zero quantity would instead fail schema
validation before entering this function.

### Exporter configuration

Supported `OTEL_TRACES_EXPORTER` values are `console` (default), `otlp`, and
`none` (no trace export). Exporter lists are not supported. No metric or log
SDK provider/exporter is configured in this phase. Console span JSON is trace
output, not the structured application logging planned for Phase 5.

When a Collector with an OTLP HTTP receiver is available in Phase 6:

```bash
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_TIMEOUT=5
```

Restart Uvicorn after changing configuration. The generic endpoint automatically
gains `/v1/traces`. If you set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, it takes
precedence and must include the complete path, such as
`http://localhost:4318/v1/traces`. This project supports HTTP/protobuf, not
gRPC; do not point it at port 4317's gRPC receiver. Malformed URL schemes and
unsupported protocols fail configuration early. A wrong path or unreachable
receiver causes exporter errors; requests can still succeed while telemetry
is lost. Keep `console` until the Collector exists.

Later, container networking uses the Collector's service name instead of
`localhost`; an ADOT sidecar in the same ECS task can use `localhost:4318`.
Both accept the same OTLP payload: only environment/endpoint settings change.
Standard exporter headers, TLS certificate and timeout environment settings
are passed through to the OpenTelemetry exporter without hard-coded credentials.

The provider honors SDK sampling variables. With `parentbased_always_on`, new
root traces are sampled and incoming parent sampling decisions are respected.
An incoming `traceparent` ending in `-00` therefore produces no exported spans.
`OTEL_RESOURCE_ATTRIBUTES` adds resource metadata, such as
`deployment.environment.name=local`. The default batch delay is five seconds
unless overridden as above. Order and timing of console output are not a
request-order guarantee.

The app flushes pending spans on lifespan exit, including startup failure.
The SDK's process-exit hook then shuts down the process-wide provider. This
allows repeated application lifespan cycles without replacing the global
provider or adding duplicate exporters. Abrupt termination cannot guarantee
delivery. Start with plain Uvicorn; do not also wrap this app in
`opentelemetry-instrument`, which would compete with programmatic setup.

References: [Python exporters](https://opentelemetry.io/docs/languages/python/exporters/),
[FastAPI instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html),
and [SQLite instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/sqlite3/sqlite3.html).
