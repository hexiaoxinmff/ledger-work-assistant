"""Read-only pre-delivery scan for version alignment and accidental sensitive artifacts."""
import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS={".git",".github","__pycache__",".pytest_cache"}
TEXT_SUFFIXES={".md",".txt",".py",".json",".yaml",".yml",".toml",".ini",".cfg",".sh",".ps1",".html",".xml",".csv",".tsv"}
SENSITIVE_BINARY_SUFFIXES={".xlsx",".xls",".xlsm",".docx",".doc",".pdf",".png",".jpg",".jpeg",".gif",".bmp",".webp"}
SUSPICIOUS_NAME_PATTERNS=(
    re.compile(r"codex-clipboard",re.I),
    re.compile(r"screenshot|screen[-_ ]?shot",re.I),
    re.compile(r"合同|收款|费用记录|真实台账|内部资料",re.I),
)
SECRET_PATTERNS=(
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"gh"+"p_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-"+"[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)

def files_under(root):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path

def read_text(path):
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError,OSError):
        return ""

def check_versions(root):
    skill=(root/"ledger-organizer/SKILL.md").read_text(encoding="utf-8")
    readme=(root/"README.md").read_text(encoding="utf-8")
    version=(root/"ledger-organizer/tools/fcs-adapted/scripts/version.py").read_text(encoding="utf-8")
    skill_match=re.search(r"助手 (v[0-9]+(?:\.[0-9]+)+)",skill)
    readme_match=re.search(r"当前技能版本：(?P<v>v[0-9]+(?:\.[0-9]+)+)",readme)
    script_match=re.search(r'SKILL_VERSION = "(?P<v>[0-9]+(?:\.[0-9]+)+)"',version)
    values={
        "skill":skill_match.group(1) if skill_match else None,
        "readme":readme_match.group("v") if readme_match else None,
        "version_py":("v"+script_match.group("v")) if script_match else None,
    }
    return values, len(set(v for v in values.values() if v))==1 and all(values.values())

def scan(root):
    findings=[]
    for path in files_under(root):
        relative=path.relative_to(root).as_posix()
        if any(pattern.search(relative) for pattern in SUSPICIOUS_NAME_PATTERNS):
            findings.append({"kind":"suspicious_filename","path":relative})
        if path.suffix.lower() in SENSITIVE_BINARY_SUFFIXES:
            findings.append({"kind":"sensitive_binary_file","path":relative,"suffix":path.suffix.lower()})
        text=read_text(path)
        if text:
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append({"kind":"secret_like_text","path":relative,"pattern":pattern.pattern.replace("\\","")})
                    break
    versions,aligned=check_versions(root)
    return {"root":str(root),"versions":versions,"versions_aligned":aligned,"findings":findings,
            "passed":aligned and not findings,
            "scope":"仅扫描仓库文件名、扩展名、版本文件和可读文本；不打开二进制业务文件，不证明业务内容不存在，也不读取仓库外资料。"}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args(argv)
    try:
        report=scan(args.root.resolve())
    except (OSError,UnicodeError) as exc:
        print(json.dumps({"passed":False,"error":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 2

if __name__=="__main__":
    sys.exit(main())
