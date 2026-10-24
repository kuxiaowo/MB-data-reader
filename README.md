# MB-data-reader

轻量独立的只读学习数据提取器：**Python 3.10+，运行时零第三方依赖**，无网站、数据库、服务器、提醒或后台任务。**解析器/传输层尚未完成真实会话端到端验证。** 已参考当前页面的脱敏 DOM 结构观察；公开文件不包含真实学生记录。

## 已实现

- ManageBac upcoming / past / overdue 任务；分页、任务 ID 去重；班级与官方总评/assessment categories。
- 只接受调用方已认证的内存 CookieJar；没有账号密码登录或凭据持久化，没有提交/修改学校数据的功能。
- 独立 `TimetableProvider` 接口及只读 `OfflineTimetableProvider`：解析用户在授权会话中取得的已渲染课表 HTML，不读取/导出认证信息，不调用私有 API。入口 <https://student.hyqzedu.com/app-base-info/app/home>。自动认证/实时抓取尚未安装，`timetable-status` 仍显式返回 `provider_not_configured`；离线解析不等于自动登录已接通。
- 不估算成绩、不造分数线。`grade_boundaries` / `estimated_grade` 为 null，未知权重也不是 0。

## 运行（无需安装）

在本目录执行：

```sh
python -m unittest discover -s tests -v
python -m study_reader tasks tests/fixtures/tasks.html --view upcoming --timezone Asia/Shanghai
python -m study_reader grades tests/fixtures/grades.html --class-id 12 --class-name 'Test Maths'
python -m study_reader timetable tests/fixtures/timetable.html --week-start 2026-12-28 --week-end 2027-01-03
python -m study_reader timetable-status
```

Fixtures 与 `examples/` 中 JSON 完全虚构。CLI 只读本地 HTML 并将 JSON 输出 stdout，不联网、不自动保存。可选 `python -m pip install .` 后使用 `study-reader`；构建需 setuptools，运行无需依赖。

## 安全接入已有会话

由可信且已获授权的登录模块传入 `http.cookiejar.CookieJar`。本项目不负责登录，不要求把密码/Cookie/token 发到聊天，也不应写进代码、命令行或 Git。

```python
from study_reader.managebac import ManageBacReader
from study_reader.transport import ReadOnlyTransport

# authenticated_cookie_jar 由已有安全登录流程提供；不是字符串或文件路径。
transport = ReadOnlyTransport(authenticated_cookie_jar)
result = ManageBacReader(transport, max_pages=30, timezone_name='Asia/Shanghai').read()
# timezone_name 必须来自已验证的账户设置；不传则不假设任何时区。
# 先检查 result['complete'] 与 result['errors']，再决定如何私密保存。
```

传输层只允许 HTTPS `sdgj.managebac.cn:443` 下明确的读取路径/view/page 参数，只发 GET；所有重定向均拒绝，包括同站登录跳转。不会把 Cookie 跟随重定向发到第三方。默认 20 秒超时、5 MiB 响应上限、验证状态码/content-type/编码。失败明确报告，不自动重试，不使用旧缓存掩盖失败。不会打印远程响应、Cookie 或认证信息。

真实 HTML/成绩包含隐私，建议放已忽略的 `private/`，不要提交。`.gitignore` 不是防泄漏保证。不要分享浏览器完整 HAR/凭据；需要接口样本时只提供脱敏单请求，删除 token、Cookie、Authorization、姓名/学号等。

## 数据语义与限制

- schema_version=1。`complete` 仅代表本次范围的读取完整性，不是全学期数据保证。
- provenance 的 source/source_url/fetched_at/parsed_at/freshness 区分来源与时间；读取时间不是校方更新时间，也不保证校方页面绝对最新。
- 离线输出 `offline_unknown`，fetched_at=null；只有解析时间，单页始终 complete=false。
- 没日期的任务保留；缺年份/时间不猜默认值，原文保留、value=null。完整英文日期也需调用方显式提供已验证的 IANA 时区（`timezone_name` / CLI `--timezone`）；无时区仅保留 `local_value`，`value=null`、`resolution=timezone_required`。已提供时区记录 `timezone_source=caller_supplied`；缺年份仍不猜测。DST 重复/不存在的本地时间保持未解析。其它格式未支持时保留原文。时区数据库由系统提供；不可用时明确报配置错误，不自动退回上海时区。
- 重复 ID 最后观察覆盖（含 null 清空），views 合并。冲突列出 conflicting_observations 并 complete=false；读取顺序不等于校方更新时间，需审阅/重读。
- 页数限制、循环、危险/缺 view 分页链接、部分失败都明确报错。失败不丢其它成功数据。pagination complete 仅代表链接遍历；畸形记录另见顶层 errors。
- 任务 `assessment_status` 与 `submission_status` 分离：仅已观察的明确评定 CSS 类识别 Assessed / Not Assessed。Pending 徽标只保留在 `badge_labels_raw`，不推断为已提交或未提交；`--due` 也不是提交状态。当前任务列表提交状态仍为 null，班级表的独立 Not Submitted 尚未接入；评分与 Pending 可以同时存在。旧 `status` 仅保留评分区文本兼容，不要把它当提交状态；新调用方应使用分离字段。
- 成绩 evidence=official_page 是“页面直读而非计算”，不是独立真实性认证。分数字符串保留原文；不把任务分数当课程总评。
- 解析 selector 来源于旧代码；标准库 HTML 树不是完整浏览器 DOM，学校改版可能需更新。未知页面报错，不无声当空列表。

## 离线课表（不接私有 API）

```python
from study_reader.timetable import parse_timetable, OfflineTimetableProvider
result = parse_timetable(rendered_html, week_start='2026-12-28', week_end='2027-01-03')
# 或 OfflineTimetableProvider(rendered_html, week_start='2026-12-28').read()
```

- 输入是**已经渲染**的 `.schedule-card` DOM；普通 SPA 首页源码可能没有课表，届时明确报结构错误。只在本地处理，不抓浏览器 Cookie/token，不自动登录，不发送任何 HTTP。
- 首列日期必须来自你核实的当前页面周范围（ISO `YYYY-MM-DD`），按七列顺序加天数，支持跨月/跨年。`今` 与数字日期标签只保留原文，不用来猜日期；若页面明确打印完整 ISO 起止范围，可省略参数。实际页面类似 `03月02日 - 03月08日` 的范围需要显式 `week_start`，并校验月/日范围与输入一致；页头年份以 `displayed_year_raw` 保留，不盲目将它作为跨年首日年份，也不以系统当前年份补全；可识别数字年份必须属于首/末日期年份之一。数字日标签只用于矛盾校验：必须等于已映射日期的日，不用于推断日期，`今` 不作数字校验。`week_end` 可选，但提供时必须恰好是首日+6天；可解析 DOM 范围与参数矛盾则拒绝映射。
- 保留本地起止时间、课程/班级/地点/老师、日期级异常；未提供时区，因此不生成带时区的时间戳。可见上午/下午标签可能有误，解析以数字24小时制时间为准，不将 `上午 14:00` 改成其它时刻。缺失/非法时间保留课程并报告错误；不推测默认时长，不跨夜猜测。
- 每条课程/异常 `recurring=false`，只描述该日期，不推广成每周模板。没有可靠来源 ID 时为 null，列表位置不是稳定 ID。
- **空白周/空白日不是空闲证明**：整周无课程为 `data_unavailable`，空白日为 `unknown`；可能是未发布、加载失败或确实无课，不能据此自动安排会议。页面异常文字保留，不能定位到一天的异常标记 `date=null` 并报错。
- 离线结果始终 `complete=false`、`freshness=offline_unknown`、`fetched_at=null`；`observed_lessons` 只说明 DOM 中看到了课程，不保证整周完整或最新。真实 HTML 和输出均可能含学生隐私，请只保存在本地 `private/`，勿提交。

## 验证

离线测试覆盖日期/年份缺失、多行 HTML/实体、时区、官方成绩/缺权重、分数更新清空、同名班级、host allowlist、拒绝重定向、分页上限/循环/失败、登录页、未知布局。网络使用 fake/mock，测试不访问学校。另有编译检查、CLI JSON 冒烟检查。

**尚未端到端验证：传输层真实会话认证、完整线上 HTML 解析、真实任务分页/成绩准确率、课表版本/参数/响应/认证。** 当前仅将脱敏实时结构观察转化为虚构回归测试，不代表已抓取全量数据。 需要后续授权会话或脱敏样本。

## 来源、许可与发布

读取结构/selector 参考用户已有代码并隔离为新只读模块：

- [To-do-list/managebac_backend.py](https://github.com/kuxiaowo/To-do-list/blob/main/managebac_backend.py)，blob SHA `8ea8f88c148ca4943c17f72be21dd5b81f74a883`
- [MangeBac-Dashboard/scraper.py](https://github.com/kuxiaowo/MangeBac-Dashboard/blob/main/scraper.py)，blob SHA `9d9a0fb9d87be65edbfcedaa85b14e4e92f3437a`

未搬入数据库、UI、登录提交、AppleScript、硬编码年份或默认分数线。**上游许可/再分发条件尚未确认，不擅自添加开源许可证。** 项目名称为 MB-data-reader；公开发布前应确认许可、学校规则，并检查凭据和学生数据。发布包仅包含代码、文档、测试与虚构示例，不包含真实账号、会话或学习数据。
