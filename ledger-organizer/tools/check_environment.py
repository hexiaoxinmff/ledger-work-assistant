"""Read-only check of the current Python runtime and optional dependencies."""
import importlib.util, json, platform, sys
from pathlib import Path
root=Path(__file__).resolve().parent
modules={name:importlib.util.find_spec(name) is not None for name in ("openpyxl","pandas","yaml")}
tools={"docx_tables":(root/"document-to-excel/docx_tables.py").is_file(),"table_conversion":(root/"format-conversion/convert_table.py").is_file(),"ledger_reconcile":(root/"fcs-adapted/scripts/reconcile.py").is_file()}
print(json.dumps({"python":platform.python_version(),"executable":sys.executable,"modules":modules,"tools":tools,"note":"只检查模块可发现和文件存在；未验证导入、转换器、OCR、联网或业务可用性，不安装依赖"},ensure_ascii=False))
