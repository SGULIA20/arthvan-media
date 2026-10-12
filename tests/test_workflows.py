from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    doc = yaml.safe_load((WF / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # PyYAML reads the key `on` as boolean True
    return doc


def test_daily_post_runs_at_18_00_lagos_which_is_17_00_utc():
    wf = load("daily-post.yml")
    assert wf["on"]["schedule"] == [{"cron": "37 16 * * *"}, {"cron": "37 17 * * *"}]
    assert wf["permissions"] == {"contents": "write"}
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_manual_runs_default_to_the_safe_render_mode_and_scheduled_runs_post():
    wf = load("daily-post.yml")
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert inputs["mode"]["default"] == "render" and set(inputs["mode"]["options"]) == {"render", "prepare", "post"}
    text = (WF / "daily-post.yml").read_text()
    assert "github.event.inputs.mode || 'post'" in text


def test_secrets_are_passed_by_env_and_inputs_never_expand_inside_shell_lines():
    text = (WF / "daily-post.yml").read_text()
    assert "secrets.IG_ACCESS_TOKEN" in text and "secrets.IG_USER_ID" in text and "vars.PAUSE" in text
    for line in text.splitlines():
        if line.strip().startswith("run:") or line.strip().startswith("- run:"):
            assert "${{" not in line, line


def test_refresh_workflow_runs_weekly():
    wf = load("refresh-token.yml")
    assert wf["on"]["schedule"] == [{"cron": "30 12 * * 0"}]
    assert "secrets.IG_ACCESS_TOKEN" in (WF / "refresh-token.yml").read_text()


def test_checkout_always_takes_the_latest_main_so_reruns_see_the_log():
    steps = load("daily-post.yml")["jobs"]["post"]["steps"]
    checkout = [x for x in steps if str(x.get("uses", "")).startswith("actions/checkout")][0]
    assert checkout["with"]["ref"] == "main"


def test_linkedin_credentials_reach_the_daily_job_and_the_token_date_reaches_the_weekly_job():
    daily = (WF / "daily-post.yml").read_text()
    assert "secrets.LINKEDIN_ACCESS_TOKEN" in daily and "secrets.LINKEDIN_PERSON_URN" in daily
    assert "vars.LINKEDIN_TOKEN_DATE" in (WF / "refresh-token.yml").read_text()


def test_threads_credentials_reach_both_jobs():
    assert "secrets.THREADS_ACCESS_TOKEN" in (WF / "daily-post.yml").read_text()
    assert "secrets.THREADS_USER_ID" in (WF / "daily-post.yml").read_text()
    assert "secrets.THREADS_ACCESS_TOKEN" in (WF / "refresh-token.yml").read_text()


def test_weekly_report_runs_monday_morning_and_can_open_issues():
    wf = load("weekly-report.yml")
    assert wf["on"]["schedule"] == [{"cron": "23 6 * * 1"}]
    assert wf["permissions"] == {"contents": "write", "issues": "write"}
    text = (WF / "weekly-report.yml").read_text()
    assert "secrets.IG_ACCESS_TOKEN" in text and "gh issue create" in text


def test_weekly_report_includes_the_ad_radar():
    text = (WF / "weekly-report.yml").read_text()
    assert "radar.collect" in text and "radar.report" in text and "radar/snapshots" in text
