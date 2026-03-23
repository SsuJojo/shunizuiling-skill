#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DETAIL_MODE = os.environ.get("SNZL_DETAIL_MODE", "compact").strip().lower()
HOMEWORK_FILTER_ID = os.environ.get("SNZL_HOMEWORK_ID", "").strip()
HOMEWORK_FILTER_NAME = os.environ.get("SNZL_HOMEWORK_NAME", "").strip()
HOMEWORK_FILTER_NEXT = os.environ.get("SNZL_HOMEWORK_NEXT", "").strip().lower() in {"1", "true", "yes", "on"}
SUBMIT_DEBUG = os.environ.get("SNZL_SUBMIT_DEBUG", "true").strip().lower() not in {"0", "false", "no", "off"}

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

BASE_URL = "https://smartestu.cn"
SCHOOL_CODE = os.environ.get("SNZL_SCHOOL_CODE", "scnu").strip().lower() or "scnu"
COURSE_ID: int | None = None
LOGIN_PATH = "/api/auth/login"
COURSE_QUERY_PATH = "/api/homework/student/course/query"
HOMEWORK_QUERY_PATH = "/api/homework/student/mark/queryHomeworks"
QUESTION_PATH_TEMPLATE = "/api/homework/homework/{homework_id}/generated-questions"
EXERCISE_MARKS_PATH = "/api/homework/student/mark/queryExercisesByHomeworkId"
FILE_PRESIGN_BATCH_PATH = "/api/homework/files/presign/batch"
EXERCISE_SUBMIT_PATH = "/api/homework/student/exercise/submit"
HOMEWORK_COMPLETE_PATH = "/api/homework/student/homework/complete"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/assignment",
    "User-Agent": "Mozilla/5.0 (compatible; smartestu-openclaw-skill/2.0)",
}

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_DIR = SKILL_DIR / "Cache"
STATE_DIR = CACHE_DIR / "state"
IMAGE_DIR = CACHE_DIR / "images"
LOG_DIR = CACHE_DIR / "logs"
LAST_SESSION_PATH = STATE_DIR / "last_session.txt"

CN_NUMS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def ensure_cache_dirs() -> None:
    for path in [CACHE_DIR, STATE_DIR, IMAGE_DIR, LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def append_log(kind: str, payload: Dict[str, Any]) -> Path:
    ensure_cache_dirs()
    path = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
    entry = {"time": utc_now_iso(), "kind": kind, **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


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


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def summarize_text(text: str, limit: int = 60) -> str:
    text = strip_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


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

    def _request(self, method: str, path: str, payload: Dict[str, Any] | None = None, use_auth: bool = True, referer: str | None = None, extra_headers: Dict[str, str] | None = None, raw_bytes: bytes | None = None) -> Any:
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        if use_auth:
            if not self.token:
                raise RuntimeError("authentication required before calling this endpoint")
            headers["Authorization"] = f"Bearer {self.token}"
        data = raw_bytes
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url=f"{BASE_URL}{path}", data=data, headers=headers, method=method)
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

    def _request_url(self, method: str, url: str, raw_bytes: bytes | None = None, extra_headers: Dict[str, str] | None = None) -> Dict[str, Any]:
        headers = {"User-Agent": DEFAULT_HEADERS["User-Agent"]}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url=url, data=raw_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return {"ok": True, "status": getattr(resp, "status", 200), "body": body[:1000]}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http {exc.code} for upload url: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"upload request failed: {exc}") from exc

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
        return self._request("POST", COURSE_QUERY_PATH, payload={"studentId": self.school_user_id})

    def resolve_course_id(self) -> int:
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
            courses = courses_resp.get("data", [])
        if not isinstance(courses, list):
            raise RuntimeError(f"unexpected courses response: {json.dumps(courses_resp, ensure_ascii=False)}")

        if env_name:
            hits = [c for c in courses if env_name in str(c.get("name", ""))]
            if len(hits) == 1:
                return int(hits[0]["id"])
            if len(hits) > 1:
                choices = [{"id": c.get("id"), "name": c.get("name")} for c in hits]
                raise RuntimeError(f"SNZL_COURSE_NAME matched multiple courses: {choices}")

        if len(courses) == 1 and "id" in courses[0]:
            return int(courses[0]["id"])

        choices = [{"id": c.get("id"), "name": c.get("name"), "teacherName": c.get("teacherName")} for c in courses]
        raise RuntimeError("multiple courses found; set SNZL_COURSE_ID or SNZL_COURSE_NAME to choose one. " f"available: {choices}")

    def query_homeworks(self) -> Any:
        course_id = self.resolve_course_id()
        return self._request("POST", HOMEWORK_QUERY_PATH, payload={"studentId": self.school_user_id, "courseIds": [course_id]})

    def query_questions(self, homework_id: int) -> Any:
        raw = self._request("GET", QUESTION_PATH_TEMPLATE.format(homework_id=homework_id), payload=None)
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
        return self._request("POST", EXERCISE_MARKS_PATH, payload={"homeworkId": homework_id, "studentId": student_id or self.school_user_id})

    def presign_batch(self, original_names: list[str]) -> Any:
        return self._request("POST", FILE_PRESIGN_BATCH_PATH, payload={"files": [{"originalName": name} for name in original_names]})

    def upload_binary(self, put_url: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> Any:
        return self._request_url("PUT", put_url, raw_bytes=file_bytes, extra_headers={"Content-Type": content_type})

    def submit_exercise(self, exercise_id: int, answer_urls: list[str]) -> Any:
        return self._request("POST", EXERCISE_SUBMIT_PATH, payload={"exerciseId": exercise_id, "studentId": self.school_user_id, "answerUrl": answer_urls})

    def complete_homework(self, homework_id: int) -> Any:
        return self._request("POST", HOMEWORK_COMPLETE_PATH, payload={"homeworkId": homework_id, "studentId": self.school_user_id})


class SubmissionSessionManager:
    def __init__(self) -> None:
        ensure_cache_dirs()

    def _path(self, session_id: str) -> Path:
        return STATE_DIR / f"{session_id}.json"

    def save(self, session: Dict[str, Any]) -> Dict[str, Any]:
        ensure_cache_dirs()
        path = self._path(session["sessionId"])
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        LAST_SESSION_PATH.write_text(session["sessionId"], encoding="utf-8")
        return session

    def load(self, session_id: str | None = None) -> Dict[str, Any]:
        if not session_id or session_id == "last":
            if not LAST_SESSION_PATH.exists():
                raise RuntimeError("no submission session found")
            session_id = LAST_SESSION_PATH.read_text(encoding="utf-8").strip()
        path = self._path(session_id)
        if not path.exists():
            raise RuntimeError(f"submission session not found: {session_id}")
        return json.loads(path.read_text(encoding="utf-8"))


SESSION_MANAGER = SubmissionSessionManager()


def flatten_homeworks(compact_output: Dict[str, Any]) -> list[Dict[str, Any]]:
    rows = ((compact_output.get("data") or {}).get("courseHomeworkDTOList") or [])
    result: list[Dict[str, Any]] = []
    for row in rows:
        course_name = row.get("courseName")
        course_id = row.get("courseId")
        for hw in row.get("homeworks") or []:
            hw = dict(hw)
            hw["courseName"] = course_name
            hw["courseId"] = course_id
            result.append(hw)
    return result


def build_exercise_summary(exercise: Dict[str, Any], index: int) -> Dict[str, Any]:
    raw = exercise.get("questionMd") or exercise.get("questionText") or exercise.get("name") or ""
    subs = exercise.get("subQuestions") or []
    if not raw and subs:
        raw = " ".join(str(x.get("questionMd") or "") for x in subs)
    return {
        "index": index,
        "exerciseId": exercise.get("id"),
        "name": exercise.get("name") or f"第{index}题",
        "questionNum": exercise.get("questionNum") or index,
        "summary": summarize_text(str(raw), 80) or f"第{index}题",
        "rawQuestion": raw,
        "score": exercise.get("score"),
    }


def create_submission_session(client: SmartestuClient, homework_id: int | None = None, homework_name: str | None = None) -> Dict[str, Any]:
    raw_homeworks = client.query_homeworks()
    compact = compact_homeworks_output(raw_homeworks, include_details=True, homework_id=homework_id, homework_name=homework_name, next_pending=False)
    matches = flatten_homeworks(compact)
    if not matches:
        raise RuntimeError("no homework matched the given id/name")
    if len(matches) > 1:
        choices = [{"id": x.get("id"), "name": x.get("name"), "deadline": x.get("endTime")} for x in matches]
        raise RuntimeError(f"multiple homeworks matched; narrow it down. matches: {choices}")
    hw = matches[0]
    exercises = [build_exercise_summary(ex, i + 1) for i, ex in enumerate(hw.get("exercises") or [])]
    if not exercises:
        raise RuntimeError("the homework payload did not include exercises; cannot build a safe submission plan")

    session_id = f"snzl-submit-{hw.get('id')}-{timestamp_slug()}"
    session = {
        "sessionId": session_id,
        "createdAt": utc_now_iso(),
        "updatedAt": utc_now_iso(),
        "debug": SUBMIT_DEBUG,
        "status": "collecting_images",
        "studentId": client.school_user_id,
        "course": {"id": hw.get("courseId"), "name": hw.get("courseName")},
        "homework": {
            "id": hw.get("id"),
            "name": hw.get("name"),
            "deadline": hw.get("endTime"),
            "startTime": hw.get("startTime"),
            "totalScore": hw.get("totalScore"),
            "submission_status": hw.get("submission_status"),
            "review_status": hw.get("review_status"),
            "allowCorrection": hw.get("allowCorrection"),
            "enableResubmit": hw.get("enableResubmit"),
            "resubmitTimes": hw.get("resubmitTimes"),
            "exerciseCount": len(exercises),
        },
        "images": [],
        "exercises": exercises,
        "mapping": [],
        "plan": None,
        "confirmToken": None,
    }
    append_log("submission.session.created", {"sessionId": session_id, "homeworkId": hw.get("id"), "homeworkName": hw.get("name"), "debug": SUBMIT_DEBUG})
    return SESSION_MANAGER.save(session)


def image_label(index: int) -> str:
    if 0 <= index < len(CN_NUMS):
        return f"图{CN_NUMS[index]}"
    return f"图{index}"


def image_slot(index: int) -> str:
    return f"p{index}"


def normalize_image_ref(ref: str) -> str:
    ref = ref.strip()
    if not ref:
        raise RuntimeError("empty image ref")
    m = re.fullmatch(r"p(\d+)", ref, flags=re.I)
    if m:
        return f"p{int(m.group(1))}"
    m = re.fullmatch(r"图([一二三四五六七八九十0-9]+)", ref)
    if not m:
        raise RuntimeError(f"invalid image ref: {ref}")
    token = m.group(1)
    cn_map = {k: i for i, k in enumerate(CN_NUMS) if i > 0}
    idx = int(token) if token.isdigit() else cn_map.get(token)
    if not idx:
        raise RuntimeError(f"unsupported image ref: {ref}")
    return f"p{idx}"


def copy_image_into_cache(session_id: str, source_path: str, index: int) -> Dict[str, Any]:
    src = Path(source_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise RuntimeError(f"image file not found: {src}")
    ensure_cache_dirs()
    ext = src.suffix.lower() or ".bin"
    session_dir = IMAGE_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    dst = session_dir / f"{image_slot(index)}{ext}"
    shutil.copy2(src, dst)
    return {
        "sourcePath": str(src),
        "cachedPath": str(dst),
        "size": dst.stat().st_size,
        "sha1": hashlib.sha1(dst.read_bytes()).hexdigest(),
        "originalName": src.name,
        "ext": ext,
    }


def add_image_to_session(session_id: str | None, source_path: str) -> Dict[str, Any]:
    session = SESSION_MANAGER.load(session_id)
    index = len(session.get("images") or []) + 1
    copied = copy_image_into_cache(session["sessionId"], source_path, index)
    record = {
        "index": index,
        "alias": image_label(index),
        "slot": image_slot(index),
        **copied,
        "addedAt": utc_now_iso(),
    }
    session.setdefault("images", []).append(record)
    session["updatedAt"] = utc_now_iso()
    append_log("submission.image.added", {"sessionId": session["sessionId"], "alias": record["alias"], "cachedPath": record["cachedPath"], "sourcePath": source_path})
    return SESSION_MANAGER.save(session)


def parse_mapping_string(mapping_text: str) -> list[Dict[str, Any]]:
    """Legacy deterministic parser.

    Prefer model-built structured mapping via --mapping-json.
    This fallback only accepts already-normalized text such as:
    1:图一,图二;2:图三
    """
    if not mapping_text.strip():
        raise RuntimeError("mapping text is empty")
    mapping: list[Dict[str, Any]] = []
    for part in re.split(r"[;；\n]+", mapping_text.strip()):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            left, right = part.split(":", 1)
        elif "：" in part:
            left, right = part.split("：", 1)
        else:
            raise RuntimeError(f"invalid normalized mapping segment: {part}")
        exercise_idx_text = re.sub(r"[^0-9]", "", left)
        if not exercise_idx_text:
            raise RuntimeError(f"exercise index missing in: {part}")
        exercise_index = int(exercise_idx_text)
        aliases = re.findall(r"图[一二三四五六七八九十0-9]+", right)
        if not aliases:
            raise RuntimeError(f"image alias missing in: {part}")
        mapping.append({"exerciseIndex": exercise_index, "imageAliases": aliases})
    return mapping


def parse_mapping_json(mapping_json_text: str) -> list[Dict[str, Any]]:
    if not mapping_json_text.strip():
        raise RuntimeError("mapping json is empty")
    try:
        data = json.loads(mapping_json_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid mapping json: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise RuntimeError("mapping json must be a non-empty list")
    mapping: list[Dict[str, Any]] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"mapping item #{idx} must be an object")
        exercise_index = item.get("exerciseIndex")
        image_aliases = item.get("imageAliases")
        if not isinstance(exercise_index, int):
            raise RuntimeError(f"mapping item #{idx} missing integer exerciseIndex")
        if not isinstance(image_aliases, list) or not image_aliases or not all(isinstance(x, str) and x.strip() for x in image_aliases):
            raise RuntimeError(f"mapping item #{idx} missing non-empty imageAliases")
        normalized_aliases = [x.strip() for x in image_aliases]
        mapping.append({
            "exerciseIndex": exercise_index,
            "imageAliases": normalized_aliases,
            "exerciseLabel": item.get("exerciseLabel"),
            "platformQuestionNum": item.get("platformQuestionNum"),
            "reason": item.get("reason"),
        })
    return mapping


def build_submission_plan(session_id: str | None, mapping_text: str | None = None, mapping_json_text: str | None = None, mapping_source_text: str | None = None) -> Dict[str, Any]:
    session = SESSION_MANAGER.load(session_id)
    if mapping_json_text:
        mapping_input = parse_mapping_json(mapping_json_text)
        parse_mode = "model-json"
    elif mapping_text:
        mapping_input = parse_mapping_string(mapping_text)
        parse_mode = "normalized-text"
    else:
        raise RuntimeError("either mapping_text or mapping_json_text is required")
    images = session.get("images") or []
    image_by_alias = {}
    for img in images:
        image_by_alias[img["alias"]] = img
        image_by_alias[img["slot"]] = img
    exercises = session.get("exercises") or []
    plan_items = []
    command_steps = []
    used_aliases: list[str] = []

    for item in mapping_input:
        exercise_index = item["exerciseIndex"]
        if exercise_index < 1 or exercise_index > len(exercises):
            raise RuntimeError(f"exercise index out of range: {exercise_index}")
        exercise = exercises[exercise_index - 1]
        selected_images = []
        for alias in item["imageAliases"]:
            normalized_ref = normalize_image_ref(alias)
            image = image_by_alias.get(normalized_ref)
            if not image:
                raise RuntimeError(f"image not found in session: {normalized_ref}")
            selected_images.append(image)
            used_aliases.append(image["slot"])
        plan_items.append(
            {
                "exerciseIndex": exercise_index,
                "exerciseId": exercise["exerciseId"],
                "exerciseName": exercise["name"],
                "platformQuestionNum": exercise.get("questionNum"),
                "questionSummary": exercise["summary"],
                "exerciseLabel": item.get("exerciseLabel"),
                "modelReason": item.get("reason"),
                "imageAliases": [img["alias"] for img in selected_images],
                "imageSlots": [img["slot"] for img in selected_images],
                "imagePaths": [img["cachedPath"] for img in selected_images],
            }
        )
        command_steps.append(
            {
                "step": "submit-exercise",
                "exerciseId": exercise["exerciseId"],
                "answerImages": [img["cachedPath"] for img in selected_images],
            }
        )

    confirm_token = hashlib.sha1(f"{session['sessionId']}|{mapping_text}".encode("utf-8")).hexdigest()[:10].upper()
    shell_lines = [
        "# Preview only. DO NOT run blindly.",
        f"$env:SNZL_SUBMIT_DEBUG={'true' if session.get('debug', True) else 'false'}",
        f"python scripts/smartestu_api.py submit-run --session-id {session['sessionId']} --confirm {confirm_token}",
    ]
    plan = {
        "builtAt": utc_now_iso(),
        "confirmToken": confirm_token,
        "parseMode": parse_mode,
        "mappingSourceText": mapping_source_text,
        "mapping": plan_items,
        "unusedImages": [img["alias"] for img in images if img["slot"] not in used_aliases],
        "commandPreview": shell_lines,
    }
    session["mapping"] = mapping_input
    session["plan"] = plan
    session["confirmToken"] = confirm_token
    session["status"] = "awaiting_confirmation"
    session["updatedAt"] = utc_now_iso()
    append_log("submission.plan.built", {"sessionId": session["sessionId"], "confirmToken": confirm_token, "mapping": plan_items})
    return SESSION_MANAGER.save(session)


def presign_name_for_image(image_path: str, alias: str) -> str:
    src = Path(image_path)
    ext = src.suffix.lower() or ".jpg"
    digest = hashlib.md5((alias + src.name + str(src.stat().st_size)).encode("utf-8")).hexdigest()[:8]
    return f"{int(time.time() * 1000)}-{digest}{ext}"


def run_submission(session_id: str | None, confirm_token: str, allow_live: bool = False) -> Dict[str, Any]:
    session = SESSION_MANAGER.load(session_id)
    expected = session.get("confirmToken")
    if not expected:
        raise RuntimeError("no pending plan; build a submission plan first")
    if confirm_token != expected:
        raise RuntimeError("confirm token mismatch; refuse to submit")

    debug = bool(session.get("debug", True))
    if debug and allow_live:
        raise RuntimeError("debug session cannot be forced live")

    plan = session.get("plan") or {}
    mapping = plan.get("mapping") or []
    results = []

    if debug:
        for item in mapping:
            simulated_urls = []
            for slot in item.get("imageSlots") or []:
                simulated_urls.append(f"debug://{session['sessionId']}/{slot}")
            results.append(
                {
                    "exerciseId": item["exerciseId"],
                    "exerciseName": item["exerciseName"],
                    "simulatedAnswerUrls": simulated_urls,
                    "submitResponse": {"code": 200, "msg": "DEBUG: simulated exercise submit", "success": True},
                }
            )
        complete_response = {"code": 200, "msg": "DEBUG: simulated homework complete", "success": True}
    else:
        client = SmartestuClient()
        client.login()
        for item in mapping:
            presign_names = [presign_name_for_image(path, alias) for path, alias in zip(item.get("imagePaths") or [], item.get("imageAliases") or [])]
            presign_resp = client.presign_batch(presign_names)
            data = (presign_resp or {}).get("data") or []
            if len(data) != len(item.get("imagePaths") or []):
                raise RuntimeError(f"presign count mismatch for exercise {item['exerciseId']}")
            answer_urls = []
            upload_rows = []
            for image_path, upload_info in zip(item.get("imagePaths") or [], data):
                file_bytes = Path(image_path).read_bytes()
                client.upload_binary(upload_info["putUrl"], file_bytes)
                answer_urls.append(upload_info["url"])
                upload_rows.append({"path": image_path, "url": upload_info["url"]})
            submit_resp = client.submit_exercise(item["exerciseId"], answer_urls)
            results.append({"exerciseId": item["exerciseId"], "exerciseName": item["exerciseName"], "uploads": upload_rows, "submitResponse": submit_resp})
        complete_response = client.complete_homework(session["homework"]["id"])

    session["status"] = "submitted_debug" if debug else "submitted_live"
    session["submittedAt"] = utc_now_iso()
    session["runResult"] = {
        "debug": debug,
        "results": results,
        "completeResponse": complete_response,
    }
    session["updatedAt"] = utc_now_iso()
    append_log("submission.run", {"sessionId": session["sessionId"], "debug": debug, "resultCount": len(results), "complete": complete_response})
    return SESSION_MANAGER.save(session)


def render_submission_preview(session: Dict[str, Any]) -> Dict[str, Any]:
    plan = session.get("plan") or {}
    homework = session.get("homework") or {}
    lines = [
        f"这是即将提交的题目：{homework.get('name')}",
        f"作业ID：{homework.get('id')}",
        f"截止时间：{homework.get('deadline') or '未知'}",
        f"题目数量：{homework.get('exerciseCount') or len(session.get('exercises') or [])}",
    ]
    if plan.get("mappingSourceText"):
        lines.append(f"你的原始分配：{plan['mappingSourceText']}")
    for item in plan.get("mapping") or []:
        lines.append(
            f"第{item['exerciseIndex']}项（平台题号 {item.get('platformQuestionNum') or '未知'}，{item['exerciseName']}）：{item['questionSummary']}"
        )
        lines.append(f"提交图片：{'、'.join(item['imageAliases'])}")
        if item.get("modelReason"):
            lines.append(f"理解依据：{item['modelReason']}")
    if plan.get("unusedImages"):
        lines.append(f"未使用图片：{'、'.join(plan['unusedImages'])}")
    lines.append("是否确认提交？")
    return {
        "sessionId": session.get("sessionId"),
        "confirmToken": session.get("confirmToken"),
        "debug": session.get("debug", True),
        "parseMode": plan.get("parseMode"),
        "mappingSourceText": plan.get("mappingSourceText"),
        "previewText": "\n".join(lines),
        "commandPreview": plan.get("commandPreview") or [],
        "mapping": plan.get("mapping") or [],
    }


def parse_args() -> argparse.Namespace:
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

    si = sub.add_parser("submit-init", help="create a safe submission session for one homework")
    si.add_argument("--homework-id", type=int, help="target homework id")
    si.add_argument("--name", dest="homework_name", help="target homework name keyword")

    sa = sub.add_parser("submit-add-image", help="copy one user image into Cache and assign 图一/图二 aliases")
    sa.add_argument("--session-id", default="last", help="submission session id or 'last'")
    sa.add_argument("--source", required=True, help="absolute path to the image file")

    sp = sub.add_parser("submit-plan", help="build a preview plan from model-produced mapping")
    sp.add_argument("--session-id", default="last", help="submission session id or 'last'")
    sp.add_argument("--mapping", help="normalized mapping text like '1:图一,图二;2:图三' (legacy fallback)")
    sp.add_argument("--mapping-json", help="preferred structured mapping JSON produced by the model")
    sp.add_argument("--mapping-source-text", help="original user natural-language mapping text for preview display")

    ss = sub.add_parser("submit-show", help="show the current session/plan preview")
    ss.add_argument("--session-id", default="last", help="submission session id or 'last'")

    sr = sub.add_parser("submit-run", help="run the current plan only after explicit confirmation token matches")
    sr.add_argument("--session-id", default="last", help="submission session id or 'last'")
    sr.add_argument("--confirm", required=True, help="confirmation token returned by submit-plan")
    sr.add_argument("--live", action="store_true", help="actually send requests when debug is disabled")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.command in {"submit-add-image", "submit-plan", "submit-show", "submit-run"}:
            if args.command == "submit-add-image":
                output = add_image_to_session(args.session_id, args.source)
            elif args.command == "submit-plan":
                session = build_submission_plan(
                    args.session_id,
                    mapping_text=args.mapping,
                    mapping_json_text=args.mapping_json,
                    mapping_source_text=args.mapping_source_text,
                )
                output = render_submission_preview(session)
            elif args.command == "submit-show":
                session = SESSION_MANAGER.load(args.session_id)
                output = render_submission_preview(session) if session.get("plan") else session
            elif args.command == "submit-run":
                session = run_submission(args.session_id, args.confirm, allow_live=args.live)
                output = session.get("runResult") or {}
            else:
                raise RuntimeError(f"unsupported submit command: {args.command}")
            print(json.dumps({"ok": True, "data": clean_payload(output)}, ensure_ascii=False, indent=2))
            return 0

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
        elif args.command == "submit-init":
            output = create_submission_session(client, homework_id=args.homework_id, homework_name=args.homework_name)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
    except Exception as exc:
        append_log("error", {"command": args.command, "error": str(exc)})
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    include_details = bool(getattr(args, "detail", False)) or DETAIL_MODE == "detail"
    env_homework_id = int(HOMEWORK_FILTER_ID) if HOMEWORK_FILTER_ID.isdigit() else None
    cli_homework_id = getattr(args, "homework_id", None) if args.command == "homeworks" else None
    effective_homework_id = cli_homework_id or env_homework_id
    effective_homework_name = getattr(args, "homework_name", None) or HOMEWORK_FILTER_NAME or None
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
