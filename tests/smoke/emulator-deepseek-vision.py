"""Send owned PNG samples through the real DeepSeek Flash image path on Phone."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import random
import re
import runpy
import struct
import time
from urllib.parse import urlencode
from urllib.request import Request
import uuid
import zlib

flow = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = flow['support']
WIDTH, HEIGHT = 512, 256
COLORS = {
    'red': bytes((230, 30, 38)), 'green': bytes((30, 172, 56)),
    'blue': bytes((28, 79, 230)), 'yellow': bytes((255, 220, 26)),
}
UPLOAD = '/api/session/uploadFileBinary'


def chunk(kind, data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))


def sample(left, right):
    header=struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,2,0,0,0)
    pixels=(b'\0'+COLORS[left]*(WIDTH//2)+COLORS[right]*(WIDTH//2))*HEIGHT
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')


def upload(device, sid, filename, data):
    query=urlencode({'sessionId':sid,'mediaType':'image/png','name':filename})
    result=device.opener.open(Request(device.url+UPLOAD+'?'+query,data=data,headers={
        'Host':'127.0.0.1:19592','Content-Type':'application/octet-stream','Cookie':device.cookie(),
    }),timeout=30)
    with result:
        response=json.load(result)
    assert response['ok'], response
    value=response['value']
    size=(value['image']['width'],value['image']['height'])
    assert size==(WIDTH,HEIGHT), size
    return value


def execute(device,sid,receipts):
    before=support['events'](device,sid)
    cursor=max((row['seq'] for row in before),default=0)
    prompt='Read the two images in the order attached. Each image has two solid vertical halves. '
    prompt+='Return only the four English color names, separated by spaces, left then right for each image. Do not use tools.'
    content=[{'type':'file','receiptId':receipt['receiptId']} for receipt in receipts]
    content.append({'type':'text','text':prompt})
    request_id=str(uuid.uuid4())
    device.rpc('session/prompt',{'request':{'sessionId':sid,'requestId':request_id,'mode':'queue','content':content}})
    until=time.monotonic()+80
    while time.monotonic()<until:
        new=[row for row in support['events'](device,sid) if row['seq']>cursor]
        end=next((row for row in new if row['type']=='turn/end'),None)
        if end:
            assert end['data']['reason']['kind']=='completed', end
            assert not any(row['type']=='tool/call' for row in new),new
            attached=[block['attachment']['attachmentId'] for row in new if row['type']=='user/message'
                      for block in row['data']['content'] if block['type']=='image']
            assert attached==[receipt['image']['attachmentId'] for receipt in receipts],attached
            result=flow['assistant_texts'](new).strip()
            return result,end['data']['reason'], attached
        time.sleep(.25)
    raise AssertionError('Image prompt did not finish')


def run(device,output):
    marker='mh-vision-'+uuid.uuid4().hex[:10]
    app='alpine/workspace-native/'+marker
    bridge=('tcp:19643','tcp:19592')
    evidence, workspace, sid = {},None,None
    unfinished=False
    assert 'Forwardport result:OK' in device.hdc('fport',*bridge)
    try:
        device.ready('normal')
        device.app('mkdir '+app)
        registered=device.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+marker}})
        assert registered['created']
        workspace=registered['workspace']['workspaceId']
        with support['model_key'](device):
            try:
                sid=device.rpc('session/create',{'request':{'workspaceId':workspace}})['sessionId']
                model={'provider':'deepseek-official','model':'deepseek-flash','reasoningEffort':'off'}
                device.rpc('session/selectModel',{'request':{'sessionId':sid,**model}})
                order=random.SystemRandom().sample(list(COLORS),len(COLORS))
                blobs=[sample(*order[:2]), sample(*order[2:])]
                receipts=[upload(device,sid,f'fixture-{index}.png',data) for index,data in enumerate(blobs)]
                evidence['requestedModel']=model
                evidence['expectedImageOrder']=order
                evidence['sourcePNGHashes']=[hashlib.sha256(data).hexdigest() for data in blobs]
                unfinished=True
                reply, reason, _=execute(device,sid,receipts)
                unfinished=False
                evidence['reply']=reply
                evidence['turnEndReason']=reason
                assert re.findall(r'[a-z]+',reply.lower())==order, (order,reply)
                def retrieve(receipt):
                    result=device.rpc('session/attachment',{'request':{'sessionId':sid,'attachment':receipt['image']}})
                    return base64.b64decode(result['data'],validate=True)
                normalized=[retrieve(receipt) for receipt in receipts]
                assert all(bytes(result) for result in normalized)
                device.stop()
                device.start()
                evidence['restartReadyMs']=device.ready('normal')
                assert [retrieve(receipt) for receipt in receipts]==normalized
                evidence['attachmentBytesRestored']=True
            finally:
                if unfinished:
                    device.rpc('session/cancel',{'request':{'sessionId':sid}})
                if sid:
                    device.rpc('workspace/archiveSession',{'request':{'sessionId':sid}})
        evidence['testKeyRemoved']=True
    finally:
        try:
            if workspace:
                assert device.rpc('workspace/delete',{'request':{'workspaceId':workspace}})=={'deleted':True}
            device.app('rm -rf '+app)
        finally:
            device.hdc('fport','rm',*bridge)
            output.write_text(json.dumps(evidence,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target,19643),args.output)
