# smartestu api reference

## constants
- base url: `https://smartestu.cn`
- default school code: `scnu`
- environment variables:
  - `SNZL_ID`: student local id
  - `SNZL_PSWD`: password
  - `SNZL_COURSE_ID`: optional fixed course id override
  - `SNZL_COURSE_NAME`: optional course name substring override
  - `SNZL_SCHOOL_CODE`: optional school code override, defaults to `scnu`
  - `SNZL_SUBMIT_DEBUG`: debug switch for submission flow, defaults to `true`

## auth flow
1. call `POST /api/auth/login`
2. build `schoolUserId` as `{schoolCode}-{SNZL_ID}`
3. read bearer token from the response body field `token`
4. preserve cookies returned by the server for follow-up calls

## supported endpoints

> generated-questions endpoint is intentionally hidden again for user-facing output. Keep compatibility in code, but do not treat it as canonical homework content.

### login
`POST /api/auth/login`

request body:
```json
{
  "schoolUserLocalId": "${SNZL_ID}",
  "password": "${SNZL_PSWD}",
  "schoolCode": "${SNZL_SCHOOL_CODE:-scnu}",
  "schoolUserId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}"
}
```

### query courses
`POST /api/homework/student/course/query`

request body:
```json
{
  "studentId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}"
}
```

### query homeworks
`POST /api/homework/student/mark/queryHomeworks`

request body:
```json
{
  "studentId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}",
  "courseIds": [1436]
}
```

> actual course id should be resolved dynamically by the helper script unless `SNZL_COURSE_ID` is set.

### query generated questions for one homework
`GET /api/homework/homework/{homework_id}/generated-questions`

### query per-exercise marks and feedback for one homework
`POST /api/homework/student/mark/queryExercisesByHomeworkId`

request body:
```json
{
  "homeworkId": 7984,
  "studentId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}"
}
```

response highlights:
- `data.homeworkInfo`: homework name, total score, time window, resubmission flags
- `data.studentExerciseMarkList[]`: one row per exercise with `exerciseId`, `exerciseName`, `score`, `markText`, `ansUrls`, `updatedAt`, plagiarism/handwriting flags, and resubmit info
- use this endpoint when the user asks why a homework did not get full marks, wants teacher/AI feedback, or wants per-question scores

## submission flow endpoints (captured from HAR)

### presign upload url(s)
`POST /api/homework/files/presign/batch`

request body:
```json
{
  "files": [
    {"originalName": "example.jpg"}
  ]
}
```

response highlights:
- `data[].putUrl`: pre-signed object storage upload URL
- `data[].url`: final Smartestu CDN URL used in `answerUrl`
- `data[].originalKey`: object key on storage backend

### upload binary to putUrl
`PUT <putUrl from presign response>`

notes:
- upload target is currently Volcano/TOS style object storage
- helper script keeps this path implemented but debug mode should skip it by default

### submit one exercise answer
`POST /api/homework/student/exercise/submit`

request body:
```json
{
  "exerciseId": 46120,
  "studentId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}",
  "answerUrl": [
    "https://smartestu.cn/uploads/homework/1774193167010-f5d83415.jpg",
    "https://smartestu.cn/uploads/homework/1774193173750-2b5b09d5.jpg"
  ]
}
```

successful response sample:
```json
{"code":200,"msg":"提交题目答案成功","data":{"success":true},"success":true}
```

### complete homework
`POST /api/homework/student/homework/complete`

request body:
```json
{
  "homeworkId": 7986,
  "studentId": "${SNZL_SCHOOL_CODE:-scnu}-${SNZL_ID}"
}
```

successful response sample:
```json
{"code":200,"msg":"完成作业成功","success":true}
```

## helper commands for safe submission

- `python scripts/smartestu_api.py submit-init --homework-id 9724`
- `python scripts/smartestu_api.py submit-add-image --session-id last --source C:/path/to/image1.jpg`
- `python scripts/smartestu_api.py submit-plan --session-id last --mapping-json '[{"exerciseIndex":1,"imageAliases":["p1","p2"],"reason":"按用户语义分配到第1项"},{"exerciseIndex":2,"imageAliases":["p3"],"reason":"按用户语义分配到第2项"}]' --mapping-source-text '图一图二提交到题一里，图三提交到题二里'`
- `python scripts/smartestu_api.py submit-plan --session-id last --mapping '1:图一,图二;2:图三'`  # legacy fallback only
- `python scripts/smartestu_api.py submit-show --session-id last`
- `python scripts/smartestu_api.py submit-run --session-id last --confirm ABCDEF1234`

## implementation notes
- the helper script prints raw json for machine use
- the skill instructions tell the model to convert the raw json into natural chinese
- submission cache lives under `Cache/`
  - `Cache/state/`: submission sessions
  - `Cache/images/`: copied user images
  - `Cache/logs/`: jsonl logs
- never echo `SNZL_PSWD`
- never print the full bearer token unless the user explicitly asks for debugging
- if the course query shows that the expected course is missing, say so explicitly before attempting homework lookup
- when the user says phrases like `数你最灵` and asks to view assignments, this skill should interpret the request as a homework query for the bound course
- in the current debug stage, prefer simulation only; do not send live submission requests by default
