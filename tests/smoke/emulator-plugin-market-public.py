"""Read, search, and paginate a real public DSH index through the profile proxy."""
import argparse
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import threading
import time
from urllib.parse import urlsplit
import uuid

market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
translation = runpy.run_path(str(Path(__file__).with_name('emulator-cot-translation.py')))
CATALOG = 'https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json'
HARNESS_ENV = translation['HARNESS_ENV']


class CatalogProxy(translation['ConnectProxy']):
    authorities = {urlsplit(CATALOG).netloc + ':443'}


def run(device, port, output):
    ref = '/data/local/tmp/mh-public-market-' + uuid.uuid4().hex[:10]
    bridge = (f'tcp:{port}', 'tcp:19592')
    originals = {}
    evidence = {'source': CATALOG}
    server = None
    reverse = None
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        files = [market['PROFILE'] + '/' + part for part in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
        files += ['mobile-harness-boot.json', HARNESS_ENV]
        originals = {path: translation['profile_bytes'](device, path) for path in files}
        market['market'](device, False)
        upstream = translation['proxy_endpoint']()
        server = ThreadingHTTPServer(('127.0.0.1', 0), CatalogProxy)
        server.upstream, server.calls = upstream, []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        candidate = ('tcp:19773', f'tcp:{server.server_port}')
        assert 'Forwardport result:OK' in device.hdc('rport', *candidate)
        reverse = candidate
        env = (originals[HARNESS_ENV] or b'').rstrip()
        assert not any(name in env.lower() for name in (b'http_proxy', b'https_proxy', b'all_proxy', b'no_proxy'))
        device.stop()
        market['lsp']['restore_bytes'](device, HARNESS_ENV, env + b'\nHTTPS_PROXY=http://127.0.0.1:19773\n', ref)
        device.start()
        device.ready('normal')
        market['switch'](device, True)
        assert device.rpc('pluginMarket/listIndexes', {}) == []
        device.rpc('pluginMarket/setIndexes', {'urls': [CATALOG]})
        start = time.monotonic()
        first = market['search'](device, CATALOG, limit=3)
        evidence['fetchMs'] = round((time.monotonic() - start)*1000)
        assert first['total'] > 1000 and first['nextOffset'] == 3, first
        second = market['search'](device, CATALOG, limit=3, offset=3, fetchedAt=first['fetchedAt'])
        assert first['fetchedAt'] == second['fetchedAt'] and second['nextOffset'] == 6

        def names(result):
            return [row['name'] for row in result['entries']]

        assert set(names(first)).isdisjoint(names(second))
        keyword = names(first)[0]
        results = market['search'](device, CATALOG, text=keyword, sort={'kind': 'relevance'}, limit=10)
        assert keyword in names(results)
        expected_connect = {'authority': urlsplit(CATALOG).netloc + ':443', 'connectStatus': 200}
        assert server.calls == [expected_connect], server.calls
        device.stop()
        device.start()
        evidence['restartReadyMs'] = device.ready('normal')
        assert [row['url'] for row in device.rpc('pluginMarket/listIndexes', {})] == [CATALOG]
        restored = market['search'](device, CATALOG, limit=3)
        assert names(restored) == names(first) and restored['total'] == first['total']
        assert server.calls == [expected_connect, expected_connect], server.calls
        device.rpc('pluginMarket/setIndexes', {'urls': []})
        assert not device.rpc('pluginMarket/listIndexes', {})
        evidence.update(title=first['title'], total=first['total'], firstPage=names(first),
                        secondPage=names(second), searchName=keyword, searchMatches=results['total'],
                        persistedAfterRestart=True, sourceRemoved=True, connects=server.calls)
    finally:
        try:
            if originals:
                device.stop()
                for index, (file, data) in enumerate(originals.items()):
                    if data is None:
                        device.app('rm -f ' + file)
                    else:
                        market['lsp']['restore_bytes'](device, file, data, ref + str(index))
                device.start()
                device.ready('normal')
                assert all(translation['profile_bytes'](device, path) == data for path, data in originals.items())
                market['market'](device, False)
                evidence['configRestored'] = True
        finally:
            if reverse:
                device.hdc('fport', 'rm', *reverse)
            if server:
                server.shutdown()
                server.server_close()
            device.hdc('fport', 'rm', *bridge)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--host-port', type=int, default=19652)
    args = parser.parse_args()
    run(market['support']['Emulator'](args.target, args.host_port), args.host_port, args.output)
