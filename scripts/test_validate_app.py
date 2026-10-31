# SPDX-License-Identifier: GPL-3.0-only

import tempfile
import unittest

from archive_app import Capture
from validate_app import skipped_navigation

REJECT = r'/(forum|api|auth|signup|login|logout|register)(/|$|[?])'
BASE = 'http://127.0.0.1:4000'


class ValidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.capture = Capture(temp.name, 'diyhrt.coffee', REJECT)

    def test_visits_to_rejected_pages_on_the_original_site_are_expected(self):
        for url in [
            'https://diyhrt.coffee/login',
            'https://diyhrt.coffee/signup?next=%2Fsettings',
            'https://forum.diyhrt.coffee/login?next=%2Fmessages',
        ]:
            self.assertTrue(skipped_navigation(self.capture, url), url)

    def test_other_navigations_still_load_or_fail(self):
        for url in [
            BASE + '/login',
            BASE + '/diyhrt.coffee/forum/',
            BASE + '/diyhrt.coffee/login.html',
            'https://diyhrt.coffee/about',
            'https://example.com/login',
        ]:
            self.assertFalse(skipped_navigation(self.capture, url), url)

    def test_nothing_is_expected_without_rejected_pages(self):
        self.capture.reject = ''
        self.assertFalse(skipped_navigation(self.capture, 'https://diyhrt.coffee/login'))


if __name__ == '__main__':
    unittest.main()
