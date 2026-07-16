from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TopicRule:
    any_permission_codes: set[str] = field(default_factory=set)
    allow_any_authenticated_user: bool = False
    auto_subscribe: bool = False
    client_subscribable: bool = True


AUTO_TOPICS = {"system", "auth", "notifications"}

TOPIC_RULES: dict[str, TopicRule] = {
    "system": TopicRule(allow_any_authenticated_user=True, auto_subscribe=True),
    "auth": TopicRule(allow_any_authenticated_user=True, auto_subscribe=True),
    "notifications": TopicRule(allow_any_authenticated_user=True, auto_subscribe=True),
    "admin.users": TopicRule(any_permission_codes={"user.manage"}),
    "admin.roles": TopicRule(any_permission_codes={"role.read", "role.manage"}),
    "admin.menus": TopicRule(any_permission_codes={"menu.read", "menu.manage"}),
    "admin.system-params": TopicRule(any_permission_codes={"system_param.read", "system_param.manage"}),
    "admin.system-messages": TopicRule(any_permission_codes={"admin.system_message"}),
    "admin.files": TopicRule(any_permission_codes={"file.read", "file.manage"}),
    "admin.tower-models": TopicRule(any_permission_codes={"tower_model.read", "tower_model.manage", "tower.read", "tower.manage"}),
    "admin.elevation": TopicRule(any_permission_codes={"elevation.read", "elevation.manage"}),
    "admin.atp-models": TopicRule(any_permission_codes={"atp.read", "atp.run", "atp.manage"}),
    "admin.atp-assets": TopicRule(any_permission_codes={"atp.read", "atp.run", "atp.manage"}),
    "admin.audit_logs": TopicRule(any_permission_codes={"menu.read", "menu.manage"}),
    "admin.scheduled-tasks": TopicRule(any_permission_codes={"celery.read", "celery.manage"}),
}


def get_auto_topics() -> set[str]:
    return {topic for topic, rule in TOPIC_RULES.items() if rule.auto_subscribe}


def is_builtin_topic(topic: str) -> bool:
    return topic in AUTO_TOPICS


def validate_topic_subscription(
    topic: str,
    *,
    role_codes: set[str],
    permission_codes: set[str],
) -> tuple[bool, str | None]:
    if "admin" in role_codes:
        return True, None

    rule = TOPIC_RULES.get(topic)
    if not rule:
        return False, "unknown_topic"
    if not rule.client_subscribable:
        return False, "topic_not_subscribable"
    if rule.allow_any_authenticated_user:
        return True, None
    if rule.any_permission_codes and permission_codes.intersection(rule.any_permission_codes):
        return True, None
    return False, "missing_permission"
