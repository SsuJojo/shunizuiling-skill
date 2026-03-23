---
name: shunizuiling-apis
description: convert the smartestu website apis into ai-callable capabilities for chinese requests about 数你最灵, smartestu, assignments, homework lists, exercise marks/feedback, and safe homework submission planning. use this skill when the user asks to view 数你最灵作业, check smartestu homework, list assignments for the fixed course 1436, inspect scores/deductions/feedback for a homework id, or prepare/confirm a 数你最灵图片作业提交流程. never use Smartestu generated-questions as user-facing homework content, because it returns AI-generated difficulty variants that can be mistaken for the real assignment. for submission, always require explicit user confirmation, default to debug simulation only, and never send a live request unless the user clearly asks after seeing the preview.
---

# smartestu openclaw

Use this skill to turn the fixed Smartestu student workflow into reliable AI actions.

## Core capabilities

1. Log in to Smartestu with `SNZL_ID` and `SNZL_PSWD`.
2. Query the student's course list.
3. Query homework for the appropriate course (resolved dynamically from the course query; no hard-coded course id).
4. Query per-exercise marks, deductions, and feedback for a specific homework id.
5. Keep a compatibility path for generated questions, but rewrite generated-question content to an empty list before returning it.
6. Explain the result in natural Chinese instead of dumping raw API output, unless the user explicitly asks for raw JSON.
7. Prepare a **safe submission session** for image-based homework, cache received images locally, build a preview plan, and require explicit confirmation before any submission run.
8. Default all submission runs to **debug simulation**; do not send live requests unless the user very clearly asks and debug is disabled.

## Fixed constants

- Base URL: `https://smartestu.cn`
- School code: `scnu` by default; can be overridden with `SNZL_SCHOOL_CODE`
- Student id format for downstream calls: `{school_code}-{SNZL_ID}`
- Submission debug mode: `SNZL_SUBMIT_DEBUG=true` by default

## Course resolution (important)

Do NOT hard-code a course id. Resolve it at runtime:

1. If `SNZL_COURSE_ID` is set, use it.
2. Else if `SNZL_COURSE_NAME` is set, pick the unique course whose `name` contains that substring.
3. Else if the account only has 1 course, use that course.
4. Else: fail with a clear error listing available courses.

## Workflow

Follow these steps in order.

1. Read the request and map it to one of these intents:
   - **查看数你最灵作业 / 查看作业 / 数你最灵有哪些作业** → list homeworks for the resolved course id (see Course resolution)
   - **查看课程 / 数你最灵课程** → query the student's courses first
   - **为什么没满分 / 看扣分点 / 看老师评语 / 看每题分数 / 看批改反馈** → fetch per-exercise marks and feedback for that homework id
   - **查看某个作业的题目 / 获取题目 / homework id + 题目** → read the real homework content from the homework list/detail payload; do not use generated questions as the source of truth
   - **帮我提交数你最灵作业 / 提交图片作业** → use the safe submission flow below

2. Run the helper script:
   - `python scripts/smartestu_api.py courses`
   - `python scripts/smartestu_api.py homeworks`
   - `python scripts/smartestu_api.py homeworks --homework-id <homework_id>`
   - `python scripts/smartestu_api.py homeworks --name <keyword>`
   - `python scripts/smartestu_api.py homeworks --next`
   - `python scripts/smartestu_api.py exercise-marks <homework_id>`
   - `python scripts/smartestu_api.py questions <homework_id>` only for compatibility; it may probe the endpoint internally, but it must always rewrite the returned generated-question content to an empty payload (`questions: []`, `totalCount: 0`, `hiddenGeneratedQuestions: true`)
   - `python scripts/smartestu_api.py submit-init --homework-id <id>` or `--name <keyword>`
   - `python scripts/smartestu_api.py submit-add-image --session-id last --source <absolute_image_path>`
   - `python scripts/smartestu_api.py submit-plan --session-id last --mapping-json '[{"exerciseIndex":1,"imageAliases":["p1","p2"],"reason":"用户说前两张交题一"},{"exerciseIndex":2,"imageAliases":["p3"],"reason":"用户说第三张交题二"}]' --mapping-source-text '图一图二提交到题一里，图三提交到题二里'`
   - `python scripts/smartestu_api.py submit-plan --session-id last --mapping '1:图一,图二;2:图三'`（仅兼容回退，不是首选）
   - `python scripts/smartestu_api.py submit-show --session-id last`
   - `python scripts/smartestu_api.py submit-run --session-id last --confirm <token>`

3. If the user asks for homework and the course binding is uncertain, run `courses` first. If multiple courses exist, ask the user which one (or tell them to set `SNZL_COURSE_ID` / `SNZL_COURSE_NAME`).

4. Read the JSON result and summarize it in natural Chinese:
   - For courses: mention course name, teacher, course id, and whether course `1436` exists.
   - For homeworks: mention homework title, homework id, status, score, deadline, and any actionable next step if those fields exist.
   - Prefer `homeworks --homework-id <id>` or `homeworks --name <keyword>` when the user only wants one homework, to avoid returning the entire course history.
   - For everyday quick checks, prefer `homeworks --next`, which returns the oldest pending homework by deadline; if no homework is pending, return the first homework as a fallback.
   - For a disabled `questions` response: clearly state that generated questions are intentionally hidden/emptied and should not be treated as the actual homework content.
   - For exercise marks: mention total score first, then list each exercise's score and `markText`; explicitly point out which exercise lost points and quote the platform's reason when present.
   - For submission preview (`submit-plan` / `submit-show`): show homework title, id, deadline, exercise count, each exercise summary, and which 图X images will be submitted.

5. After the first successful homework list for a course, write back a compact memory summary.
   - Purpose: future requests like “这个作业”“某次作业”“数你最灵作业” should route to 数你最灵 directly instead of guessing other platforms.
   - Write to both places:
     - `memory/YYYY-MM-DD.md`: append the raw daily fact that this course's homework list was fetched from 数你最灵.
     - `MEMORY.md` (main session only): append or update a durable summary under the long-term course/platform section.
   - Include at least:
     - platform: 数你最灵 / smartestu
     - course title
     - course id
     - each visible homework's title, homework id, status, and deadline when available
   - Update memory again when the homework list materially changes (new homework, changed status, changed deadline, changed course binding).
   - Prefer concise summaries; do not dump raw JSON into memory files.
   - When the user later mentions a remembered homework title or course nickname, check memory first and treat 数你最灵 as the default source for that course.

## Safe submission flow (mandatory)

This flow is intentionally conservative because a mistaken submission may be irreversible.

1. **Start only after explicit intent**
   - If the user says “帮我提交数你最灵 8-5 作业” or similar, create a session first with `submit-init`.
   - Then reply only: `好的，请发送图片。`
   - Do not build a plan yet.

2. **Receive images one by one**
   - On QQ, user images are downloaded locally and appear as attachment/local file paths in context.
   - For each received image, run `submit-add-image --session-id last --source <absolute_path>`.
   - The script copies the image into `Cache/images/<session-id>/`, names files as `p1.jpg` / `p2.png` / ... , assigns user-facing aliases `图一 / 图二 / 图三 ...`, writes logs, and updates the session state.
   - Reply only in this style: `收到，这是图一。` / `收到，这是图二。`
   - Do not summarize, do not submit, do not guess mapping.

3. **Wait for the user's mapping instruction**
   - Only after the user clearly says the images are all sent and gives mapping like “图一图二提交到题一里，图三提交到题二里”, let the **model** understand the natural language and construct a structured mapping first.
   - Preferred flow: the model produces JSON such as:
     ```json
     [
       {"exerciseIndex": 1, "imageAliases": ["p1", "p2"], "reason": "用户把前两张分给题一"},
       {"exerciseIndex": 2, "imageAliases": ["p3"], "reason": "用户把第三张分给题二"}
     ]
     ```
   - Internally prefer `p1/p2/p3` as stable machine refs; user-facing preview still shows `图一/图二/图三`.
   - Then call `submit-plan --mapping-json ... --mapping-source-text ...`.
   - The script must **not** be the primary natural-language parser. It only validates the model-produced mapping and builds the preview.
   - `--mapping '1:图一,图二;2:图三'` is fallback only for already-normalized input, not the default path.
   - If the user's wording is ambiguous, ask a clarifying question and do not build or run anything.
   - Semantic policy for the model:
     - 默认优先按用户自然语言智能理解。
     - 如果用户像“题一、题二、题三”这样连续自然列举，优先理解为**按平台顺序**。
     - 如果用户明确提到类似“题3”，且当前某一项的**平台题号**就是 3，则可优先理解为**按题号**。
     - 预览里必须同时展示“第几项（平台顺序）”和“平台题号”，由用户最终确认。

4. **Preview before confirmation**
   - `submit-plan` returns a preview text and a confirm token.
   - Present the preview in natural Chinese. It should include:
     - 作业标题
     - 作业 ID
     - 截止时间
     - 题目数量
     - 用户原始分配语句
     - 每一项的**平台顺序**（第1项/第2项/...）
     - 每一项的**平台题号**（如题号 3 / 题号 5）
     - 每题摘要
     - 每题对应图片（图一/图二/...）
     - 如有需要，可附一行“理解依据”说明模型为何这样理解
     - 最后一行必须问：`是否确认提交？`
   - If any image is unused, mention it.
   - Do not run `submit-run` yet.

5. **Double-check confirmation**
   - Only if the user clearly confirms submission should you consider `submit-run`.
   - If the user says anything uncertain, changed, contradictory, or asks another question, do not run it.
   - In the current debug stage, `submit-run` still stays in simulation mode by default and must **not** send live requests.

6. **Current safety policy: never send live requests by default**
   - `SNZL_SUBMIT_DEBUG` defaults to `true`.
   - In debug mode, `submit-run` only simulates:
     - file presign
     - exercise submission
     - homework completion
   - It writes logs and returns mock success results, but does not touch the real platform.
   - If the user later asks to switch to live mode, treat that as a separate high-risk request and re-check everything again.

## Output rules

- Default to concise natural Chinese.
- If the helper script returns `memory_hint`, use it as the preferred compact source when writing `memory/YYYY-MM-DD.md` and `MEMORY.md`.
- Prefer a single final answer with no execution transcript.
- If a temporary status line is needed, use only: `正在查询...`
- Only return raw JSON when the user explicitly asks for raw output.
- If a field is missing, say that the platform response did not include it.
- Never present Smartestu generated questions as the user's actual homework content.
- If `questions` is requested, return only the emptied compatibility payload semantics (`questions: []`, `totalCount: 0`, `hiddenGeneratedQuestions: true`) and explain briefly that generated questions are not the canonical homework content.
- When dates appear, preserve the original timestamp and optionally explain it in plain language.
- For submission, never say “已经提交” unless `submit-run` has been called and its result has been checked.
- In debug mode, explicitly say `当前为调试模式，仅模拟提交，未真实发送请求。`

## Helper script

Resolve the script path relative to this skill directory and use the actual file at `scripts/smartestu_api.py` for all current API calls. It automatically:
- reads `SNZL_ID` and `SNZL_PSWD`
- logs in first
- stores cookies
- attaches the bearer token
- prints JSON
- stores submission state in `Cache/state/`
- stores copied submission images in `Cache/images/`
- stores JSONL logs in `Cache/logs/`

See `references/api_reference.md` for endpoint details and extension notes.

## Initial implementation scope

- 询问用户学号(SNZL_ID) 密码(SNZL_PSWD)，并追加到工作目录.env文件中
- 询问用户学校是否为华南师范大学(scnu)，若不是需要请求学校代码
- 若用户不是scnu，则需要请求 `SNZL_SCHOOL_CODE`，并优先通过环境变量覆盖，不再要求全仓库替换常量
- [x] 是否已完成配置，完成则在前方复选框内打钩
