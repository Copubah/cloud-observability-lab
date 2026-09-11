"""API contracts, persistence, and deterministic incident behavior."""

import sqlite3
import time

import pytest


def stored_orders(client):
    with sqlite3.connect(client.app.state.database_path) as db:
        return db.execute('SELECT quantity, price_cents, total_cents FROM orders').fetchall()


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'healthy'}


def test_users(client):
    response = client.get('/users')
    assert response.status_code == 200
    users = response.json()
    assert [user['id'] for user in users] == [1, 2, 3]
    response = client.get('/users/1')
    assert response.status_code == 200
    assert response.json() == users[0]


def test_missing_user(client):
    response = client.get('/users/999')
    assert response.status_code == 404
    assert response.json() == {'detail': 'User not found'}


@pytest.mark.parametrize('user_id', ['0', '-1', 'abc', '9223372036854775808'])
def test_invalid_user_id(client, user_id):
    assert client.get(f'/users/{user_id}').status_code == 422


def test_order_persists_exact_money(client, order):
    response = client.post('/orders', json=order)
    assert response.status_code == 201
    result = response.json()
    assert result['id'] == 1
    assert result['price'] == '0.10'
    assert result['total'] == '0.30'
    assert result['customer_id'] == 1
    assert stored_orders(client) == [(3, 10, 30)]


@pytest.mark.parametrize('change', [
    {'quantity': 0}, {'quantity': 1001}, {'quantity': True},
    {'price': '-1.00'}, {'price': '1.001'}, {'product': '   '},
    {'customer_id': 0}, {'unexpected': 'field'},
])
def test_invalid_order_does_not_write(client, order, change):
    response = client.post('/orders', json=order | change)
    assert response.status_code == 422
    assert stored_orders(client) == []


def test_unknown_customer_does_not_write(client, order):
    response = client.post('/orders', json=order | {'customer_id': 999})
    assert response.status_code == 404
    assert response.json() == {'detail': 'Customer not found'}
    assert stored_orders(client) == []


def test_slow(client):
    started = time.monotonic()
    response = client.get('/slow')
    assert response.status_code == 200
    assert response.json()['status'] == 'slow'
    # No upper bound: loaded CI machines may take longer than the requested wait.
    assert time.monotonic() - started >= 2.2


def test_error_is_http_500(client, caplog):
    response = client.get('/error')
    assert response.status_code == 500
    assert response.text == 'Internal Server Error'
    assert any(record.message == 'Request failed' and record.exc_info for record in caplog.records)
    assert client.get('/health').status_code == 200


@pytest.mark.parametrize('errors', [False, True])
@pytest.mark.parametrize('latency', [False, True])
def test_incident_modes(client, order, monkeypatch, latency, errors):
    monkeypatch.setenv('SIMULATE_DB_LATENCY', str(latency).lower())
    monkeypatch.setenv('SIMULATE_ERRORS', str(errors).lower())
    started = time.monotonic()
    response = client.post('/orders', json=order)
    if latency:
        assert time.monotonic() - started >= 2.2
    assert response.status_code == (500 if errors else 201)
    assert stored_orders(client) == ([] if errors else [(3, 10, 30)])
    assert client.get('/health').status_code == 200
