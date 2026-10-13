from engine import status_page


def test_the_page_shows_the_clock_jobs_credit_and_internet_state_and_escapes_text():
    s = {"now": "13 Oct 16:00:00", "jobs": [("05:10", "mira_polls_en.json"), ("00:01", "<b>x</b>")], "reels": 15, "newest": ("15-x.mp4", "15:20"),
         "credit": "Veo video credit: ₹9648 used", "net": {"Google": True, "GitHub": False}}
    h = status_page.render(s)
    assert "Updated 13 Oct 16:00:00" in h and "mira_polls_en.json" in h and "15 Reels" in h and "₹9648" in h
    assert "NOT REACHABLE" in h and ">OK<" in h and "&lt;b&gt;x" in h and 'http-equiv=refresh content=30' in h
