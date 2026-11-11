# 费用与收款台账整理助手

一个平台中立的试用技能，帮助使用者按平台能力转换常见文档、表格、PDF 和图片格式，并整理费用、收款等表格，保留来源并列出待核实事项。不能代替财务审核，不自动入账、付款、开票或发送。

## 安装和使用

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

包内另提供受限的 CSV/XLSX 本地互转脚本 `ledger-organizer/tools/format-conversion/convert_table.py`，保留可读取的值并进行回读检查；格式及公式等限制见转换说明。其他格式仍依赖当前环境工具。

简单 DOCX 表格转换会生成结构化表、来源明细及含数字原文复核清单；其数字筛选不代表已核对。运行 `python ledger-organizer/tools/check_environment.py` 可只读检查当前 Python 中的模块和工具文件是否可发现。

## 本地图片 OCR 实验

包内提供单张图片识别脚本 `ledger-organizer/tools/local-ocr/recognize_image.py`，使用预先安装的指定 RapidOCR/ONNX Runtime 和通过哈希检查的模型；项目不含模型、不自动安装下载。输出识别文本、位置及待人工复核状态，不自动填账或恢复表格。仅供虚构样例测试，完整限制见 `ledger-organizer/references/local-ocr.md`。

实验功能可对单张简单线框表格图片尝试定位网格并导出复核工作簿；仅限虚构样例，依赖 OCR/OpenCV 和 openpyxl。所有识别内容及空格需对原图人工核对，多页 PDF 和复杂表格暂不保证支持。详见 `ledger-organizer/references/local-ocr.md`。
