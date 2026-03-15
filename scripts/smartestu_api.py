#!/usr/bin/env python3
import argparse
import json
import os
import urllib.error
import urllib.request
import http.cookiejar
from typing import Any, Dict

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
        return self._request(
            "GET",
            QUESTION_PATH_TEMPLATE.format(homework_id=homework_id),
            payload=None,
        )

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

    print(json.dumps({"ok": True, "data": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
