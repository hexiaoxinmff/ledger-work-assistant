"""Read-only check of the current Python runtime and optional dependencies."""
import argparse, importlib.util, json, platform, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent
modules={name:importlib.util.find_spec(name) is not None for name in ("openpyxl","pandas","yaml","rapidocr","onnxruntime","cv2","numpy","pypdfium2")}
tools={"docx_tables":(root/"document-to-excel/docx_tables.py").is_file(),"table_conversion":(root/"format-conversion/convert_table.py").is_file(),"ledger_reconcile":(root/"fcs-adapted/scripts/reconcile.py").is_file(),"local_ocr":(root/"local-ocr/recognize_image.py").is_file(),"table_grid":(root/"local-ocr/table_grid.py").is_file(),"export_review":(root/"local-ocr/export_review.py").is_file(),"pdf_pipeline":(root/"local-ocr/pipeline_pdf.py").is_file(),"collect_review":(root/"local-ocr/collect_review.py").is_file()}
requirements={
 "table_conversion":("openpyxl",), "docx_tables":("openpyxl",),
 "ledger_reconcile":("openpyxl","pandas","yaml"),
 "local_ocr":("rapidocr","onnxruntime","cv2","numpy"),
 "pdf_pipeline":("rapidocr","onnxruntime","cv2","numpy","pypdfium2","openpyxl","PIL"),
 "collect_review":("openpyxl",),
}

def probe(module,timeout=15):
    code="import importlib,json,sys; imported=importlib.import_module(sys.argv[1]); print(json.dumps({'version':str(getattr(imported,'__version__','unknown')),'location':str(getattr(imported,'__file__','unknown'))}))"
    try:
        result=subprocess.run([sys.executable,'-c',code,module],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status":"timeout"}
    if result.returncode:
        return {"status":"import_failed","exit_code":result.returncode,"error":result.stderr[-1500:]}
    try:
        details=json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError):
        return {"status":"invalid_probe_output"}
    return {"status":"imported",**details}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=sorted(requirements))
    args=parser.parse_args()
    report={"python":platform.python_version(),"executable":sys.executable,"modules":modules,"tools":tools,"note":"默认仅检查模块可发现和文件存在；指定任务才在独立子进程验证导入，不安装依赖。导入可能执行依赖初始化；不会运行转换或读取业务文件，不能证明模型、业务或平台隔离可用。"}
    exit_code=0
    if args.task:
        imports={module:probe(module) for module in requirements[args.task]}
        report.update(task=args.task,imports=imports,entrypoint=str(root/paths[args.task]))
        report['dependency_check_passed']=tools[args.task] and all(item['status']=='imported' for item in imports.values())
        exit_code=0 if report['dependency_check_passed'] else 2
    print(json.dumps(report,ensure_ascii=False))
    return exit_code

paths={"table_conversion":"format-conversion/convert_table.py","docx_tables":"document-to-excel/docx_tables.py","ledger_reconcile":"fcs-adapted/scripts/reconcile.py","local_ocr":"local-ocr/recognize_image.py","pdf_pipeline":"local-ocr/pipeline_pdf.py","collect_review":"local-ocr/collect_review.py"}

if __name__=='__main__':sys.exit(main())
