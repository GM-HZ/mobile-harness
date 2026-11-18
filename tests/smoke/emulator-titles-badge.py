"""Exercise official session titles and the badge skill through normal DSH entry points."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import time
import uuid

lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
agent = lsp['agent']; support = agent['support']; toolkit = agent['toolkit']
PROFILE = 'alpine/native-benchmark-home/profiles/web'
TITLE_BUNDLE = '@deepseek-ai/dsh-experimental-session-titles-bundle'
BADGE_BUNDLE = '@deepseek-ai/dsh-experimental-badge-skill-bundle'
TITLE_PROVIDER = 'session-title-all-prompts-llm'
DEFAULT_PROVIDER = 'session-title-first-prompt-llm'
BADGE_MODULE = '@deepseek-ai/dsh-skill-badge'
ASSET_SOURCE = Path('vendor/repos/dsh/packages/experimental/skill-badge/assets')
ASSET_DEVICE = 'alpine/.dsh-0.2.2-rc.5/dsh/node_modules/' + BADGE_MODULE + '/assets'
MARKDOWN = '# Badge acceptance\n\n[![](https://img.shields.io/badge/powered_by-dsh-4D6BFE?style=flat-square&logo=deepseek&logoColor=white)](https://github.com/deepseek-ai/deepseek-harness)'


def catalog(emulator, enabled):
    status = {}
    rows = emulator.rpc('pluginManager/listBundles', {})
    keys = ['name', 'availability', 'official', 'optional', 'removable', 'enabled', 'version']
    for name in [TITLE_BUNDLE, BADGE_BUNDLE]:
        row, = [row for row in rows if row['name'] == name]
        assert row['availability'] == 'installation' and row['official'] and row['optional'], row
        assert row['version'] == '0.2.2-rc.5' and not row['removable'] and not row.get('error'), row
        assert row['enabled'] == enabled, row
        status[name] = {key: row[key] for key in keys}
    return status


def switch(emulator, enabled):
    for name in [TITLE_BUNDLE, BADGE_BUNDLE]:
        change = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': enabled})
        assert change['application'] in ['applied', 'restart-required'], change
    return restart(emulator)


def restart(emulator):
    emulator.stop()
    emulator.start()
    return emulator.ready('normal')


def assert_providers(emulator, enabled):
    rows = emulator.rpc('pluginManager/listPlugins', {})
    active = {row['moduleName'] for row in rows if row.get('enabled') and row.get('fiberPhase') == 'active'}
    prefix = '@deepseek-ai/dsh-'
    assert (prefix + TITLE_PROVIDER in active) == enabled, active
    assert (prefix + DEFAULT_PROVIDER in active) != enabled, active
    assert (BADGE_MODULE in active) == enabled, active


def title_events(emulator, session):
    return [row for row in support['events'](emulator, session) if row['type'] == 'session/title']


def prompt(emulator, session, subject):
    calls, _, rows = agent['prompt'](emulator, session, subject + ' Reply only OK. Use no tools.')
    assert not calls, calls
    return [row['seq'] for row in rows if row['type'] == 'user/message' and row['data']['source']['kind'] == 'user']


def wait_title(emulator, session, provider, sequences):
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        events = title_events(emulator, session)
        if events:
            entry = events[-1]
            data = entry['data']
            if data['source'].get('provider') == provider and data['messageSeqs'] == sequences:
                assert data['title'].strip() and '\n' not in data['title'], entry
                assert data['source']['model']['provider'] == 'deepseek-official', entry
                assert data['source']['model']['model'], entry
                return entry
        time.sleep(.25)
    raise AssertionError(f'Expected {provider} title derived from {sequences}, got {events}')


def check_title(emulator, evidence):
    session = support['session'](emulator, True)
    evidence['titleSessionId'] = session
    first = prompt(emulator, session, 'Plan a vegetable garden with tomatoes and lettuce.')
    assert len(first) == 1, first
    evidence['firstProviderTitle'] = wait_title(emulator, session, TITLE_PROVIDER, first)
    second = prompt(emulator, session, 'Expand the garden plan to include a greenhouse and a rainwater irrigation system.')
    assert len(second) == 2 and second[:1] == first, second
    evidence['allPromptsProviderTitle'] = wait_title(emulator, session, TITLE_PROVIDER, second)
    pinned = 'Pinned garden plan ' + uuid.uuid4().hex[:8]
    renamed = emulator.rpc('session/rename', {'request': {'sessionId': session, 'title': pinned}})
    assert renamed['title'] == pinned, renamed
    before = title_events(emulator, session)
    assert before[-1]['seq'] == renamed['seq'] and before[-1]['data'] == {
        'title': pinned, 'messageSeqs': [], 'source': {'kind': 'user'},
    }
    third = prompt(emulator, session, 'Switch to planning a lunar rover instead.')
    assert len(third) == 3
    assert title_events(emulator, session) == before
    evidence['pinnedRestartReadyMs'] = restart(emulator)
    fourth = prompt(emulator, session, 'Now consider adapting the lunar rover for icy caves.')
    assert len(fourth) == 4
    assert title_events(emulator, session) == before
    evidence['pinnedTitleAndEventsSurvivedLaterPromptsAndRestart'] = before[-1]
    print('Verified model-backed title revisions, pin and restart', flush=True)


def skills(emulator, session):
    return {row['name']: row for row in emulator.rpc('skills/list', {'request': {'sessionId': session}})['skills']}


def check_badge(emulator, name, evidence):
    session = support['session'](emulator, True)
    evidence['badgeSessionId'] = session
    badge = skills(emulator, session)['dsh-badge']
    assert badge['modelInvocable'] and 'powered by dsh' in badge['description']
    evidence['catalogSkill'] = badge
    result, _ = agent['tool'](emulator, session, 'skill', {'name': 'dsh-badge'})
    body = toolkit['texts']([result])
    assert '<skill_content name="dsh-badge">' in body and '/dsh-skill-badge/assets' in body, body
    instructions = (ASSET_SOURCE/'dsh-badge.md').read_text().strip()
    assert instructions in body, body
    evidence['skillResultInstructionsSha256'] = hashlib.sha256(instructions.encode()).hexdigest()
    png = agent['read_bytes'](emulator, ASSET_DEVICE+'/dsh-badge.png')
    assert png == (ASSET_SOURCE/'dsh-badge.png').read_bytes()
    evidence['officialPngBytes'] = len(png)
    evidence['officialPngSha256'] = hashlib.sha256(png).hexdigest()

    # The model uses the exact Markdown obtained from the skill, in an owned file.
    output = name + '/badge.md'
    agent['tool'](emulator, session, 'write', {'file_path': output, 'content': MARKDOWN})
    saved = agent['read_bytes'](emulator, 'alpine/workspace-native/' + output)
    assert saved == MARKDOWN.encode()
    evidence['markdownBytes'] = len(saved)
    evidence['markdownSha256'] = hashlib.sha256(saved).hexdigest()
    print('Verified the actual skill, bundled PNG and workspace Markdown', flush=True)


def run(emulator, output):
    name = 'mh-titles-badge-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    remote = '/data/local/tmp/' + name
    originals = {}
    evidence = {'fixture': name}
    try:
        emulator.ready('normal')
        originals = {path: agent['read_bytes'](emulator, path) for path in [
            PROFILE+'/package.json', PROFILE+'/pnpm-lock.yaml', 'mobile-harness-boot.json',
        ]}
        evidence['initialCatalog'] = catalog(emulator, False)
        assert_providers(emulator, False)
        emulator.app('mkdir ' + folder)
        with support['model_key'](emulator):
            cold = support['session'](emulator, True)
            assert 'dsh-badge' not in skills(emulator, cold)
            evidence['enableReadyMs'] = switch(emulator, True)
            evidence['enabledCatalog'] = catalog(emulator, True)
            assert_providers(emulator, True)
            check_title(emulator, evidence)
            check_badge(emulator, name, evidence)
            evidence['disableReadyMs'] = switch(emulator, False)
            evidence['disabledCatalog'] = catalog(emulator, False)
            assert_providers(emulator, False)
            assert 'dsh-badge' not in skills(emulator, evidence['badgeSessionId'])
            new_session = support['session'](emulator, True)
            first = prompt(emulator, new_session, 'Plan a small backyard greenhouse.')
            assert len(first) == 1
            evidence['defaultProviderTitleAfterDisable'] = wait_title(emulator, new_session, DEFAULT_PROVIDER, first)
            assert agent['read_bytes'](emulator, PROFILE+'/pnpm-lock.yaml') == originals[PROFILE+'/pnpm-lock.yaml']
            evidence['bundleTogglesPreservedLock'] = True
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                emulator.app('rm -rf ' + folder)
                for index, (path, data) in enumerate(originals.items()):
                    lsp['restore_bytes'](emulator, path, data, remote+'-'+str(index))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                after = {path: agent['read_bytes'](emulator, path) for path in originals}
                assert after == originals
                evidence['restoredConfigurationHashes'] = {path: hashlib.sha256(data).hexdigest() for path, data in after.items()}
                assert emulator.app(f'test ! -e {folder} && printf ABSENT') == 'ABSENT'
        finally:
            output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, options.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
