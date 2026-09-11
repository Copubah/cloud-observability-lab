"""Check the trace structure and correlation used by the incident walkthrough."""

from opentelemetry.trace import StatusCode


def test_order_business_spans_are_server_children(client, order, spans):
    assert client.post('/orders', json=order).status_code == 201
    finished = spans.get_finished_spans()
    server = next(span for span in finished if span.name == 'POST /orders')
    for name in ('validate_order', 'lookup_customer', 'calculate_total', 'save_order'):
        matches = [span for span in finished if span.name == name]
        assert len(matches) == 1
        assert matches[0].parent.span_id == server.context.span_id
        assert matches[0].context.trace_id == server.context.trace_id
    assert any('INSERT' in span.name for span in finished)


def test_error_log_links_to_error_span(client, spans, caplog):
    trace_id = '11111111111111111111111111111111'
    response = client.get('/error', headers={
        'traceparent': f'00-{trace_id}-2222222222222222-01',
    })
    assert response.status_code == 500
    server = next(span for span in spans.get_finished_spans() if span.name == 'GET /error')
    assert server.status.status_code == StatusCode.ERROR
    assert any(event.name == 'exception' for event in server.events)
    record = next(record for record in caplog.records if record.message == 'Request failed')
    assert record.otelTraceID == trace_id == format(server.context.trace_id, '032x')
    assert record.otelSpanID == format(server.context.span_id, '016x')
