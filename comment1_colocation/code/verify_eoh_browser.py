"""Exercise English review actions in an isolated headless Edge profile."""
import base64
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen
import websocket
from self_service_engine import ROOT,load,dump,configure_temp
from verify_batch_summary import stage_case


def main():
    work=Path(load(ROOT/'logs/upgrade_release_work.json')['work']);folder=work/('browser_check_'+uuid.uuid4().hex[:6]);configure_temp(folder/'runtime')
    case=folder/'cases/qa';stage_case(ROOT.parent/'分析结果/3',case);meta=load(case/'case.json');meta['name']='EOH QA';dump(case/'case.json',meta)
    def port():
        with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
    service,debug=port(),port();base=f'http://127.0.0.1:{service}/case/{meta["case_id"]}'
    env=dict(os.environ,TEMP=str(folder/'runtime'),TMP=str(folder/'runtime'),TMPDIR=str(folder/'runtime'),PYTHONDONTWRITEBYTECODE='1')
    handles=[];processes=[];ws=None;checks={}
    def launch(args):
        stream=(folder/'browser.log').open('ab');handles.append(stream)
        p=subprocess.Popen(args,env=env,cwd=folder,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=stream,stderr=stream);processes.append(p);return p
    try:
        launch([sys.executable,'-B',str(ROOT/'code/self_service_server.py'),'--port',str(service),'--cases-root',str(case.parent)])
        for attempt in range(100):
            try:
                with urlopen(base+'/api/reviews',timeout=1) as r:initial=json.load(r)
                break
            except Exception:time.sleep(.15)
        else:raise RuntimeError('Review server unavailable')
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=launch([str(edge),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--disable-breakpad','--disable-crash-reporter',
                        '--user-data-dir='+str(folder/'profile'),'--disk-cache-dir='+str(folder/'cache'),'--crash-dumps-dir='+str(folder/'crashes'),
                        '--remote-debugging-port='+str(debug),'--remote-allow-origins=http://localhost:'+str(debug),'--window-size=1500,1100',base+'/review/'])
        for attempt in range(100):
            try:
                with urlopen(f'http://127.0.0.1:{debug}/json/list',timeout=1) as r:targets=json.load(r)
                target=next(t for t in targets if t['type']=='page' and base in t['url']);break
            except Exception:time.sleep(.15)
        else:raise RuntimeError('Headless Edge unavailable')
        ws=websocket.create_connection(target['webSocketDebuggerUrl'],origin=f'http://localhost:{debug}',timeout=15);sequence=0
        def cdp(method,params=None):
            nonlocal sequence
            sequence+=1;seq=sequence;ws.send(json.dumps(dict(id=seq,method=method,params=params or {})))
            while True:
                response=json.loads(ws.recv())
                if response.get('id')==seq:
                    if 'error' in response:raise RuntimeError(response['error'])
                    return response.get('result',{})
        def evaluate(expression):
            result=cdp('Runtime.evaluate',dict(expression=expression,awaitPromise=True,returnByValue=True))
            if result.get('exceptionDetails'):raise RuntimeError(result['exceptionDetails'])
            return result.get('result',{}).get('value')
        for attempt in range(100):
            if evaluate("typeof ready!=='undefined'&&ready&&!!document.getElementById('hole-point')"):break
            time.sleep(.15)
        else:raise RuntimeError(evaluate("document.body.innerText"))
        text=evaluate('document.body.innerText');assert not re.search('[\u3400-\u9fff]',text),text
        assert evaluate("document.title.startsWith('EOH')&&$('save').textContent==='Save all changes'")
        checks['actual_review_page_controls_and_status_english']=True
        result=evaluate("(async()=>{$('kind').value='candidate_bright_particle';begin('add');ui.draft=[[500,300],[505,300],[505,305],[500,305]];finish();let id=ui.selected;await saveAll();await serial;return {id,revision:state.revision,status:$('save-state').textContent};})()")
        assert result['revision']>initial['revision'] and result['status'].startswith('Saved to project folder'),result
        record=load(case/'report/review_annotations/review_annotations.json');assert any(a['object_id']==result['id'] and a['operation']=='add_outline' for a in record['actions'])
        checks['english_add_outline_and_save_persist_native_record']=True
        evaluate("$('width').value='full';draw();$('overlay').scrollIntoView({block:'center'});$('hole-point').click()")
        xy=evaluate("(()=>{let b=$('overlay').getBoundingClientRect(),v=viewport();return {x:b.left+(300.5-v.x)*v.zoom*b.width/700,y:b.top+(300.5-v.y)*v.zoom*b.height/480};})()")
        cdp('Input.dispatchMouseEvent',dict(type='mousePressed',button='left',clickCount=1,**xy));cdp('Input.dispatchMouseEvent',dict(type='mouseReleased',button='left',clickCount=1,**xy))
        result=evaluate("(async()=>{await saveAll();await serial;return {shapes:FIELDS[currentField()].exclusion_shapes,status:$('save-state').textContent};})()")
        assert any(s['kind']=='point' and s['radius_um']==1 for s in result['shapes']),result
        checks['english_hole_buffer_preview_and_save_work']=True
        assert not re.search('[\u3400-\u9fff]',evaluate('document.body.innerText'))
        metrics=cdp('Page.getLayoutMetrics')['cssContentSize'];metrics['scale']=1
        screenshot=cdp('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=metrics))
        (ROOT/'logs/eoh_review_english.png').write_bytes(base64.b64decode(screenshot['data']))
        try:cdp('Browser.close')
        except Exception:pass
        try:browser.wait(timeout=10)
        except subprocess.TimeoutExpired:pass
        dump(ROOT/'logs/eoh_browser_validation.json',dict(status='passed',checks=checks))
        print(checks,flush=True)
    finally:
        if ws:ws.close()
        for p in reversed(processes):
            if p.poll() is None:p.terminate();p.wait(timeout=10)
        for handle in handles:handle.close()


if __name__=='__main__':main()
