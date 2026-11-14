"""Run bundled synthetic regression suites with the selected Python interpreter."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):
        stream.reconfigure(encoding='utf-8',errors='replace')

ROOT=Path(__file__).resolve().parents[1]
CORE=('tools/tests','tools/format-conversion/tests','tools/document-to-excel/tests')
LEDGER=('tools/fcs-adapted/tests',)
OCR=('tools/local-ocr/tests',)
PDF_TEXT=('tools/pdf-text/tests',)
SUITES={'core':CORE,'ledger':LEDGER,'pdf-text':PDF_TEXT,'ocr':OCR,'all':CORE+LEDGER+PDF_TEXT+OCR}

def run_suite(directory,timeout):
    path=ROOT/directory
    if not path.is_dir() or not list(path.glob('test_*.py')):
        return {'suite':directory,'status':'missing_tests'}
    command=[sys.executable,'-m','unittest','discover','-s',str(path),'-v']
    try:
        child_env=os.environ.copy()
        child_env['PYTHONIOENCODING']='utf-8'
        child_env['PYTHONUTF8']='1'
        result=subprocess.run(command,cwd=ROOT,env=child_env,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'suite':directory,'status':'timeout','timeout_seconds':timeout}
    return {'suite':directory,'status':'passed' if result.returncode==0 else 'failed','exit_code':result.returncode,'output':(result.stdout+result.stderr)[-16000:]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=tuple(SUITES),default='core')
    parser.add_argument('--timeout',type=int,default=180,help='每个测试组的超时秒数')
    args=parser.parse_args()
    if not 1<=args.timeout<=600:parser.error('--timeout 必须在 1 至 600 秒之间')
    selected=SUITES[args.suite]
    results=[run_suite(directory,args.timeout) for directory in selected]
    passed=all(result['status']=='passed' for result in results)
    not_run=[] if args.suite=='all' else [directory for name,group in SUITES.items() if name!='all' and name!=args.suite for directory in group]
    print(json.dumps({'executable':sys.executable,'selected':args.suite,'results':results,'selected_suites_passed':passed,'not_run':not_run,'scope':'仅包内虚构脚本回归；不验证真实业务、平台自主调用、界面或 OCR 模型识别精度；不安装依赖'},ensure_ascii=False,indent=2))
    return 0 if passed else 1

if __name__=='__main__':sys.exit(main())
