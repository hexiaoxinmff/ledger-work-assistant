# 同事交付与验收说明

适用版本：技能 v0.102，适配脚本 0.48

## 一句话发给 Agent

> 请从 https://github.com/hexiaoxinmff/ledger-work-assistant 下载 main 分支，将其中的 ledger-organizer 导入为技能；先报告实际加载的 SKILL.md 版本并阅读 platform-acceptance.md 和 PLATFORM-ACCEPTANCE-REPORT-TEMPLATE.md，只用仓库虚构样例完成完整验收，运行可用的回归测试，生成并回读一份通用 Word 使用教程，输出测试报告和未验证项，未通过前不要处理任何真实业务资料。

如果目标 Agent 不支持直接下载 GitHub，可先在浏览器下载仓库 ZIP，再把其中的 ledger-organizer 文件夹导入；导入后必须新建会话，不要只让 Agent 阅读 README 就判定技能已加载。

## 交付内容

只需要交付以下内容：

- GitHub 仓库：https://github.com/hexiaoxinmff/ledger-work-assistant
- 导入目录：ledger-organizer/
- 平台验收说明：ledger-organizer/references/platform-acceptance.md
- 验收记录模板：PLATFORM-ACCEPTANCE-REPORT-TEMPLATE.md
- 本说明：COLLEAGUE-HANDOFF.md

不要把仓库里的虚构结果、运行清单或本机路径当作同事的实际验收结果。

## 第一步：确认已加载

在新会话中发送：

> 请不要处理业务文件。先实际读取当前已加载的 ledger-organizer/SKILL.md，报告标题版本、读取到的参考文件，并说明当前会话是否能调用包内脚本；如果只能阅读文字，明确说明不能把代码存在当作已执行。

合格标准：

- 报告版本为 v0.102；
- 能区分“平台已加载”与“手动读取文件”；
- 不虚构脚本执行、文件生成或依赖可用。

## 第二步：运行包内回归

在 Agent 允许执行本地脚本时，使用与环境检查相同的 Python 解释器：

1. 环境检查（不安装依赖）：

   python ledger-organizer/tools/check_environment.py --task table_conversion

2. 核心回归：

   python ledger-organizer/tools/run_checks.py --suite core

3. 依赖齐全时再运行全部回归：

   python ledger-organizer/tools/run_checks.py --suite all

若某组依赖缺失，必须记录实际解释器、缺少模块、停止位置和未运行组；不能把“部分通过”写成“全部通过”，也不要自动安装依赖。

## 第三步：虚构样例验收

至少覆盖以下内容：

- ledger-organizer/tools/tests/fixtures/acceptance.csv
- ledger-organizer/tools/tests/fixtures/acceptance.tsv
- ledger-organizer/tools/tests/fixtures/acceptance_semicolon.csv
- 一份只含简单表格的虚构 DOCX
- 一份带文字层的虚构 PDF

数字与字段必须检查：

- 前导零编号；
- 长编号；
- 12.30 等尾零；
- -0.00；
- 空金额；
- 科学计数法；
- 中文数字金额候选；
- 日期、百分比和备注换行；
- 重复编号、多候选和单边记录。

每次转换或整理都要确认：

- 原始文件未被修改；
- 输出是新文件，不覆盖已有结果；
- 结果可重新读取；
- 来源文件、工作表/页码、起始行等定位存在；
- .manifest.json（若生成）与结果文件对应，但不公开转发；
- 不能自动把数字候选、OCR 结果、空值/零值或金额合计写成业务已确认。

## 第四步：Word 教程验收

让 Agent 发送：

> 请根据当前技能的通用能力，生成一份不包含任何真实业务资料的 Word 使用教程，至少包含：能做什么、需要提供什么、最短使用步骤、结果如何核对、数字/OCR 人工复核、隐私保护、常见失败和脱敏反馈格式；生成后重新读取或解析 Word，报告标题和关键章节是否存在。

合格标准：

- 实际生成 .docx，或如平台不支持则明确说明并交付 Markdown；
- 生成后有回读/解析证据；
- 教程没有真实业务数据、本机绝对路径、密钥、截图或运行清单；
- 教程说明本技能不代替财务审核、入账、付款、开票或发送。

## 通过 / 不通过

只有同时满足以下条件，才可进入脱敏真实资料试用：

- 实际加载版本正确；
- 所有选择运行的回归组通过，未运行组已明确列出；
- 虚构样例转换、数字核验、来源追溯和已有结果保护通过；
- Word 教程生成并回读通过；
- 数据保护检查通过；
- 未验证项和人工复核项已列出。

出现以下任一情况即暂停：

- Agent 无法报告实际加载版本；
- 把脚本存在或 CI 通过说成已经实际调用；
- 真实业务资料被上传到额外服务；
- 输入文件被覆盖；
- 长编号、空值、零值或 OCR 候选被未经核对地确认；
- 结果无法回读或来源无法定位。

## 脱敏反馈格式

只提交以下通用信息，不附真实文件：

- 使用平台和客户端：
- 实际加载版本：
- 实际运行的回归组及退出状态：
- 使用的虚构样例类型：
- 期望行为：
- 实际行为：
- 影响功能：
- 未验证或缺少依赖：
- 是否允许加入虚构回归：
