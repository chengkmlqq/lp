#!/usr/bin/env python3
"""
fquiz 需求分析 API 适配脚本（仅负责接口调用，不负责方案生成）。

支持动作：
- query          查询需求列表（支持状态过滤与处理顺序排序）
- get            查询单条需求详情
- lifecycle      查询单条需求生命周期
- analyze        提交单条分析回写
- batch-analyze  批量提交分析回写
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib import error, parse, request

DEFAULT_BASE_URL = "https://www.quizck.cn"
DEFAULT_USER_ID = "openclaw"
DEFAULT_USER_PWD = "12345678"
DEFAULT_PROJECT_NAME = "fquiz"
DEFAULT_STATUSES = ["PENDING_ANALYSIS", "PENDING_REVISION"]
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_ITEMS = 100


def print_json(data: Dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    raise SystemExit(exit_code)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_base_url(raw: str) -> str:
    value = normalize_text(raw)
    if not value:
        raise ValueError("base-url 不能为空")
    return value.rstrip("/")


def read_text_file(path: str, *, field_name: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise ValueError(f"{field_name} 读取失败: {e}") from e

    if not normalize_text(text):
        raise ValueError(f"{field_name} 内容不能为空")
    return text


def validate_progress(progress_percent: Optional[int]) -> None:
    if progress_percent is None:
        return
    if progress_percent < 0 or progress_percent > 100:
        raise ValueError("progress-percent 必须在 0-100 之间")


def parse_statuses(status_args: Optional[Sequence[str]]) -> List[str]:
    if not status_args:
        return list(DEFAULT_STATUSES)

    result: List[str] = []
    seen = set()
    for item in status_args:
        for part in (item or "").split(","):
            s = part.strip().upper()
            if not s:
                continue
            if s not in seen:
                seen.add(s)
                result.append(s)

    if not result:
        raise ValueError("status 不能为空")
    return result


def normalize_priority(value: Any) -> str:
    raw = normalize_text(value).upper()
    if raw in {"HIGH", "MEDIUM", "LOW"}:
        return raw
    return raw or "UNKNOWN"


def priority_rank(priority: str) -> int:
    rank_map = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return rank_map.get(priority, 99)


def create_date_sort_key(requirement: Dict[str, Any]) -> str:
    for field in ("createDate", "createdDate", "createTime", "createdTime", "gmtCreate"):
        value = normalize_text(requirement.get(field))
        if value:
            return value
    return ""


def sort_requirements_for_processing(queried: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        queried,
        key=lambda req: (
            priority_rank(normalize_priority(req.get("priority"))),
            create_date_sort_key(req),
            normalize_text(req.get("id")),
        ),
    )


def extract_data_body(body: Any) -> Any:
    if isinstance(body, dict) and "data" in body and body.get("data") is not None:
        return body.get("data")
    return body


def http_json(
    opener: request.OpenerDirector,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if json_body is not None:
        req_headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")

    req = request.Request(url=url, data=body_bytes, headers=req_headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    return {"status": resp.status, "body": json.loads(raw)}
                except json.JSONDecodeError:
                    return {"status": resp.status, "body": raw}
            return {"status": resp.status, "body": raw}
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        err_body: Any = raw
        try:
            err_body = json.loads(raw)
        except Exception:
            pass
        return {"status": e.code, "body": err_body, "http_error": True}


def ensure_2xx(step: str, resp: Dict[str, Any], error_msg: str) -> Any:
    status = int(resp.get("status", 0) or 0)
    if 200 <= status < 300:
        return extract_data_body(resp.get("body"))

    print_json(
        {
            "ok": False,
            "step": step,
            "status": status,
            "error": error_msg,
            "details": resp.get("body"),
        },
        exit_code=1,
    )


def login_and_get_token(
    opener: request.OpenerDirector,
    *,
    base_url: str,
    user_id: str,
    user_pwd: str,
    timeout: int,
) -> str:
    login_url = f"{base_url}/api/user/login"
    login_result = http_json(
        opener,
        "POST",
        login_url,
        json_body={"userId": user_id, "userPwd": user_pwd},
        timeout=timeout,
    )
    ensure_2xx("login", login_result, "登录失败（账号/密码或服务异常）")

    jwt_url = f"{base_url}/api/jwt/generate?userId={parse.quote(user_id)}"
    jwt_result = http_json(opener, "POST", jwt_url, timeout=timeout)
    token_body = ensure_2xx("jwt", jwt_result, "JWT 生成失败（会话或接口异常）")

    token = normalize_text(token_body)
    if not token:
        print_json(
            {
                "ok": False,
                "step": "jwt",
                "status": jwt_result.get("status"),
                "error": "JWT 生成失败：返回 token 为空",
            },
            exit_code=1,
        )
    return token


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def fetch_requirement_detail(
    opener: request.OpenerDirector,
    *,
    base_url: str,
    token: str,
    requirement_id: str,
    timeout: int,
) -> Dict[str, Any]:
    url = f"{base_url}/api/project/requirement/get/{parse.quote(requirement_id)}"
    resp = http_json(opener, "GET", url, headers=auth_headers(token), timeout=timeout)
    body = ensure_2xx("get", resp, "查询需求详情失败")
    if not isinstance(body, dict):
        print_json(
            {
                "ok": False,
                "step": "get",
                "status": resp.get("status"),
                "error": "需求详情返回格式异常",
                "details": body,
            },
            exit_code=1,
        )
    return body


def fetch_lifecycle(
    opener: request.OpenerDirector,
    *,
    base_url: str,
    token: str,
    requirement_id: str,
    timeout: int,
) -> List[Dict[str, Any]]:
    url = f"{base_url}/api/project/requirement/{parse.quote(requirement_id)}/lifecycle"
    resp = http_json(opener, "GET", url, headers=auth_headers(token), timeout=timeout)
    body = ensure_2xx("lifecycle", resp, "查询需求生命周期失败")
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    return []


def query_requirements_by_status(
    opener: request.OpenerDirector,
    *,
    base_url: str,
    token: str,
    project_name: str,
    statuses: Sequence[str],
    page_size: int,
    max_items: int,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    url = f"{base_url}/api/project/requirement/search"
    merged: List[Dict[str, Any]] = []
    seen_ids = set()
    query_trace: List[Dict[str, Any]] = []

    for status in statuses:
        page_num = 1
        while True:
            payload = {
                "projectName": project_name,
                "status": status,
                "pageNum": page_num,
                "pageSize": page_size,
            }
            resp = http_json(
                opener,
                "POST",
                url,
                headers=auth_headers(token),
                json_body=payload,
                timeout=timeout,
            )
            page_body = ensure_2xx("query", resp, "查询需求列表失败")
            if not isinstance(page_body, dict):
                print_json(
                    {
                        "ok": False,
                        "step": "query",
                        "status": resp.get("status"),
                        "error": "需求查询返回格式异常",
                        "details": page_body,
                    },
                    exit_code=1,
                )

            content = page_body.get("content")
            if not isinstance(content, list):
                content = []

            query_trace.append(
                {
                    "status": status,
                    "pageNum": page_num,
                    "returned": len(content),
                    "totalElements": page_body.get("totalElements"),
                    "totalPages": page_body.get("totalPages"),
                }
            )

            for item in content:
                if not isinstance(item, dict):
                    continue
                rid = normalize_text(item.get("id"))
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                merged.append(item)
                if len(merged) >= max_items:
                    return merged, query_trace

            total_pages = page_body.get("totalPages")
            if not content:
                break
            if isinstance(total_pages, int) and total_pages > 0 and page_num >= total_pages:
                break
            if len(content) < page_size:
                break
            page_num += 1

    return merged, query_trace


def extract_latest_review_remark(logs: Sequence[Dict[str, Any]]) -> str:
    review_logs = [x for x in logs if normalize_text(x.get("eventType")).upper() == "REVIEW"]
    if not review_logs:
        return ""
    latest = review_logs[-1]
    return normalize_text(latest.get("remark"))


def summarize_requirement_item(requirement: Dict[str, Any], process_order: int) -> Dict[str, Any]:
    return {
        "processOrder": process_order,
        "requirementId": normalize_text(requirement.get("id")),
        "title": normalize_text(requirement.get("title")),
        "status": normalize_text(requirement.get("status")).upper(),
        "priority": normalize_priority(requirement.get("priority")),
        "projectName": normalize_text(requirement.get("projectName")),
        "createDate": create_date_sort_key(requirement),
        "descr": normalize_text(requirement.get("descr")),
        "resultMsg": normalize_text(requirement.get("resultMsg")),
    }


def analyze_requirement(
    opener: request.OpenerDirector,
    *,
    base_url: str,
    token: str,
    requirement_id: str,
    descr: str,
    progress_percent: Optional[int],
    timeout: int,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"descr": descr}
    if progress_percent is not None:
        payload["progressPercent"] = progress_percent

    url = f"{base_url}/api/project/requirement/{parse.quote(requirement_id)}/analyze"
    resp = http_json(
        opener,
        "POST",
        url,
        headers=auth_headers(token),
        json_body=payload,
        timeout=timeout,
    )
    body = ensure_2xx("analyze", resp, "需求分析调用失败")
    return {
        "status": resp.get("status"),
        "payload": payload,
        "result": body,
    }


def parse_batch_items(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if args.batch_file and args.batch_json:
        raise ValueError("batch-file 与 batch-json 只能二选一")
    if not args.batch_file and not args.batch_json:
        raise ValueError("batch-analyze 需要提供 batch-file 或 batch-json")

    raw: Any
    if args.batch_file:
        try:
            with open(args.batch_file, "r", encoding=args.batch_file_encoding or "utf-8") as f:
                raw = json.load(f)
        except OSError as e:
            raise ValueError(f"batch-file 读取失败: {e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"batch-file JSON 解析失败: {e}") from e
    else:
        raw = json.loads(args.batch_json)

    if not isinstance(raw, list):
        raise ValueError("批量输入必须是 JSON 数组")

    items: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx} 项不是对象")
        rid = normalize_text(item.get("requirementId") or item.get("id"))
        descr = normalize_text(item.get("descr"))
        progress = item.get("progressPercent")
        if progress is not None and not isinstance(progress, int):
            raise ValueError(f"第 {idx} 项 progressPercent 必须是整数")
        validate_progress(progress)
        if not rid:
            raise ValueError(f"第 {idx} 项 requirementId 不能为空")
        if not descr:
            raise ValueError(f"第 {idx} 项 descr 不能为空")
        items.append(
            {
                "requirementId": rid,
                "descr": descr,
                "progressPercent": progress,
            }
        )
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="fquiz 需求分析 API 适配脚本（仅负责接口调用，不负责方案生成）",
    )

    parser.add_argument(
        "--action",
        required=True,
        choices=["query", "get", "lifecycle", "analyze", "batch-analyze"],
        help="执行动作",
    )

    # 通用鉴权参数
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="服务地址，默认 https://www.quizck.cn")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="登录账号，默认 openclaw")
    parser.add_argument("--user-pwd", default=DEFAULT_USER_PWD, help="登录密码，默认 12345678")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 超时秒数，默认 15")

    # query 参数
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME, help="项目名过滤，默认 fquiz")
    parser.add_argument(
        "--status",
        action="append",
        help="查询状态（可重复或逗号分隔），默认 PENDING_ANALYSIS,PENDING_REVISION",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help=f"查询分页大小，默认 {DEFAULT_PAGE_SIZE}")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS, help=f"批量最大处理数，默认 {DEFAULT_MAX_ITEMS}")
    parser.add_argument("--with-review-remark", action="store_true", help="query 时对 PENDING_REVISION 附加拉取评审备注")

    # 单条参数
    parser.add_argument("--requirement-id", help="需求 ID（get/lifecycle/analyze 必填）")
    parser.add_argument("--with-lifecycle", action="store_true", help="get 时附带返回生命周期")

    # analyze 参数
    parser.add_argument("--descr", help="回写分析描述（analyze 必填）")
    parser.add_argument("--descr-file", help="回写分析描述文件路径（UTF-8 文本，analyze 可用，和 --descr 二选一）")
    parser.add_argument("--progress-percent", type=int, default=None, help="进度百分比（0-100，可选）")

    # batch-analyze 参数
    parser.add_argument("--batch-file", help="批量回写输入文件（JSON 数组）")
    parser.add_argument("--batch-json", help="批量回写输入 JSON 字符串（JSON 数组）")
    parser.add_argument("--batch-file-encoding", default="utf-8", help="batch-file 文件编码，默认 utf-8")

    parser.add_argument("--dry-run", action="store_true", help="仅参数校验并输出执行计划，不发起真实请求")
    return parser


def validate_args(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        action = normalize_text(args.action)
        base_url = normalize_base_url(args.base_url)
        user_id = normalize_text(args.user_id)
        user_pwd = args.user_pwd or ""
        requirement_id = normalize_text(args.requirement_id)
        descr = normalize_text(args.descr)
        descr_file = normalize_text(args.descr_file)
        if descr and descr_file:
            raise ValueError("analyze 模式下 descr 与 descr-file 只能二选一")
        if descr_file:
            descr = read_text_file(descr_file, field_name="descr-file")
        project_name = normalize_text(args.project_name) or DEFAULT_PROJECT_NAME
        statuses = parse_statuses(args.status)

        if not user_id:
            raise ValueError("user-id 不能为空")
        if not user_pwd:
            raise ValueError("user-pwd 不能为空")
        if args.timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if args.page_size <= 0:
            raise ValueError("page-size 必须大于 0")
        if args.max_items <= 0:
            raise ValueError("max-items 必须大于 0")

        validate_progress(args.progress_percent)

        if action in {"get", "lifecycle", "analyze"} and not requirement_id:
            raise ValueError(f"action={action} 时 requirement-id 不能为空")
        if action == "analyze" and not descr:
            raise ValueError("action=analyze 时 descr 不能为空")
        if action == "batch-analyze":
            # 仅校验格式，不触发网络调用
            parse_batch_items(args)

        return {
            "action": action,
            "base_url": base_url,
            "user_id": user_id,
            "user_pwd": user_pwd,
            "requirement_id": requirement_id,
            "descr": descr,
            "project_name": project_name,
            "statuses": statuses,
        }
    except (ValueError, json.JSONDecodeError) as ve:
        print_json(
            {
                "ok": False,
                "step": "validate",
                "error": str(ve),
            },
            exit_code=2,
        )


def dry_run_output(args: argparse.Namespace, cfg: Dict[str, Any]) -> None:
    endpoints = {
        "login": "/api/user/login",
        "jwt": f"/api/jwt/generate?userId={parse.quote(cfg['user_id'])}",
        "search": "/api/project/requirement/search",
        "get": "/api/project/requirement/get/{id}",
        "lifecycle": "/api/project/requirement/{id}/lifecycle",
        "analyze": "/api/project/requirement/{id}/analyze",
    }

    plans = {
        "query": [
            "1) login",
            "2) jwt",
            "3) search 按状态分页查询",
            "4) 按优先级与创建时间排序输出",
            "5) 可选：PENDING_REVISION 拉取 lifecycle REVIEW remark",
        ],
        "get": ["1) login", "2) jwt", "3) get 读取需求详情", "4) 可选返回 lifecycle"],
        "lifecycle": ["1) login", "2) jwt", "3) lifecycle 读取需求生命周期"],
        "analyze": ["1) login", "2) jwt", "3) analyze 回写 descr/progressPercent"],
        "batch-analyze": ["1) login", "2) jwt", "3) 逐条 analyze 回写（按输入顺序）"],
    }

    print_json(
        {
            "ok": True,
            "dryRun": True,
            "action": cfg["action"],
            "plan": {
                "baseUrl": cfg["base_url"],
                "userId": cfg["user_id"],
                "projectName": cfg["project_name"],
                "statuses": cfg["statuses"],
                "requirementId": cfg["requirement_id"] or None,
                "withReviewRemark": bool(args.with_review_remark),
                "withLifecycle": bool(args.with_lifecycle),
                "endpoints": endpoints,
                "steps": plans[cfg["action"]],
                "progressPercent": args.progress_percent,
                "hasDescr": bool(cfg["descr"]),
            },
        }
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    cfg = validate_args(args)

    if args.dry_run:
        dry_run_output(args, cfg)

    opener = request.build_opener(request.HTTPCookieProcessor())
    token = login_and_get_token(
        opener,
        base_url=cfg["base_url"],
        user_id=cfg["user_id"],
        user_pwd=cfg["user_pwd"],
        timeout=args.timeout,
    )

    action = cfg["action"]

    if action == "query":
        queried, query_trace = query_requirements_by_status(
            opener,
            base_url=cfg["base_url"],
            token=token,
            project_name=cfg["project_name"],
            statuses=cfg["statuses"],
            page_size=args.page_size,
            max_items=args.max_items,
            timeout=args.timeout,
        )
        sorted_items = sort_requirements_for_processing(queried)

        status_count: Dict[str, int] = {}
        items: List[Dict[str, Any]] = []

        for idx, req in enumerate(sorted_items, start=1):
            item = summarize_requirement_item(req, process_order=idx)
            status = item["status"] or "UNKNOWN"
            status_count[status] = status_count.get(status, 0) + 1

            if args.with_review_remark and status == "PENDING_REVISION":
                logs = fetch_lifecycle(
                    opener,
                    base_url=cfg["base_url"],
                    token=token,
                    requirement_id=item["requirementId"],
                    timeout=args.timeout,
                )
                item["reviewRemarkSources"] = [
                    "requirement.resultMsg",
                    "lifecycle.REVIEW.remark",
                ]
                item["reviewRemark"] = "\n".join(
                    [x for x in [item.get("resultMsg"), extract_latest_review_remark(logs)] if normalize_text(x)]
                )

            items.append(item)

        print_json(
            {
                "ok": True,
                "action": "query",
                "projectName": cfg["project_name"],
                "statuses": cfg["statuses"],
                "count": len(items),
                "statusCount": status_count,
                "processingOrderRule": "priority(HIGH>MEDIUM>LOW) then createDate then id",
                "queryTrace": query_trace,
                "items": items,
            }
        )

    if action == "get":
        detail = fetch_requirement_detail(
            opener,
            base_url=cfg["base_url"],
            token=token,
            requirement_id=cfg["requirement_id"],
            timeout=args.timeout,
        )
        result: Dict[str, Any] = {
            "ok": True,
            "action": "get",
            "requirement": detail,
        }
        if args.with_lifecycle:
            result["lifecycle"] = fetch_lifecycle(
                opener,
                base_url=cfg["base_url"],
                token=token,
                requirement_id=cfg["requirement_id"],
                timeout=args.timeout,
            )
        print_json(result)

    if action == "lifecycle":
        logs = fetch_lifecycle(
            opener,
            base_url=cfg["base_url"],
            token=token,
            requirement_id=cfg["requirement_id"],
            timeout=args.timeout,
        )
        print_json(
            {
                "ok": True,
                "action": "lifecycle",
                "requirementId": cfg["requirement_id"],
                "count": len(logs),
                "logs": logs,
            }
        )

    if action == "analyze":
        result = analyze_requirement(
            opener,
            base_url=cfg["base_url"],
            token=token,
            requirement_id=cfg["requirement_id"],
            descr=cfg["descr"],
            progress_percent=args.progress_percent,
            timeout=args.timeout,
        )
        status_after = ""
        if isinstance(result.get("result"), dict):
            status_after = normalize_text(result["result"].get("status"))

        print_json(
            {
                "ok": True,
                "action": "analyze",
                "requirementId": cfg["requirement_id"],
                "writebackSuccess": True,
                "statusAfterWriteback": status_after,
                **result,
            }
        )

    if action == "batch-analyze":
        batch_items = parse_batch_items(args)
        results: List[Dict[str, Any]] = []
        success = 0

        for idx, item in enumerate(batch_items, start=1):
            rid = item["requirementId"]
            payload: Dict[str, Any] = {"descr": item["descr"]}
            if item.get("progressPercent") is not None:
                payload["progressPercent"] = item["progressPercent"]

            url = f"{cfg['base_url']}/api/project/requirement/{parse.quote(rid)}/analyze"
            resp = http_json(
                opener,
                "POST",
                url,
                headers=auth_headers(token),
                json_body=payload,
                timeout=args.timeout,
            )

            status_code = int(resp.get("status", 0) or 0)
            body = extract_data_body(resp.get("body"))
            ok = 200 <= status_code < 300

            status_after = ""
            if isinstance(body, dict):
                status_after = normalize_text(body.get("status"))

            results.append(
                {
                    "order": idx,
                    "requirementId": rid,
                    "writebackSuccess": ok,
                    "statusCode": status_code,
                    "statusAfterWriteback": status_after,
                    "failureReason": None if ok else "analyze 接口调用失败",
                    "payload": payload,
                    "result": body,
                }
            )
            if ok:
                success += 1

        failed = len(results) - success
        print_json(
            {
                "ok": failed == 0,
                "action": "batch-analyze",
                "total": len(results),
                "success": success,
                "failed": failed,
                "items": results,
            },
            exit_code=0 if failed == 0 else 1,
        )


if __name__ == "__main__":
    main()
