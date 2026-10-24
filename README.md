# MB-data-reader

轻量独立的只读学习数据提取器：**Python 3.10+，运行时零第三方依赖**，无网站、数据库、服务器、提醒或后台任务。**未使用真实账号，未完成学校线上数据验证。**

## 已实现

- ManageBac upcoming / past / overdue 任务；分页、任务 ID 去重；班级与官方总评/assessment categories。
- 只接受调用方已认证的内存 CookieJar；没有账号密码登录或凭据持久化，没有提交/修改学校数据的功能。
- 独立 `TimetableProvider` 接口，当前显式 `provider_not_configured`，不是“空课表”。入口 <https://student.hyqzedu.com/app-base-info/app/home>。公开脚本确认 POST 读取路径模板 `/api/${getApiVersion()}/courses-schedule/students/my.schedule.list`，base 为 `https://api.hyqzedu.com/student-web-gateway-api/`；版本、参数、响应和认证仍未知，因此未猜测实现。公开首页在云浏览器显示 token 失效 401；需要后续脱敏样本或用户导出。此 POST 读取路径尚未接入，也未被本工具调用。
- 不估算成绩、不造分数线。`grade_boundaries` / `estimated_grade` 为 null，未知权重也不是 0。

## 运行（无需安装）

在本目录执行：

```sh
python -m unittest discover -s tests -v
python -m study_reader tasks tests/fixtures/tasks.html --view upcoming
python -m study_reader grades tests/fixtures/grades.html --class-id 12 --class-name 'Test Maths'
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
result = ManageBacReader(transport, max_pages=30).read()
# 先检查 result['complete'] 与 result['errors']，再决定如何私密保存。
```

传输层只允许 HTTPS `sdgj.managebac.cn:443` 下明确的读取路径/view/page 参数，只发 GET；所有重定向均拒绝，包括同站登录跳转。不会把 Cookie 跟随重定向发到第三方。默认 20 秒超时、5 MiB 响应上限、验证状态码/content-type/编码。失败明确报告，不自动重试，不使用旧缓存掩盖失败。不会打印远程响应、Cookie 或认证信息。

真实 HTML/成绩包含隐私，建议放已忽略的 `private/`，不要提交。`.gitignore` 不是防泄漏保证。不要分享浏览器完整 HAR/凭据；需要接口样本时只提供脱敏单请求，删除 token、Cookie、Authorization、姓名/学号等。

## 数据语义与限制

- schema_version=1。`complete` 仅代表本次范围的读取完整性，不是全学期数据保证。
- provenance 的 source/source_url/fetched_at/parsed_at/freshness 区分来源与时间；读取时间不是校方更新时间，也不保证校方页面绝对最新。
- 离线输出 `offline_unknown`，fetched_at=null；只有解析时间，单页始终 complete=false。
- 没日期的任务保留；缺年份/时间不猜默认值，原文保留、value=null。完整英文日期按中国学校 UTC+08:00 解释并标注 timezone_assumption；其它格式未支持时保留原文。
- 重复 ID 最后观察覆盖（含 null 清空），views 合并。冲突列出 conflicting_observations 并 complete=false；读取顺序不等于校方更新时间，需审阅/重读。
- 页数限制、循环、危险/缺 view 分页链接、部分失败都明确报错。失败不丢其它成功数据。pagination complete 仅代表链接遍历；畸形记录另见顶层 errors。
- 成绩 evidence=official_page 是“页面直读而非计算”，不是独立真实性认证。分数字符串保留原文；不把任务分数当课程总评。
- 解析 selector 来源于旧代码；标准库 HTML 树不是完整浏览器 DOM，学校改版可能需更新。未知页面报错，不无声当空列表。

## 验证

离线测试覆盖日期/年份缺失、多行 HTML/实体、时区、官方成绩/缺权重、分数更新清空、同名班级、host allowlist、拒绝重定向、分页上限/循环/失败、登录页、未知布局。网络使用 fake/mock，测试不访问学校。另有编译检查、CLI JSON 冒烟检查。

**尚未验证：真实会话认证、当前线上 HTML、真实任务分页/成绩准确率、课表版本/参数/响应/认证。** 需要后续授权会话或脱敏样本。

## 来源、许可与发布

读取结构/selector 参考用户已有代码并隔离为新只读模块：

- [To-do-list/managebac_backend.py](https://github.com/kuxiaowo/To-do-list/blob/main/managebac_backend.py)，blob SHA `8ea8f88c148ca4943c17f72be21dd5b81f74a883`
- [MangeBac-Dashboard/scraper.py](https://github.com/kuxiaowo/MangeBac-Dashboard/blob/main/scraper.py)，blob SHA `9d9a0fb9d87be65edbfcedaa85b14e4e92f3437a`

未搬入数据库、UI、登录提交、AppleScript、硬编码年份或默认分数线。**上游许可/再分发条件尚未确认，不擅自添加开源许可证。** 项目名称为 MB-data-reader；公开发布前应确认许可、学校规则，并检查凭据和学生数据。发布包仅包含代码、文档、测试与虚构示例，不包含真实账号、会话或学习数据。
