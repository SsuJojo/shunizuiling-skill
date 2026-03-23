#!/usr/bin/env python3
import argparse
import json
import os
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path
from typing import Any, Dict


DETAIL_MODE = os.environ.get("SNZL_DETAIL_MODE", "compact").strip().lower()
HOMEWORK_FILTER_ID = os.environ.get("SNZL_HOMEWORK_ID", "").strip()
HOMEWORK_FILTER_NAME = os.environ.get("SNZL_HOMEWORK_NAME", "").strip()
HOMEWORK_FILTER_LATEST = os.environ.get("SNZL_HOMEWORK_LATEST", "").strip().lower() in {"1", "true", "yes", "on"}


DROP_KEYS = {
    "url",
    "tfSpec",
    "mcqSpec",
    "objectiveGroupSpec",
    "answerStructure",
    "customAnswerTime",
    "customAppealDeadline",
    "onlineExamStartedAt",
    "onlineExamEndedAt",
    "imageProblemType",
    "studentSubExercise",
    "lateSubmissionRecord",
    "teacherReply",
    "referenceSolution",
    "modelOutput",
    "raw",
}


def clean_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if key in DROP_KEYS:
                continue
            child_clean = clean_payload(child)
            if child_clean is None:
                continue
            if child_clean == {} or child_clean == []:
                continue
            cleaned[key] = child_clean
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            item_clean = clean_payload(item)
            if item_clean is None or item_clean == {} or item_clean == []:
                continue
            cleaned_list.append(item_clean)
        return cleaned_list
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    return value


def compact_question_block(exercise: Dict[str, Any], include_details: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": exercise.get("id"),
        "name": exercise.get("name"),
        "questionNum": exercise.get("questionNum"),
        "score": exercise.get("score"),
        "questionType": exercise.get("questionType"),
    }

    question_structure = exercise.get("questionStructure") or []
    if question_structure:
        first = question_structure[0] or {}
        main = first.get("mainQuestion") or {}
        if main.get("questionMd"):
            result["questionMd"] = main.get("questionMd")
        subs = []
        for sub in first.get("subQuestions") or []:
            item = {
                "questionNum": sub.get("questionNum"),
                "questionMd": sub.get("questionMd"),
            }
            item = clean_payload(item)
            if item:
                subs.append(item)
        if subs:
            result["subQuestions"] = subs
    elif exercise.get("questions"):
        texts = [x.get("content") for x in exercise.get("questions", []) if isinstance(x, dict) and x.get("content")]
        if texts:
            result["questionText"] = "\n".join(texts)

    if include_details:
        if exercise.get("studentAnswer"):
            result["studentAnswer"] = exercise.get("studentAnswer")
        elif exercise.get("answerImages"):
            result["answerImages"] = exercise.get("answerImages")

        if exercise.get("answers"):
            answer_texts = [x.get("content") for x in exercise.get("answers", []) if isinstance(x, dict) and x.get("content")]
            if answer_texts:
                result["answers"] = answer_texts

    return clean_payload(result)


def compact_homeworks_output(output: Dict[str, Any], include_details: bool = False, homework_id: int | None = None, homework_name: str | None = None, next_pending: bool = False) -> Dict[str, Any]:
    data = output.get("data") or {}
    rows = []
    for course_block in data.get("courseHomeworkDTOList") or []:
        source_homeworks = list(course_block.get("studentCourseHomeworkDTOList") or [])

        if next_pending:
            pending = [hw for hw in source_homeworks if str(hw.get("submission_status")) == "not_submitted"]
            pending.sort(key=lambda hw: str(hw.get("endTime") or "9999-12-31T23:59:59Z"))
            source_homeworks = pending[:1] if pending else source_homeworks[:1]

        homeworks = []
        for hw in source_homeworks:
            if homework_id is not None and hw.get("id") != homework_id:
                continue
            if homework_name and homework_name not in str(hw.get("name", "")):
                continue
            homeworks.append(
                clean_payload(
                    {
                        "id": hw.get("id"),
                        "name": hw.get("name"),
                        "startTime": hw.get("startTime"),
                        "endTime": hw.get("endTime"),
                        "teacherName": hw.get("teacherName"),
                        "totalScore": hw.get("totalScore"),
                        "score": hw.get("score"),
                        "status": hw.get("status"),
                        "submission_status": hw.get("submission_status"),
                        "review_status": hw.get("review_status"),
                        "allowCorrection": hw.get("allowCorrection"),
                        "enableResubmit": hw.get("enableResubmit"),
                        "resubmitTimes": hw.get("resubmitTimes"),
                        "exercise_status": hw.get("exercise_status"),
                        "exercises": [compact_question_block(ex, include_details=include_details) for ex in hw.get("exercises") or []],
                    }
                )
            )
        rows.append(
            clean_payload(
                {
                    "courseId": course_block.get("courseId"),
                    "courseName": course_block.get("courseName"),
                    "homeworks": homeworks,
                }
            )
        )
    return clean_payload({**output, "data": {"courseHomeworkDTOList": rows, "detailMode": "detail" if include_details else "compact", "filter": {"homeworkId": homework_id, "homeworkName": homework_name, "next": next_pending}}})


def compact_exercise_marks_output(output: Dict[str, Any], include_details: bool = False) -> Dict[str, Any]:
    data = output.get("data") or {}
    return clean_payload(
        {
            **output,
            "data": {
                "detailMode": "detail" if include_details else "compact",
                "homeworkInfo": {
                    "id": data.get("homeworkInfo", {}).get("id"),
                    "name": data.get("homeworkInfo", {}).get("name"),
                    "totalScore": data.get("homeworkInfo", {}).get("totalScore"),
                    "startTime": data.get("homeworkInfo", {}).get("startTime"),
                    "endTime": data.get("homeworkInfo", {}).get("endTime"),
                    "enableResubmit": data.get("homeworkInfo", {}).get("enableResubmit"),
                    "resubmitTimes": data.get("homeworkInfo", {}).get("resubmitTimes"),
                },
                "studentExerciseMarkList": [
                    clean_payload(
                        {
                            "exerciseId": item.get("exerciseId"),
                            "exerciseName": item.get("exerciseName"),
                            "score": item.get("score"),
                            "status": item.get("status"),
                            "markText": item.get("markText"),
                            "updatedAt": item.get("updatedAt"),
                            "markPayload": {
                                "items": [
                                    clean_payload(
                                        {
                                            "questionNumber": sub.get("questionNumber"),
                                            "scoreStr": sub.get("scoreStr"),
                                            "errorReason": sub.get("errorReason"),
                                        }
                                    )
                                    for sub in ((item.get("markPayload") or {}).get("items") or [])
                                ]
                            },
                            **({"ansUrls": item.get("ansUrls")} if include_details and item.get("ansUrls") else {}),
                        }
                    )
                    for item in data.get("studentExerciseMarkList") or []
                ],
            },
        }
    )

BASE_URL = "https://smartestu.cn"
SCHOOL_CODE = "scnu"
# Course is not hard-coded.
# Resolution order:
# 1) SNZL_COURSE_ID (exact id)
# 2) SNZL_COURSE_NAME (substring match on course name)
# 3) If the account only has one course, use that course's id
COURSE_ID: int | None = None
LOGIN_PATH = "/api/auth/login"
COURSE_QUERY_PATH = "/api/homework/student/course/query"
HOMEWORK_QUERY_PATH = "/api/homework/student/mark/queryHomeworks"
QUESTION_PATH_TEMPLATE = "/api/homework/homework/{homework_id}/generated-questions"
EXERCISE_MARKS_PATH = "/api/homework/student/mark/queryExercisesByHomeworkId"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/assignment",
    "User-Agent": "Mozilla/5.0 (compatible; smartestu-openclaw-skill/1.0)",
}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def save_cache(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_memory_hint(platform: str, course: Dict[str, Any] | None, items: list[Dict[str, Any]]) -> Dict[str, Any]:
    course = course or {}
    return {
        "platform": platform,
        "course": {"title": course.get("name"), "courseId": course.get("id"), "teacher": course.get("teacherName")},
        "items": [{"homeworkId": x.get("id") or x.get("homeworkId"), "title": x.get("title") or x.get("name"), "status": x.get("status") or x.get("submitStatus"), "deadline": x.get("deadline") or x.get("endTime")} for x in items],
        "summary": f"{platform}｜{course.get('name') or '未知课程'}｜共{len(items)}项",
    }


class SmartestuClient:
    def __init__(self) -> None:
        self.local_id = require_env("SNZL_ID")
        self.password = require_env("SNZL_PSWD")
        self.school_user_id = f"{SCHOOL_CODE}-{self.local_id}"
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.token: str | None = None

    def _request(self, method: str, path: str, payload: Dict[str, Any] | None = None, use_auth: bool = True, referer: str | None = None) -> Any:
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        if use_auth:
            if not self.token:
                raise RuntimeError("authentication required before calling this endpoint")
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=f"{BASE_URL}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http {exc.code} for {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"request failed for {path}: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    def login(self) -> Dict[str, Any]:
        payload = {
            "schoolUserLocalId": self.local_id,
            "password": self.password,
            "schoolCode": SCHOOL_CODE,
            "schoolUserId": self.school_user_id,
        }
        result = self._request("POST", LOGIN_PATH, payload=payload, use_auth=False, referer=f"{BASE_URL}/login")
        token = result.get("token")
        if not token:
            raise RuntimeError(f"login succeeded but token missing: {json.dumps(result, ensure_ascii=False)}")
        self.token = token
        return result

    def query_courses(self) -> Any:
        return self._request(
            "POST",
            COURSE_QUERY_PATH,
            payload={"studentId": self.school_user_id},
        )

    def resolve_course_id(self) -> int:
        """Resolve course id dynamically.

        Uses env overrides when present; otherwise queries the user's course list.
        """
        env_id = os.environ.get("SNZL_COURSE_ID", "").strip()
        if env_id:
            try:
                return int(env_id)
            except ValueError as exc:
                raise RuntimeError(f"invalid SNZL_COURSE_ID: {env_id}") from exc

        env_name = os.environ.get("SNZL_COURSE_NAME", "").strip()
        courses_resp = self.query_courses()
        courses = (courses_resp or {}).get("data")
        if courses is None and isinstance(courses_resp, dict):
            # Some responses wrap data differently; keep a best-effort fallback.
            courses = courses_resp.get("data", [])
        if not isinstance(courses, list):
            raise RuntimeError(f"unexpected courses response: {json.dumps(courses_resp, ensure_ascii=False)}")

        if env_name:
            hits = [c for c in courses if env_name in str(c.get("name", ""))]
            if len(hits) == 1:
                return int(hits[0]["id"])
            if len(hits) > 1:
                choices = [{"id": c.get("id"), "name": c.get("name") } for c in hits]
                raise RuntimeError(f"SNZL_COURSE_NAME matched multiple courses: {choices}")
            # fall through to generic resolution when no match

        if len(courses) == 1 and "id" in courses[0]:
            return int(courses[0]["id"])

        choices = [{"id": c.get("id"), "name": c.get("name"), "teacherName": c.get("teacherName")} for c in courses]
        raise RuntimeError(
            "multiple courses found; set SNZL_COURSE_ID or SNZL_COURSE_NAME to choose one. "
            f"available: {choices}"
        )

    def query_homeworks(self) -> Any:
        course_id = self.resolve_course_id()
        return self._request(
            "POST",
            HOMEWORK_QUERY_PATH,
            payload={"studentId": self.school_user_id, "courseIds": [course_id]},
        )

    def query_questions(self, homework_id: int) -> Any:
        raw = self._request(
            "GET",
            QUESTION_PATH_TEMPLATE.format(homework_id=homework_id),
            payload=None,
        )
        if not isinstance(raw, dict):
            return {
                "code": 200,
                "msg": "generated questions hidden",
                "data": {
                    "homeworkId": homework_id,
                    "questions": [],
                    "totalCount": 0,
                    "hiddenGeneratedQuestions": True,
                },
            }

        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        return {
            **raw,
            "msg": "generated questions hidden",
            "data": {
                "homeworkId": data.get("homeworkId", homework_id),
                "homeworkName": data.get("homeworkName"),
                "questions": [],
                "totalCount": 0,
                "hiddenGeneratedQuestions": True,
            },
        }

    def query_exercise_marks(self, homework_id: int, student_id: str | None = None) -> Any:
        return self._request(
            "POST",
            EXERCISE_MARKS_PATH,
            payload={
                "homeworkId": homework_id,
                "studentId": student_id or self.school_user_id,
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="smartestu api helper for the openclaw skill")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="log in and print sanitized account info")
    sub.add_parser("courses", help="list the student's course data")
    sub.add_parser("homeworks", help="list homeworks for a resolved course id (not hard-coded)")
    q = sub.add_parser("questions", help="get generated questions for a homework id")
    q.add_argument("homework_id", type=int, help="homework id such as 7984")
    m = sub.add_parser("exercise-marks", help="get per-exercise scores and feedback for a homework id")
    m.add_argument("homework_id", type=int, help="homework id such as 7984")
    m.add_argument("--student-id", dest="student_id", help="override studentId such as scnu-20254002061")

    for parser_ in [sub.choices["homeworks"], sub.choices["exercise-marks"], sub.choices["questions"]]:
        parser_.add_argument("--detail", action="store_true", help="return detail payload instead of compact mode")

    sub.choices["homeworks"].add_argument("--homework-id", type=int, help="filter a single homework by id")
    sub.choices["homeworks"].add_argument("--name", dest="homework_name", help="filter homeworks by substring match on name")
    sub.choices["homeworks"].add_argument("--next", action="store_true", help="return the oldest pending homework, or the first homework if none are pending")

    args = parser.parse_args()

    try:
        client = SmartestuClient()
        login_result = client.login()
        if args.command == "login":
            output = {
                "token_present": bool(login_result.get("token")),
                "user": {
                    "id": login_result.get("user", {}).get("id") or login_result.get("user", {}).get("_id"),
                    "name": login_result.get("user", {}).get("name"),
                    "schoolUserId": login_result.get("user", {}).get("schoolUserId"),
                    "role": login_result.get("user", {}).get("role"),
                    "email": login_result.get("user", {}).get("email"),
                },
            }
        elif args.command == "courses":
            output = client.query_courses()
        elif args.command == "homeworks":
            output = client.query_homeworks()
        elif args.command == "questions":
            output = client.query_questions(args.homework_id)
        elif args.command == "exercise-marks":
            output = client.query_exercise_marks(args.homework_id, student_id=args.student_id)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    include_details = bool(getattr(args, "detail", False)) or DETAIL_MODE == "detail"
    env_homework_id = int(HOMEWORK_FILTER_ID) if HOMEWORK_FILTER_ID.isdigit() else None
    cli_homework_id = getattr(args, "homework_id", None) if args.command == "homeworks" else None
    effective_homework_id = cli_homework_id or env_homework_id
    effective_homework_name = (getattr(args, "homework_name", None) or HOMEWORK_FILTER_NAME or None)
    effective_next = bool(getattr(args, "next", False)) or HOMEWORK_FILTER_NEXT
    if args.command == "homeworks":
        output = compact_homeworks_output(output, include_details=include_details, homework_id=effective_homework_id, homework_name=effective_homework_name, next_pending=effective_next)
    elif args.command == "exercise-marks":
        output = compact_exercise_marks_output(output, include_details=include_details)
    cleaned_output = clean_payload(output)
    print(json.dumps({"ok": True, "data": cleaned_output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
