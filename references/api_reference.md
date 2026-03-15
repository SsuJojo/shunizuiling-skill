# smartestu api reference

## constants
- base url: `https://smartestu.cn`
- school code: `scnu`
- fixed course id: `1436`
- environment variables:
  - `SNZL_ID`: student local i
  - `SNZL_PSWD`: password

## auth flow
1. call `POST /api/auth/login`
2. build `schoolUserId` as `scnu-{SNZL_ID}`
3. read bearer token from the response body field `token`
4. preserve cookies returned by the server for follow-up calls

## supported endpoints

### login
`POST /api/auth/login`

request body:
```json
{
  "schoolUserLocalId": "${SNZL_ID}",
  "password": "${SNZL_PSWD}",
  "schoolCode": "scnu",
  "schoolUserId": "scnu-${SNZL_ID}"
}
```

### query courses
`POST /api/homework/student/course/query`

request body:
```json
{
  "studentId": "scnu-${SNZL_ID}"
}
```

### query homeworks for the fixed course
`POST /api/homework/student/mark/queryHomeworks`

request body:
```json
{
  "studentId": "scnu-${SNZL_ID}",
  "courseIds": [1436]
}
```

### query generated questions for one homework
`GET /api/homework/homework/{homework_id}/generated-questions`

### query per-exercise marks and feedback for one homework
`POST /api/homework/student/mark/queryExercisesByHomeworkId`

request body:
```json
{
  "homeworkId": 7984,
  "studentId": "scnu-${SNZL_ID}"
}
```

response highlights:
- `data.homeworkInfo`: homework name, total score, time window, resubmission flags
- `data.studentExerciseMarkList[]`: one row per exercise with `exerciseId`, `exerciseName`, `score`, `markText`, `ansUrls`, `updatedAt`, plagiarism/handwriting flags, and resubmit info
- use this endpoint when the user asks why a homework did not get full marks, wants teacher/AI feedback, or wants per-question scores

## implementation notes
- the helper script prints raw json for machine use
- the skill instructions tell the model to convert the raw json into natural chinese
- never echo `SNZL_PSWD`
- never print the full bearer token unless the user explicitly asks for debugging
- if the course query shows that course `1436` is missing, say so explicitly before attempting homework lookup
- when the user says phrases like `数你最灵` and asks to view assignments, this skill should interpret the request as a homework query for the fixed course

## future extension ideas
- homework detail lookup
- answer draft generation
- submission endpoints
- grade and feedback queries
