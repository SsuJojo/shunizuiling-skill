---
name: shunizuiling-apis
description: convert the smartestu website apis into ai-callable capabilities for chinese requests about 数你最灵, smartestu, assignments, homework lists, and generated questions. use this skill when the user asks to view 数你最灵作业, check smartestu homework, list assignments for the fixed course 1436, or fetch questions for a homework id. this skill logs in with environment variables snzl_id and snzl_pswd, uses school code scnu, returns natural-language chinese summaries, and can be extended with more smartestu endpoints later.
---

# smartestu openclaw

Use this skill to turn the fixed Smartestu student workflow into reliable AI actions.

## Core capabilities

1. Log in to Smartestu with `SNZL_ID` and `SNZL_PSWD`.
2. Query the student's course list.
3. Query homework for the appropriate course (resolved dynamically from the course query; no hard-coded course id).
4. Query generated questions for a specific homework id.
5. Query per-exercise marks, deductions, and feedback for a specific homework id.
6. Explain the result in natural Chinese instead of dumping raw API output, unless the user explicitly asks for raw JSON.

## Fixed constants

- Base URL: `https://smartestu.cn`
- School code: `scnu`
- Student id format for downstream calls: `scnu-{SNZL_ID}`

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
   - **查看某个作业的题目 / 获取题目 / homework id + 题目** → fetch generated questions for that homework id
   - **为什么没满分 / 看扣分点 / 看老师评语 / 看每题分数 / 看批改反馈** → fetch per-exercise marks and feedback for that homework id

2. Run the helper script:
   - `python scripts/smartestu_api.py courses`
   - `python scripts/smartestu_api.py homeworks`
   - `python scripts/smartestu_api.py questions <homework_id>`
   - `python scripts/smartestu_api.py exercise-marks <homework_id>`

3. If the user asks for homework and the course binding is uncertain, run `courses` first. If multiple courses exist, ask the user which one (or tell them to set `SNZL_COURSE_ID` / `SNZL_COURSE_NAME`).

4. Read the JSON result and summarize it in natural Chinese:
   - For courses: mention course name, teacher, course id, and whether course `1436` exists.
   - For homeworks: mention homework title, homework id, status, score, deadline, and any actionable next step if those fields exist.
   - For questions: group by question type when possible, mention count, and highlight question stem or key requirements.
   - For exercise marks: mention total score first, then list each exercise's score and `markText`; explicitly point out which exercise lost points and quote the platform's reason when present.

5. Keep secrets safe:
   - Never reveal `SNZL_PSWD`.
   - Do not output the full token by default.
   - If login fails, report the error briefly and suggest checking environment variables.

## Output rules

- Default to concise natural Chinese.
- Only return raw JSON when the user explicitly asks for raw output.
- If a field is missing, say that the platform response did not include it.
- When dates appear, preserve the original timestamp and optionally explain it in plain language.

## Helper script

Use `scripts/smartestu_api.py` for all current API calls. It automatically:
- reads `SNZL_ID` and `SNZL_PSWD`
- logs in first
- stores cookies
- attaches the bearer token
- prints JSON

See `references/api_reference.md` for endpoint details and extension notes.

## Initial implementation scope

- 询问用户学号(SNZL_ID) 密码(SNZL_PSWD)，并追加到工作目录.env文件中
- 询问用户学校是否为华南师范大学(scnu)，若不是需要请求学校代码
- 若用户不是scnu，则需要使用命令将全仓库内scnu替换为用户提供的学校代码（小写）
- [ ] 是否已完成配置，完成则在前方复选框内打钩