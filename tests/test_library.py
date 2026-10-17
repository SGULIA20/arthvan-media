import json

from engine import library as lib


def make(tmp_path):
    root, library = tmp_path / "repo", tmp_path / "Arthvan-Reels"
    (root / "stories" / "out").mkdir(parents=True); library.mkdir()
    for sid, app, lang in (("a-en", "scoremybiz", "en"), ("b-en", "scoremybiz", "en"), ("a-hi", "scoremybiz", "hi-IN"), ("w-en", "waypoint", "en"), ("g-gu", "scoremybiz", "gu")):
        (root / "stories" / f"{sid.replace('-', '_')}.json").write_text(json.dumps({"id": sid, "app": app, "lang": lang}))
    return root, library


def test_a_reel_is_filed_under_its_app_and_language_and_numbered_per_folder(tmp_path):
    root, library = make(tmp_path)
    mp4 = tmp_path / "x.mp4"; mp4.write_bytes(b"1")
    assert lib.file_reel(mp4, "a-en", library, root) == library / "ScoreMyBiz" / "English" / "01-a-en.mp4"
    assert lib.file_reel(mp4, "b-en", library, root).name == "02-b-en.mp4"
    assert lib.file_reel(mp4, "a-hi", library, root) == library / "ScoreMyBiz" / "Hindi" / "01-a-hi.mp4"           # hi-IN is Hindi
    assert lib.file_reel(mp4, "w-en", library, root) == library / "Waypoint" / "English" / "01-w-en.mp4"
    assert lib.file_reel(mp4, "g-gu", library, root).parent.name == "Gujarati"


def test_filing_never_replaces_an_existing_reel(tmp_path):
    root, library = make(tmp_path)
    mp4 = tmp_path / "x.mp4"; mp4.write_bytes(b"first")
    first = lib.file_reel(mp4, "a-en", library, root); mp4.write_bytes(b"second")
    assert lib.file_reel(mp4, "a-en", library, root) == first and first.read_bytes() == b"first"


def test_migrate_moves_old_flat_files_in_their_old_order_and_deletes_nothing(tmp_path):
    root, library = make(tmp_path)
    (library / "01-b-en.mp4").write_bytes(b"b"); (library / "02-a-hi.mp4").write_bytes(b"h"); (library / "03-a-en.mp4").write_bytes(b"a"); (library / "STATUS.html").write_text("x")
    moved = lib.migrate(library, root)
    assert len(moved) == 3 and not list(library.glob("*.mp4")) and (library / "STATUS.html").exists()
    english = sorted(f.name for f in (library / "ScoreMyBiz" / "English").glob("*.mp4"))
    assert english == ["01-b-en.mp4", "02-a-en.mp4"] and (library / "ScoreMyBiz" / "Hindi" / "01-a-hi.mp4").read_bytes() == b"h"


def test_sync_files_new_reels_and_refreshes_a_changed_one_only(tmp_path):
    root, library = make(tmp_path)
    (root / "stories" / "out" / "a-en.mp4").write_bytes(b"v1"); (root / "stories" / "out" / "w-en.mp4").write_bytes(b"www")
    r = lib.sync(library, root)
    assert len(r["filed"]) == 2 and r["refreshed"] == []
    (root / "stories" / "out" / "a-en.mp4").write_bytes(b"version two")
    r = lib.sync(library, root)
    assert r["filed"] == [] and r["refreshed"] == ["ScoreMyBiz/English/01-a-en.mp4"] and (library / "ScoreMyBiz" / "English" / "01-a-en.mp4").read_bytes() == b"version two"


def test_coverage_compares_every_language_with_english_per_app(tmp_path):
    root = tmp_path / "repo"; (root / "stories" / "out").mkdir(parents=True); (root / "content").mkdir()
    def story(sid, app, lang, native=False):
        sc = [{"layout": "clip", "native": "x"}] if native else [{"layout": "clip"}]
        (root / "stories" / f"{sid.replace('-', '_')}.json").write_text(json.dumps({"id": sid, "app": app, "lang": lang, "scenes": sc, "feature": "k"}))
    for sid, app, lang in (("a-en", "scoremybiz", "en"), ("b-en", "scoremybiz", "en"), ("c-en", "scoremybiz", "en"), ("a-hi", "scoremybiz", "hi-IN"), ("b-hi", "scoremybiz", "hi"),
                           ("fest-hi", "scoremybiz", "hi"), ("fest-gu", "scoremybiz", "gu"), ("w-en", "waypoint", "en")):
        story(sid, app, lang)
    story("multi-en", "scoremybiz", "en", native=True)                        # a multi-language Reel is not a yardstick
    for sid in ("a-en", "b-en", "a-hi", "fest-hi", "fest-gu"):
        (root / "stories" / "out" / f"{sid}.mp4").write_bytes(b"x")
    c = lib.coverage(root, ["hi", "gu"])
    smb = c["scoremybiz"]
    hi = next(r for r in smb["rows"] if r["lang"] == "hi"); gu = next(r for r in smb["rows"] if r["lang"] == "gu")
    # english yardstick = a, b, c, fest (fest-hi/fest-gu bases are not english, so they are 'own')
    assert smb["english"] == 3 and hi["made"] == 1 and hi["scripted"] == 1 and hi["todo"] == 1 and hi["own"] == 1
    assert gu["made"] == 0 and gu["todo"] == 3 and gu["own"] == 1
    assert c["waypoint"]["english"] == 1 and "multi" not in str(c)


def test_default_coverage_leaves_out_a_language_the_app_does_not_support(tmp_path):
    root = tmp_path / "repo"; (root / "stories" / "out").mkdir(parents=True); (root / "content").mkdir()
    for sid, app in (("a-en", "scoremybiz"), ("w-en", "waypoint")):
        (root / "stories" / f"{sid.replace('-', '_')}.json").write_text(json.dumps({"id": sid, "app": app, "lang": "en", "scenes": [{"layout": "clip"}], "feature": "k"}))
    c = lib.coverage(root)
    assert "ur" in [r["lang"] for r in c["scoremybiz"]["rows"]]
    assert "ur" not in [r["lang"] for r in c["waypoint"]["rows"]] and "ml" in [r["lang"] for r in c["waypoint"]["rows"]]
