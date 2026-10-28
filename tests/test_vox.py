import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import vox


LISTING = '<a href="/movies/avengers-doomsday">Avengers: Doomsday</a>'
OPEN = '<h2>City Centre Almaza</h2><span>10:30 pm</span>'
CLOSED = '<h1>Avengers: Doomsday</h1><p>Coming soon</p>'


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.state = {"initialized": True, "movies": {}}
        self.sent = Mock(return_value=True)
        for name, value in (("prepare_subscribers", Mock()), ("load_state", lambda: self.state),
                            ("save_state", Mock()), ("send", self.sent),
                            ("WATCH_CINEMAS", []), ("log", Mock())):
            p = patch.object(vox, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(vox.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def check(self, movie_html, showing=False, listed=True):
        def fetch(url):
            if url == vox.COMING_SOON_URL:
                return LISTING if listed and not showing else ""
            if url == vox.NOW_SHOWING_URL:
                return LISTING if showing else '<a href="/movies/another">Another</a>'
            if url.endswith('/another'):
                return CLOSED
            if isinstance(movie_html, Exception):
                raise movie_html
            return movie_html
        with patch.object(vox, "fetch", side_effect=fetch):
            vox.run()

    def booking_messages(self):
        return [c.args[0] for c in self.sent.call_args_list if 'BOOKING OPEN' in c.args[0]]

    def test_reopening_alerts_once_per_opening_including_now_showing(self):
        self.check(CLOSED)
        self.check(OPEN)
        self.check(OPEN)
        self.check(CLOSED, showing=True)
        self.check(OPEN, showing=True)
        self.assertEqual(len(self.booking_messages()), 2)

    def test_existing_alerted_state_is_rechecked(self):
        self.state['movies']['avengers-doomsday'] = {
            'title': 'Avengers: Doomsday', 'alerted': True, 'cinemas': ['City Centre Almaza']}
        self.check(OPEN, showing=True)
        self.check(OPEN, showing=True)
        self.assertEqual(len(self.booking_messages()), 1)

    def test_failed_delivery_retries_while_still_open(self):
        self.sent.return_value = False
        self.check(OPEN)
        self.assertFalse(self.state['movies']['avengers-doomsday']['alerted'])
        self.sent.return_value = True
        self.check(OPEN)
        self.check(OPEN)
        self.assertEqual(len(self.booking_messages()), 2)

    def test_failed_fetch_does_not_count_as_closure(self):
        self.check(OPEN)
        self.check(RuntimeError('temporary network failure'))
        self.check(OPEN)
        self.assertEqual(len(self.booking_messages()), 1)

    def test_watched_cinema_closure_rearms_alert(self):
        with patch.object(vox, 'WATCH_CINEMAS', ['almaza']):
            self.check(OPEN)
            self.check('<h2>Mall of Egypt</h2><span>10:30 pm</span>')
            self.check(OPEN)
        self.assertEqual(len(self.booking_messages()), 2)

    def test_unlisted_then_returning_movie_rearms_alert(self):
        self.check(OPEN)
        self.check(CLOSED, listed=False)
        self.check(OPEN)
        self.assertEqual(len(self.booking_messages()), 2)

    def test_new_cinema_alert_not_repeated(self):
        self.check(OPEN)
        expanded = OPEN + '<h2>Mall of Egypt</h2><span>11:00 pm</span>'
        self.check(expanded)
        self.check(expanded)
        messages = [c.args[0] for c in self.sent.call_args_list if 'More showtimes' in c.args[0]]
        self.assertEqual(len(messages), 1)

    def test_cinema_reopening_alerts_even_if_another_cinema_stays_open(self):
        expanded = OPEN + '<h2>Mall of Egypt</h2><span>11:00 pm</span>'
        self.check(expanded)
        self.check(OPEN)
        self.check(expanded)
        messages = [c.args[0] for c in self.sent.call_args_list if 'More showtimes' in c.args[0]]
        self.assertEqual(len(messages), 1)
        self.assertIn('Mall of Egypt', messages[0])


class SubscriberTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (('TOKEN', 'fake-test-token'), ('CHAT_ID', '100'),
                            ('SUBSCRIBERS', set()),
                            ('SUBSCRIBERS_FILE', Path(tmp.name) / 'subscribers.enc')):
            p = patch.object(vox, name, value)
            p.start()
            self.addCleanup(p.stop)

    def poll(self, updates):
        response = Mock()
        response.json.return_value = {'ok': True, 'result': updates}
        with patch.object(vox.requests, 'get', return_value=response) as get, \
                patch.object(vox, 'send_to', return_value=True):
            vox.sync_subscribers()
        return get

    def message(self, update_id, text, chat_type='private'):
        return {'update_id': update_id, 'message': {
            'chat': {'id': 987654321, 'type': chat_type}, 'text': text}}

    def test_start_persists_encrypted_subscribers_and_offset_across_runs(self):
        self.poll([self.message(10, '/start')])
        self.assertNotIn(b'987654321', vox.SUBSCRIBERS_FILE.read_bytes())
        vox.SUBSCRIBERS.clear()
        get = self.poll([])
        self.assertEqual(vox.SUBSCRIBERS, {'987654321'})
        self.assertEqual(get.call_args.kwargs['params']['offset'], 11)
        with patch.object(vox, 'send_to', return_value=True) as deliver:
            self.assertTrue(vox.send('booking open'))
        self.assertEqual({c.args[0] for c in deliver.call_args_list}, {'100', '987654321'})

    def test_stop_persists_unsubscription(self):
        self.poll([self.message(10, '/start'), self.message(11, '/stop')])
        self.assertEqual(vox.load_subscribers()['chat_ids'], [])
        vox.SUBSCRIBERS.clear()
        self.poll([])
        with patch.object(vox, 'send_to', return_value=True) as deliver:
            vox.send('booking open')
        deliver.assert_called_once_with('100', 'booking open')

    def test_group_messages_do_not_subscribe_the_group(self):
        self.poll([self.message(10, '/start', 'group')])
        self.assertEqual(vox.SUBSCRIBERS, set())

    def test_one_failed_recipient_does_not_prevent_other_deliveries(self):
        vox.SUBSCRIBERS.update(['200', '300'])
        with patch.object(vox, 'send_to', side_effect=[False, True, True]) as deliver:
            self.assertFalse(vox.send('booking open'))
        self.assertEqual(deliver.call_count, 3)

    def test_telegram_api_error_is_not_treated_as_delivery(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {'ok': False}
        with patch.object(vox.requests, 'post', return_value=response), patch.object(vox, 'log'):
            self.assertFalse(vox.send_to('100', 'booking open'))


if __name__ == '__main__':
    unittest.main()
