"""Episode identity for series recordings: XMLTV parsing, storage, keys.

Rerun suppression stands on these: the guide's episode-num / sub-title
must survive import into the programmes table, and two airings of one
episode must produce the same key while different episodes differ.
"""
import datetime
import sqlite3

from playlist import EPGDatabase

FMT = "%Y%m%d%H%M%S +0000"


def _guide(tmp_path, programmes):
    now = datetime.datetime.now(datetime.timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    body = "".join(
        '<programme start="{0}" stop="{1}" channel="c1">'
        "<title>Drama Hour</title>{2}</programme>".format(
            (now + datetime.timedelta(hours=offset)).strftime(FMT),
            (now + datetime.timedelta(hours=offset + 1)).strftime(FMT),
            extra)
        for offset, extra in programmes)
    xml_path = tmp_path / "guide.xml"
    xml_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><tv>'
        '<channel id="c1"><display-name>Channel One</display-name></channel>'
        + body + "</tv>",
        encoding="utf-8")
    return str(xml_path), now


def _schedule(db, now):
    return db.get_schedule({"tvg-id": "c1", "name": "Channel One"},
                           now - datetime.timedelta(hours=1),
                           now + datetime.timedelta(days=2))


def test_episode_num_and_subtitle_survive_import(tmp_path):
    xml, now = _guide(tmp_path, [
        (0, '<sub-title>The Long Night</sub-title>'
            '<episode-num system="xmltv_ns">0.4.</episode-num>'),
        (2, '<episode-num system="onscreen">S02E03</episode-num>'),
        (4, "<desc>No identity at all.</desc>"),
    ])
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.import_epg_xml([xml])
        rows = _schedule(db, now)
        assert [r["episode"] for r in rows] == ["0.4.", "S02E03", ""]
        assert rows[0]["subtitle"] == "The Long Night"
        assert rows[1]["subtitle"] == ""
    finally:
        db.close()


def test_xmltv_ns_wins_over_other_episode_systems(tmp_path):
    xml, now = _guide(tmp_path, [
        (0, '<episode-num system="onscreen">S09E09</episode-num>'
            '<episode-num system="xmltv_ns">1.2.</episode-num>'),
    ])
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.import_epg_xml([xml])
        rows = _schedule(db, now)
        assert rows[0]["episode"] == "1.2."
    finally:
        db.close()


def test_reimport_fills_episode_identity_in(tmp_path):
    xml_bare, now = _guide(tmp_path, [(0, "<desc>First.</desc>")])
    xml_full, _ = _guide(tmp_path, [
        (0, '<sub-title>Pilot</sub-title>'
            '<episode-num system="xmltv_ns">0.0.</episode-num>')])
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.import_epg_xml([xml_bare])
        db.import_epg_xml([xml_full])
        rows = _schedule(db, now)
        assert len(rows) == 1
        assert rows[0]["episode"] == "0.0."
        assert rows[0]["subtitle"] == "Pilot"
    finally:
        db.close()


def test_database_created_before_episode_columns_is_migrated(tmp_path):
    path = str(tmp_path / "epg.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE programmes ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT,"
        " title TEXT, start TEXT, end TEXT, description TEXT,"
        " FOREIGN KEY(channel_id) REFERENCES channels(id),"
        " UNIQUE(channel_id, start, end))")
    conn.commit()
    conn.close()
    db = EPGDatabase(path)
    try:
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(programmes)")}
        assert {"episode", "subtitle"} <= cols
        db.insert_programme("c1", "Drama Hour", "20270101000000", "20270101010000",
                            episode="0.0.", subtitle="Pilot")
        db.commit()
        row = db.conn.execute("SELECT episode, subtitle FROM programmes").fetchone()
        assert row == ("0.0.", "Pilot")
    finally:
        db.close()
