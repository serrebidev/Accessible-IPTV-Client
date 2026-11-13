import datetime

from channel_identity import guide_indexes, match_guide_channel
from playlist import EPGDatabase
from providers import _normalize_base_url
from types import SimpleNamespace
from main import IPTVClient


def test_ipv6_provider_urls_keep_their_authority():
    assert _normalize_base_url('http://u:p@[2001:db8::1234]:8080/player_api.php') == 'http://[2001:db8::1234]:8080'
    assert _normalize_base_url('https://[::1]/') == 'https://[::1]'


def test_replacing_a_programme_clears_its_old_episode_identity(tmp_path):
    db = EPGDatabase(str(tmp_path / 'epg.db'))
    try:
        db.insert_channel('1', 'Channel')
        db.insert_programme('1', 'Old', '20300101000000', '20300102000000', 'Old description', '1.2.', 'Old episode')
        db.insert_programme('1', 'New', '20300101000000', '20300102000000', 'New description', '', '')
        assert db.conn.execute('SELECT title, description, episode, subtitle FROM programmes').fetchone() == ('New', 'New description', '', '')
    finally:
        db.close()


def test_independent_source_ids_survive_import_refresh_and_matching(tmp_path):
    sources = []
    for name in ('News Alpha', 'Sport Beta'):
        path = tmp_path / (name + '.xml')
        path.write_text('<tv><channel id="100"><display-name>' + name + '</display-name></channel>'
                        '<programme channel="100" start="20300101000000 +0000" stop="20300102000000 +0000">'
                        '<title>' + name + ' show</title></programme></tv>')
        sources.append(str(path))
    db = EPGDatabase(str(tmp_path / 'epg.db'))
    try:
        db._utcnow = lambda: datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        for order in (sources, list(reversed(sources))):
            assert db.import_epg_xml(order) == 2
            rows = db.conn.execute('SELECT c.id, c.display_name, p.title FROM channels c JOIN programmes p ON p.channel_id=c.id').fetchall()
            assert len(rows) == 2
            entries = {key: {'display_name': name, 'title': title} for key, name, title in rows}
            for name in ('News Alpha', 'Sport Beta'):
                channel = {'tvg-id': '100', 'name': name}
                key = db.resolve_best_channel_id(channel)
                assert entries[key]['title'] == name + ' show'
                assert match_guide_channel(channel, guide_indexes(entries), set(entries))['title'] == name + ' show'
            # An ambiguous id without a usable name must never choose a feed at random.
            assert db.resolve_best_channel_id({'tvg-id': '100', 'name': 'Unknown'}) is None
            assert match_guide_channel({'tvg-id': '100', 'name': 'Unknown'}, guide_indexes(entries), set(entries)) is None
    finally:
        db.close()


def test_epg_search_actions_do_not_use_a_different_accounts_equal_id():
    news = {'tvg-id': '100', 'name': 'News Alpha', 'provider-id': 'first'}
    sport = {'tvg-id': '100', 'name': 'Sport Beta', 'provider-id': 'second'}
    owner = SimpleNamespace(all_channels=[news, sport])
    for identity in ('100', 'epg:' + 'a' * 40 + ':100'):
        assert IPTVClient._find_matching_channel_for_program(owner, {'channel_id': identity, 'channel_name': 'Sport Beta'}) is sport
        assert IPTVClient._find_matching_channel_for_program(owner, {'channel_id': identity, 'channel_name': 'Unknown'}) is None


def test_undeclared_channel_in_another_feed_does_not_overwrite_a_guide(tmp_path):
    first = tmp_path / 'valid.xml'
    second = tmp_path / 'missing-channel.xml'
    programme = '<programme channel="100" start="20300101000000 +0000" stop="20300102000000 +0000"><title>{}</title></programme>'
    first.write_text('<tv><channel id="100"><display-name>News</display-name></channel>' + programme.format('Keep me') + '</tv>')
    second.write_text('<tv>' + programme.format('Wrong feed') + '</tv>')
    db = EPGDatabase(str(tmp_path / 'guide.db'))
    try:
        db._utcnow = lambda: datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        db.import_epg_xml([str(first), str(second)])
        assert db.conn.execute('SELECT title FROM programmes').fetchall() == [('Keep me',)]
    finally:
        db.close()
