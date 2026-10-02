"""Regression tests for chat D-grade quality retry routing."""
from app.application.chat.service import ChatService


def test_quality_retry_message_contains_actual_issues_and_failed_candidate():
    original = "请写一份社区矫正工作通知"
    failed = "一、工作要求\n待补充具体内容。"
    issues = [
        {"severity": "critical", "message": "检测到占位符或待补充内容"},
        {"severity": "warning", "message": "正文过短"},
    ]

    retry = ChatService._quality_retry_message(original, failed, issues, attempt=1)

    assert retry != original
    assert original in retry
    assert failed in retry
    assert "检测到占位符或待补充内容" in retry
    assert "正文过短" in retry
    assert "第 1 次质量修复" in retry
    assert "只输出修复后的完整正文" in retry


def test_quality_retry_message_caps_issue_count_without_dropping_priority_order():
    issues = [
        {"severity": "critical", "message": f"问题-{i:02d}"}
        for i in range(25)
    ]
    retry = ChatService._quality_retry_message("原始要求", "失败稿", issues, attempt=2)

    assert "问题-00" in retry
    assert "问题-19" in retry
    assert "问题-20" not in retry
    assert "第 2 次质量修复" in retry


def test_quality_candidate_score_prefers_fewer_critical_issues_before_length():
    noisy_long = {
        "level": "D",
        "char_count": 3000,
        "issues": [
            {"severity": "critical", "message": "硬伤1"},
            {"severity": "critical", "message": "硬伤2"},
        ],
    }
    repaired_shorter = {
        "level": "D",
        "char_count": 1800,
        "issues": [
            {"severity": "critical", "message": "剩余硬伤"},
        ],
    }

    assert (
        ChatService._quality_candidate_score(repaired_shorter)
        > ChatService._quality_candidate_score(noisy_long)
    )
