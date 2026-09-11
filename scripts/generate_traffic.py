"""Generate repeatable local lab traffic using only the Python standard library."""

import argparse
from collections import Counter
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--timeout', type=float, default=10.0)
    args = parser.parse_args()
    if args.requests < 1:
        parser.error('--requests must be positive')
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error('--delay must be finite and nonnegative')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    url = urlsplit(args.url)
    if (url.scheme not in {'http', 'https'} or not url.hostname
            or url.query or url.fragment or url.username or url.password):
        parser.error('--url must be an HTTP(S) base URL without credentials, query or fragment')
    counts: Counter[str] = Counter()
    routes = ('/health', '/users', '/orders', '/slow', '/error')
    try:
        for index in range(args.requests):
            route = routes[index % len(routes)]
            payload = None
            if route == '/orders':
                payload = json.dumps({
                    'customer_id': 1, 'product': 'Cloud Lab Notebook',
                    'quantity': 2, 'price': '19.99',
                }).encode()
            request = Request(args.url.rstrip('/') + route, data=payload,
                              headers={'Content-Type': 'application/json'})
            started = time.perf_counter()
            try:
                with urlopen(request, timeout=args.timeout) as response:
                    response.read()
                    status = str(response.status)
            except HTTPError as error:
                # /error deliberately returns 500; HTTP failures are useful telemetry.
                status = str(error.code)
                error.close()
            except (URLError, TimeoutError, OSError) as error:
                status = 'transport_error'
                print(f'Connection failed: {error}', flush=True)
            counts[status] += 1
            elapsed = time.perf_counter() - started
            print(f'{index + 1}/{args.requests} {request.get_method()} {route} '
                  f'{status} {elapsed:.3f}s', flush=True)
            if index + 1 < args.requests:
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print('\nInterrupted; summary includes completed attempts.')
        print(json.dumps(dict(sorted(counts.items()))))
        return 130
    print('Summary: ' + json.dumps(dict(sorted(counts.items()))))
    # A deliberate HTTP 500 is expected; inability to reach the API is not.
    return 1 if counts['transport_error'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
