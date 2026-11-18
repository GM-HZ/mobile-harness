"""Verify actual model-proposed recommendation cards and user actions on Phone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import time
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-cot-translation.py')))
support, agent, lsp, market = (flow[key] for key in ['support', 'agent', 'lsp', 'market'])
PROFILE = flow['PROFILE']
NAME = '@deepseek-ai/dsh-personalized-recommendations'
INSPECTOR = flow['inspector']['NAME']
BADGE = '@deepseek-ai/dsh-experimental-badge-skill-bundle'
MODEL = flow['flow']['MODEL']
SKILLS = {'official-plugins', 'personalized-pages'}
ROWS = {'action-cards', 'client-ui-action-cards', 'creation-recommendations',
        'client-ui-creation-recommendations', 'plugin-recommendations', 'client-ui-plugin-recommendations'}
DECISION = 'plugin:action-cards/decision'


def has_bundle(emulator, name, enabled):
    row = market['catalog'](emulator, name)
    assert row and row['availability'] == 'installation' and row['official'] and row['optional'], row
    assert row['enabled'] == enabled and row['version'] == '0.2.2-rc.5' and not row.get('error'), row
    return {key: row[key] for key in ['name', 'enabled', 'version', 'availability']}


def wait_for(read, label, timeout=22):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        value = read()
        if value:
            return value
        time.sleep(.2)
    raise AssertionError('Missing '+label)


def session(emulator, workspace, title, sessions):
    info = emulator.rpc('session/create', {'request': {'workspaceId': workspace}})
    sid = info['sessionId']
    sessions.append(sid)
    emulator.rpc('session/selectModel', {'request': {'sessionId':sid, **MODEL}})
    assert emulator.rpc('session/rename', {'request': {'sessionId':sid,'title':title}})['title']==title
    return sid


def proposal(emulator, sid, skill, args, context):
    calls, results, events = agent['prompt'](emulator,sid,
        context+' This is a controlled local acceptance test. First actually call skill once with '
        +json.dumps({'name':skill})+', then in the same turn call propose_action once with '
        +json.dumps(args,ensure_ascii=False)+'. Use no other tools. Finish with a short invitation to use the card. Do not act on it.',
        timeout=100)
    assert [c['name'] for c in calls]==['skill','propose_action'], calls
    assert json.loads(calls[0]['arguments'])=={'name':skill}
    assert json.loads(calls[1]['arguments'])==args, calls[1]
    assert 'Card shown below your answer' in agent['toolkit']['texts']([results[1]]), results[1]
    assert not any(row['type']==DECISION for row in events)
    return calls[1]['callId'], sum(row['type']=='turn/start' for row in events)


def card_selector(kind):
    return '[data-turn-tail] [data-action-card][data-action="'+kind+'"]'


def card(emulator, run, title, kind):
    flow['open_session'](emulator,run,title)
    selector=card_selector(kind)
    result=flow['wait'](run,f'''(() => {{
      const cards=[...document.querySelectorAll({json.dumps(selector)})];
      if (cards.length!==1 || !cards[0].getClientRects().length) return false;
      const node=cards[0];
      return {{ tail:!!node.closest('[data-turn-tail]'), fit:node.scrollWidth<=node.clientWidth }};
    }})()''','one recommendation card')
    assert result=={'tail':True,'fit':True},result
    return selector


def button(run, selector, labels, *, contains=False):
    relation = 'labels.some(label => text.includes(label))' if contains else 'labels.includes(text)'
    expr = f'''(() => {{
      const labels={json.dumps(labels,ensure_ascii=False)};
      const items=[...document.querySelectorAll({json.dumps(selector)})];
      const item=items.find(node=>{{
        const text=(node.getAttribute('aria-label')||node.textContent||'').trim();
        return {relation} && node.getClientRects().length && !node.disabled;
      }});
      if(!item)return false;
      item.click();
      return true;
    }})()'''
    return flow['wait'](run,expr,'recommendation action '+str(labels))


def decisions(emulator,sid,call_id,phases):
    rows = [row['data'] for row in support['events'](emulator,sid)
            if row['type']==DECISION and row['data']['callId']==call_id]
    last = rows[-1] if rows else None
    return last if last and last['phase'] in phases else None


def open_view(run, labels):
    expression = f'''(() => {{
      const labels={json.dumps(labels,ensure_ascii=False)};
      const tabs=[...document.querySelectorAll('[data-conversation-tabs] [role=tab]')];
      const rows=[...document.querySelectorAll('[role=menu] [role=menuitem]')];
      const visible=node=>node.getClientRects().length>0;
      const view=[...tabs,...rows].find(node=>visible(node)&&labels.includes(node.textContent.trim()));
      if(view){{view.click(); return tabs.includes(view)?'tab':'menu';}}
      const more=[...document.querySelectorAll('button[aria-haspopup=menu]')].find(node=>
        visible(node)&&['更多会话视图','More conversation views'].includes(node.getAttribute('aria-label')));
      if(more?.getAttribute('aria-expanded')==='false') more.click();
      return false;
    }})()'''
    return flow['wait'](run,expression,'conversation view '+str(labels))


def verify_counter(emulator,title,evidence,bundle):
    with flow['browser'](emulator) as run:
        flow['open_session'](emulator,run,title)
        try:
            origin=bundle.removeprefix('@dsh-local/view-').split('-',1)[0]
            evidence['counterViewNavigation']=open_view(run,['Local Counter','本地计数器','local-counter-'+origin])
        except AssertionError:
            evidence['counterVisibleViewLabels']=run('''[...document.querySelectorAll(
              '[data-conversation-tabs] [role=tab], [role=menu] [role=menuitem]'
            )].filter(node=>node.getClientRects().length).map(node=>node.textContent.trim())''')
            raise
        def expect_count(value, description):
            flow['wait'](run,rf'/\bCount\s*:\s*{value}\b|计数\s*[:：]\s*{value}(?!\d)/.test(document.body.innerText)',
                         description)
        expect_count(0,'initial counter value')
        button(run,'button',['Increment','增加','加一','加一（+1）'])
        expect_count(1,'incremented counter value')
        button(run,'button',['Reset','重置'])
        expect_count(0,'reset counter value')


def verify_official(emulator,workspace,name,sessions,evidence):
    title='Official recommendation '+name
    sid=session(emulator,workspace,title,sessions)
    kind='enable_official_plugin'
    args={'action':kind,'title':'DSH Badge Skill','brief':'It adds the official DSH badge to a document.',
          'details':{'name':BADGE}}
    call_id,turns=proposal(emulator,sid,'official-plugins',args,
                         'How can I add the official Powered by DSH badge to a document?')
    before=has_bundle(emulator,BADGE,False)
    with flow['browser'](emulator) as run:
        selector=card(emulator,run,title,kind)
        button(run,selector+' button',['启用','Enable'])
    result=wait_for(lambda:decisions(emulator,sid,call_id,{'enabled','failed','unconfirmed'}),'official recommendation decision')
    assert result['phase']=='enabled',result
    assert sum(row['type']=='turn/start' for row in support['events'](emulator,sid))==turns
    flow['restart'](emulator)
    after=has_bundle(emulator,BADGE,True)
    with flow['browser'](emulator) as run:
        selector=card(emulator,run,title,kind)
        flow['wait'](run,f'''(() => {{
          const status=document.querySelector({json.dumps(selector+' [role=status]')});
          return status && /已启用|Enabled|重启|Restart/.test(status.textContent);
        }})()''','persisted enable decision')
    evidence['officialRecommendation']={'beforeClick':before,'decision':result,'afterRestart':after,'clickStartedNoTurn':True}
    print('Verified official recommendation from model through real ArkWeb enable',flush=True)


def verify_page(emulator,workspace,name,sessions,evidence,create):
    title=('Creator ' if create else 'Page recommendation ')+name
    sid=session(emulator,workspace,title,sessions)
    kind='create_personalized_page'
    args={'action':kind,'title':'Local Counter','brief':'Name the counter tab Local Counter. Display Count: 0 initially, with Increment and Reset buttons. No network, files or other data.',
          'details':{'slot':'sidebar-right'}}
    call_id,turns=proposal(emulator,sid,'personalized-pages',args,
                         'Please propose a small local interface for a counter that starts at 0, increments, and resets. It needs no data source.')
    before = {r['name'] for r in emulator.rpc('pluginManager/listBundles',{})}
    with flow['browser'](emulator) as run:
        selector=card(emulator,run,title,kind)
        button(run,selector+' button',['添加到','Add to'],contains=True)
        button(run,'[role=menuitem]',['会话 Tab','Session tab'],contains=True)
        flow['wait'](run,f'''[...document.querySelectorAll({json.dumps(selector+' button')})].some(
          el=>/会话 Tab|Session tab/.test(el.getAttribute('aria-label')||''))''','chosen session tab')
        button(run,selector+' button',['创建','Create'] if create else ['暂不需要','Not now'])
    if create:
        status=wait_for(lambda:decisions(emulator,sid,call_id,{'installed','failed','interrupted','unconfirmed','cancelled'}),
                        'Creator completion',270)
        evidence['creatorDecision']=status
        assert status['phase']=='installed',status
        bundle=status['data']['bundleName']
        assert re.fullmatch(r'@dsh-local/view-[a-f0-9-]{36}',bundle),bundle
        row=market['catalog'](emulator,bundle)
        assert row and row['installed'],row
        evidence['creatorPluginRows']=[
            {key:row.get(key) for key in ['patchId','fiberPhase']}
            for row in emulator.rpc('pluginManager/listPlugins',{})
            if str(row.get('patchId','')).startswith(bundle+':')
        ]
        if status['data'].get('application')=='restart-required':
            flow['restart'](emulator)
        verify_counter(emulator,title,evidence,bundle)
        evidence['creatorCounterControls']=[0,1,0]
        print('Verified real Creator installed its own plugin',flush=True)
        with flow['browser'](emulator) as run:
            open_view(run,['聊天','对话','Chat'])
            selector=card_selector(kind)
            button(run,selector+' button',['撤销','Undo'])
        removed=wait_for(lambda:decisions(emulator,sid,call_id,{'removed'}),'generated page removal',50)
        if removed['data'].get('application')=='restart-required':
            with flow['browser'](emulator) as run:
                selector=card(emulator,run,title,kind)
                flow['wait'](run,f'''[...document.querySelectorAll({json.dumps(selector+' [role=status]')})].some(
                    status=>/重启 DSH|Restart DSH/.test(status.textContent))''','saved removal restart notice')
            flow['restart'](emulator)
            assert decisions(emulator,sid,call_id,{'removed'})==removed
        assert market['catalog'](emulator,bundle) is None
        evidence['creatorRemoval']=removed
        with flow['browser'](emulator) as run:
            selector=card(emulator,run,title,kind)
            button(run,selector+' button',['恢复','Restore'])
        restored=wait_for(lambda:decisions(emulator,sid,call_id,{'installed'}),'generated page restore',70)
        assert market['catalog'](emulator,bundle)['installed']
        if restored['data'].get('application')=='restart-required':
            flow['restart'](emulator)
        verify_counter(emulator,title,evidence,bundle)
        evidence['creatorLifecycle']={'installed':status,'removed':removed,'restored':restored}
    else:
        result=wait_for(lambda:decisions(emulator,sid,call_id,{'dismissed'}),'page dismissal')
        assert sum(row['type']=='turn/start' for row in support['events'](emulator,sid))==turns
        assert {r['name'] for r in emulator.rpc('pluginManager/listBundles',{})}==before
        flow['restart'](emulator)
        with flow['browser'](emulator) as run:
            selector=card(emulator,run,title,kind)
            flow['wait'](run,f'''(() => {{
              const node=document.querySelector({json.dumps(selector)});
              return node && /已忽略|Dismissed/.test(node.textContent) &&
                ![...node.querySelectorAll('button')].some(el=>/^(创建|Create)$/.test(el.textContent.trim()));
            }})()''','persisted dismissal with no create button')
        evidence['pageRecommendation']={'choice':'page','decision':result,'noBundleInstalledBeforeConfirmation':True}
        print('Verified page location choice, dismissal and reopen without installation',flush=True)


def run(emulator,output,create):
    name='mh-recommend-'+uuid.uuid4().hex[:10]
    folder='alpine/workspace-native/'+name
    path=support['WORKSPACE']+'/'+name
    remote='/data/local/tmp/'+name
    originals, evidence, sessions = {}, {}, []
    workspace=None
    owned_bundles=set()
    try:
        emulator.ready('normal')
        originals={file:agent['read_bytes'](emulator,file) for file in [
            PROFILE+'/package.json',PROFILE+'/pnpm-lock.yaml',PROFILE+'/cordis.patch.yml','mobile-harness-boot.json',
        ]}
        evidence['defaultCatalog']=has_bundle(emulator,NAME,False)
        assert not market['catalog'](emulator,INSPECTOR)['enabled']
        for bundle in [NAME,INSPECTOR]:
            flow['switch'](emulator,bundle,True)
        flow['restart'](emulator)
        has_bundle(emulator,NAME,True)
        rows={row['patchId']:row['fiberPhase'] for row in emulator.rpc('pluginManager/listPlugins',{})
              if row.get('patchId') in ROWS}
        assert rows==dict.fromkeys(ROWS,'active'),rows
        evidence['activeUpstreamRows']=rows
        emulator.app('mkdir '+folder)
        registration=emulator.rpc('workspace/create',{'request':{'path':path}})
        assert registration['created'],registration
        workspace=registration['workspace']['workspaceId']
        with support['model_key'](emulator):
            if not create:
                verify_official(emulator,workspace,name,sessions,evidence)
            verify_page(emulator,workspace,name,sessions,evidence,create)
            flow['switch'](emulator,NAME,False)
            new=session(emulator,workspace,'After disabling '+name,sessions)
            names={row['name'] for row in emulator.rpc('skills/list',{'request':{'sessionId':new}})['skills']}
            assert not names & SKILLS,names & SKILLS
            evidence['skillsRemovedOnDisable']=True
    finally:
        try:
            if originals:
                if create and market['catalog'](emulator,NAME)['enabled']:
                    flow['switch'](emulator,NAME,False)
                for sid in sessions:
                    for event in support['events'](emulator,sid):
                        if event['type']==DECISION and event['data']['action']=='create_personalized_page':
                            bundle=event['data'].get('data',{}).get('bundleName','')
                            if re.fullmatch(r'@dsh-local/view-[a-f0-9-]{36}',bundle):
                                owned_bundles.add(bundle)
                for bundle in sorted(owned_bundles):
                    if market['catalog'](emulator,bundle) is None:
                        continue
                    removed=emulator.rpc('pluginManager/removeBundle',{'name':bundle},timeout=100)
                    assert removed['application'] in ['applied','restart-required'],removed
                for sid in sessions:
                    emulator.rpc('workspace/archiveSession',{'request':{'sessionId':sid}})
                if workspace:
                    assert emulator.rpc('workspace/delete',{'request':{'workspaceId':workspace}})=={'deleted':True}
        finally:
            try:
                if originals:
                    emulator.stop()
                    for bundle in sorted(owned_bundles):
                        emulator.app('rm -rf '+PROFILE+'/created-plugins/'+bundle.removeprefix('@dsh-local/view-'))
                    emulator.app('rm -rf '+folder)
                    for index,(file,body) in enumerate(originals.items()):
                        lsp['restore_bytes'](emulator,file,body,remote+str(index))
                    emulator.start()
                    evidence['restoredReadyMs']=emulator.ready('normal')
                    assert all(agent['read_bytes'](emulator,file)==body for file,body in originals.items())
                    evidence['restoredHashes']={file:hashlib.sha256(body).hexdigest() for file,body in originals.items()}
            finally:
                output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--create',action='store_true',help='Run the real Creator and its installed plugin lifecycle')
    args=parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator=support['Emulator'](args.target,19643)
    forward=('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args.output,args.create)
    finally:
        emulator.hdc('fport','rm',*forward)
