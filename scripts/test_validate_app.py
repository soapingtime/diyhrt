# SPDX-License-Identifier: GPL-3.0-only

import tempfile
import unittest

from archive_app import Capture
from validate_app import skipped_navigation, skipped_prefetch

REJECT = r'/(forum|api|auth|signup|login|logout|register)(/|$|[?])'
BASE = 'http://127.0.0.1:4000'


class ValidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.capture = Capture(temp.name, 'diyhrt.coffee', REJECT)

    def test_prefetches_of_rejected_pages_are_expected_misses(self):
        for url in [
            'https://diyhrt.coffee/login?_rsc=1p-R_iEY',
            'https://forum.diyhrt.coffee/signup?_rsc=LLnm6xMO',
            'https://diyhrt.coffee/login?next=%2Fsettings&_rsc=abc',
        ]:
            self.assertTrue(skipped_prefetch(self.capture, 'Unrecorded request: ' + url), url)

    def test_other_unrecorded_requests_still_fail(self):
        for message in [
            'Unrecorded request: https://diyhrt.coffee/about?_rsc=1p-R_iEY',
            'Unrecorded request: https://diyhrt.coffee/api/v1/availability/timeline?window=7d',
            'Unrecorded request: https://diyhrt.coffee/login',
            'Unrecorded request: https://example.com/login?_rsc=abc',
            'Failed to load resource: the server responded with a status of 404 (File not found)',
        ]:
            self.assertFalse(skipped_prefetch(self.capture, message), message)

    def test_nothing_is_expected_without_rejected_pages(self):
        self.capture.reject = ''
        self.assertFalse(
            skipped_prefetch(self.capture, 'Unrecorded request: https://diyhrt.coffee/login?_rsc=a')
        )
        self.assertFalse(skipped_navigation(self.capture, BASE, BASE + '/login'))

    def test_leaving_the_mirror_for_a_rejected_page_is_expected(self):
        for path in ['/login', '/signup?next=%2Fsettings']:
            self.assertTrue(skipped_navigation(self.capture, BASE, BASE + path), path)

    def test_saved_pages_and_other_navigations_still_load(self):
        for url in [
            BASE + '/about',
            BASE + '/',
            BASE + '/diyhrt.coffee/forum/',
            BASE + '/diyhrt.coffee/api/v1/shops.json',
            BASE + '/diyhrt.coffee/login/index.html',
            'https://diyhrt.coffee/login',
        ]:
            self.assertFalse(skipped_navigation(self.capture, BASE, url), url)


if __name__ == '__main__':
    unittest.main()
