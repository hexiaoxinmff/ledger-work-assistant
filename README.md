# 费用与收款台账整理助手

一个平台中立的试用技能，帮助使用者按平台能力转换常见文档、表格、PDF 和图片格式，并整理费用、收款等表格，保留来源并列出待核实事项。不能代替财务审核，不自动入账、付款、开票或发送。

## 安装和使用

当前技能版本：v0.37。先在新会话确认实际加载的 `SKILL.md` 版本；直接阅读本地文件与平台自动加载是不同状态。通用虚构试用需求和核对标准见 [平台验收](ledger-organizer/references/platform-acceptance.md)，三份样例随包位于 `ledger-organizer/tools/tests/fixtures/`。

本机虚构回归入口：`python ledger-organizer/tools/run_checks.py`。默认执行基础环境/样例/转换/Word 提取测试；对账业务规则测试用 `--suite ledger`（需预装 pandas、openpyxl、PyYAML），PDF 文字层转表测试用 `--suite pdf-text`（需预装 pypdfium2、openpyxl），OCR 相关测试用 `--suite ocr`，全部用 `--suite all`。各组依赖须事先满足，报告保留失败、超时和未运行项目，不能将部分通过当成全功能通过。这些测试不包含真实账目、平台自主调用、界面或 OCR 准确率验收。

在仓库根目录运行以下命令检查本次要用的解释器，不自动安装依赖：

```text
python ledger-organizer/tools/check_environment.py --task table_conversion
```

报告包含实际解释器与工具入口。后续命令中的 `python` 应使用同一个解释器；检查失败须如实记录，不能当成转换已通过。其他任务可用 `--help` 查看；OCR 还需指定版本、模型和实际识别验证。

使用纯虚构、明确三列的包内样例试转，结果路径必须尚不存在：

```text
python ledger-organizer/tools/format-conversion/convert_table.py ledger-organizer/tools/tests/fixtures/acceptance.csv acceptance-result.xlsx --expected-columns 3
```

这是转换命令示例，不会安装技能或证明平台已自动调用。转换后仍应重新读取结果并逐项核对。首次试用先完成样例验收，再评估本人任务所需规则和未覆盖限制。

下载本仓库后，将 `ledger-organizer` 文件夹按所用 Agent 平台的技能安装方式导入，或让支持读取文件的 Agent 阅读 `ledger-organizer/SKILL.md`。具体目录、自动加载、联网和文件访问能力因平台而异，需在目标环境测试。可先用虚构样例提供两张表、确认字段和规则，再要求保留来源、生成复核清单。

技能内含有限测试的 Python 对账适配副本；运行需要 Python、pandas、openpyxl、PyYAML，实际依赖和平台权限须另行检查。其结果可选表格或附加结果项柱状图；结果项数量不等于交易笔数。脚本当前仅用虚构数据测试，不用于真实账目。

## 按需发现其他技能

当前任务缺少能力时，优先使用平台已有技能；必要时可用通用关键词进行只读搜索，评估候选后按平台权限与用户授权使用。搜索关键词会发送给外部服务，不应包含个人或业务数据。详情见 `ledger-organizer/references/skill-discovery.md`。

## 第三方来源

`ledger-organizer/vendor/` 附带第三方技能原文、许可及四个项目的源码文本节选，出处和限制见 `ledger-organizer/references/github-adapter.md`。第三方源码没有因封装而自动安装、运行或完成安全审查。

## 文档转 Excel

简单 DOCX 文本表格可使用 `ledger-organizer/tools/document-to-excel/docx_tables.py`，输出按表、行、列定位的单元格明细，数字原文以文本保存并回读校验；该工具不含 OCR，不处理扫描件、PDF、文档正文、合并表格和图片。其他形式依赖平台实际可用的文档或识别工具。所有结果必须结合原件复核；目前只用虚构数据测试。

## 常见文件格式转换

技能根据任务和当前平台能力选择文档、PDF、表格及图片转换工具；不同平台的支持情况需实测。格式转换后的数字、文件结构与页面呈现需要按任务核验，详见 `ledger-organizer/references/format-conversion.md`。本技能不自带所有格式的转换器或 OCR。

包内提供受限的 CSV/TSV 与 XLSX 本地互转脚本 `ledger-organizer/tools/format-conversion/convert_table.py`。TSV 固定制表符，CSV 默认逗号，可明确指定 `--delimiter semicolon` 或 `--delimiter tab`；已确认列数时使用 `--expected-columns`。显示格式可能影响数字含义时默认停止，只有明确接受底层值导出后才使用 `--allow-display-loss`。源内容按文本保存及回读核验，文本导出不保留类型，直接在表格软件打开仍可能改变长编号。更多限制见转换说明。

简单 DOCX 表格转换生成结构化表、来源明细及含数字原文复核清单，筛选不代表已核对。特殊符号、域标记、脚注/尾注引用、内容控件等不支持结构会停止，需另选方式并人工确认；该检查不能穷尽所有 Word 结构。环境自检不带参数时仅检查模块和文件能否发现，带 `--task` 才实际探测相应依赖导入。

可搜索 PDF 的文字层可用 `ledger-organizer/tools/document-to-excel/pdf_text_to_excel.py` 导出逐页原文、页码状态和数字候选复核工作簿；不做 OCR，也不猜表格列。图片文字、矢量转曲文字和批注可能未提取；扫描页逐页标明，整份没有文字层则停止。使用前运行 `python ledger-organizer/tools/check_environment.py --task pdf_text`；提取的每个数字仍须对照 PDF 原页核对。

## 本地图片 OCR 实验

包内提供单张图片识别脚本 `ledger-organizer/tools/local-ocr/recognize_image.py`，使用预先安装的指定 RapidOCR/ONNX Runtime 和通过哈希检查的模型；项目不含模型、不自动安装下载。输出识别文本、位置及待人工复核状态，不自动填账或恢复表格。仅供虚构样例测试，完整限制见 `ledger-organizer/references/local-ocr.md`。

实验功能可对单张简单线框表格图片尝试定位网格并导出复核工作簿；仅限虚构样例，依赖 OCR/OpenCV 和 openpyxl。所有识别内容及空格需对原图人工核对，多页 PDF 和复杂表格暂不保证支持。详见 `ledger-organizer/references/local-ocr.md`。

实验功能还可尝试 1–20 页、每页一个简单线框表的虚构 PDF，输出带页码的复核工作簿和中间页面文件；任何页面失败会停止，所有格子必须人工核对。依赖、隐私和适用范围见 `ledger-organizer/references/local-ocr.md`。

PDF 一键流程在渲染前自动检查 OCR 版本和模型哈希；也可单独运行 `python ledger-organizer/tools/local-ocr/recognize_image.py --check-runtime`，此检查无需图片，不运行识别，不证明引擎初始化或准确率。依赖不随仓库下载，代码存在也不等于 OCR 环境已准备。

CSV/TSV 转换、PDF 复核表及复核汇总采用临时文件校验后不覆盖发布，目标目录需要硬链接支持。强制中断可能遗留含原文的临时文件，按资料授权处理；其他输出工具不自动具有相同保护。

多页 PDF 复核默认不嵌入原页；如用户明确需要，可选择嵌入原页缩略图辅助定位。缩略图包含完整页面，可能包含表格以外的内容，分享前需按资料授权处理；数字仍以原 PDF 原尺寸人工复核。

PDF 虚构样例复核表提供逐格人工选择和文本修正；可选工具汇总复核记录并检查来源和未完成项。工具记录使用者声明，不能证明人工实际核看原件或财务结果正确。
