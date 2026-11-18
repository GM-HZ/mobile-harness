"""Probe the live DeepSeek Messages input boundary using one synthetic request."""

import argparse
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
import urllib.request

URL = 'https://api.deepseek.com/anthropic/v1/messages'
REPEATS = 530_000


def probe(key, output):
    content = 'Reply OK only. Synthetic input follows.\n' + ' 9' * REPEATS
    body = json.dumps({
        'model': 'deepseek-flash', 'max_tokens': 32, 'stream': True,
        'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': content}],
    }, separators=(',', ':')).encode()
    request = urllib.request.Request(URL, body, headers={
        'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json',
    })
    started = time.monotonic()
    facts = {'route': URL, 'model': 'deepseek-flash', 'requestBytes': len(body),
             'syntheticRepetitions': REPEATS, 'streamRequested': True}
    try:
        try:
            response = urllib.request.urlopen(request, timeout=45)
        except HTTPError as error:
            response = error
        with response:
            facts['httpStatus'] = response.getcode()
            if facts['httpStatus'] != 400:
                raise AssertionError(f"Expected provider HTTP 400, got {facts['httpStatus']}")
            raw = json.loads(response.read(64 * 1024))
        provider = raw['error']
        message = str(provider['message']).replace(key, '[redacted]')
        message = re.sub(r' \(request_id: [^)]+\)$', '', message)
        facts['error'] = {'type': provider['type'], 'message': message}
        match = re.search(r'maximum context length is (\d+) tokens.*requested (\d+) tokens', message)
        assert match and provider['type'] == 'invalid_request_error', facts['error']
        facts['providerContextLimit'], facts['providerCountedTokens'] = map(int, match.groups())
        facts['explicitWindowRejection'] = facts['providerCountedTokens'] > facts['providerContextLimit']
        assert facts['explicitWindowRejection']
    finally:
        facts['elapsedMs'] = round((time.monotonic() - started) * 1000)
        output.write_text(json.dumps(facts, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    key = os.environ.get('MH_TEST_DEEPSEEK_API_KEY')
    if not key:
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    probe(key, args.output)
