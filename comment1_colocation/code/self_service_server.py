"""One loopback reviewer service, with case-specific routes and revision protection."""
import argparse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import unquote,urlsplit
import uuid

from self_service_engine import ROOT,CASES,case_path,load,dump,editor_document,validate_output_root,UserError

LOCK=threading.Lock()


def handler(cases):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(cases),**kwargs)
        def end_headers(self):self.send_header('Cache-Control','no-store');super().end_headers()
        def json_response(self,code,value):
            body=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(code)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def route(self):
            path=unquote(urlsplit(self.path).path);match=re.fullmatch(r'/case/(case_[A-Za-z0-9_]+)(/.*)?',path)
            if not match:raise ValueError('Invalid case address.')
            case=case_path(match[1],cases)
            if not (case/'case.json').exists():raise ValueError('Case not found.')
            return case,match[2] or '/'
        def do_GET(self):
            if urlsplit(self.path).path=='/api/status':return self.json_response(200,dict(service='bse-self-service',cases_root=str(cases)))
            try:case,tail=self.route()
            except (ValueError,UserError) as e:return self.json_response(404,dict(error=str(e)))
            if tail=='/api/reviews':
                with LOCK:value=load(case/'report'/'review_annotations'/'review_annotations.json')
                return self.json_response(200,value)
            if tail in ['/','/review','/review/']:
                document=load(case/'inputs'/'review_dataset.json');document['review_url']=f'http://{self.headers.get("Host")}/case/{case.name}/review/'
                document['review_url']=f'http://{self.headers.get("Host")}/case/{load(case/"case.json")["case_id"]}/review/'
                if document.get('editable_exclusions'):
                    from exclusion_geometry import update_field_context
                    document['fields']['1']=update_field_context(case,document['fields']['1'],load(case/'report'/'review_annotations'/'review_annotations.json'))
                editor_document(case,document);target=case/'report'/'Object_Review.html'
            else:
                target=(case/tail.lstrip('/')).resolve()
                if not target.is_relative_to(case):return self.json_response(403,dict(error='Path is outside the case directory.'))
            if not target.is_file():return self.json_response(404,dict(error='File not found.'))
            self.path='/'+str(target.relative_to(cases)).replace('\\','/');return super().do_GET()
        def do_POST(self):
            try:case,tail=self.route()
            except (ValueError,UserError) as e:return self.json_response(404,dict(error=str(e)))
            if tail not in ['/api/reviews','/api/context-preview']:return self.json_response(404,dict(error='Unknown operation.'))
            origin=self.headers.get('Origin');expected=f'http://{self.headers.get("Host")}'
            if origin and origin!=expected:return self.json_response(403,dict(error='Use the local review page.'))
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=10_000_000:raise ValueError('Invalid review-record size.')
                value=json.loads(self.rfile.read(size));meta=load(case/'case.json')
                if value.get('dataset_id')!=meta['dataset_id'] or value.get('schema_version')!=1:raise ValueError('The review record belongs to another case.')
                if not isinstance(value.get('actions'),list) or not isinstance(value.get('active_ids'),list):raise ValueError('Invalid review-record format.')
                if tail=='/api/context-preview':
                    from exclusion_geometry import update_field_context
                    field=update_field_context(case,load(case/'inputs'/'review_dataset.json')['fields']['1'],value)
                    return self.json_response(200,{k:field[k] for k in ['A_runs','W_runs','window_paths','exclusion_shapes','exclusion_image','size_W_runs','size_window_paths','size_guard_um','distance_guard_um']})
                target=case/'report'/'review_annotations'/'review_annotations.json'
                with LOCK:
                    previous=load(target)
                    if value.get('base_revision',0)!=previous['revision']:
                        backup=case/'report'/'review_annotations'/'conflicts'/('conflict_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:5]+'.json')
                        value.pop('base_revision',None);dump(backup,value)
                        return self.json_response(409,dict(error='Another tab saved a newer revision. Your current state was backed up in the case folder. Use Restore review backup in EOH, then refresh the review page.',backup=str(backup)))
                    value['revision']=previous['revision']+1;value.pop('base_revision',None)
                    shutil.copy2(target,target.with_name('review_annotations.previous.json'));dump(target,value)
                return self.json_response(200,dict(revision=value['revision'],path=str(target)))
            except (ValueError,TypeError,OSError) as e:return self.json_response(400,dict(error=str(e)))
    return Handler


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8766);p.add_argument('--cases-root',type=Path,default=CASES);args=p.parse_args()
    cases=validate_output_root(args.cases_root)
    cases.mkdir(parents=True,exist_ok=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),handler(cases)).serve_forever()


if __name__=='__main__':main()
