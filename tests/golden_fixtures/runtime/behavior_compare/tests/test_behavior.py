from odoo.release import version_info
from odoo.tests import TransactionCase, tagged


@tagged('odooflux_fixture', 'at_install', 'post_install')
class TestBehavior(TransactionCase):

    def test_pass_both(self):
        self.assertEqual(1 + 1, 2)

    def test_fail_both(self):
        # Fails on every version: a pre-existing failure.
        self.assertEqual(1, 2)

    def test_regression(self):
        # Passes on majors below 19 and fails on 19.0: a regression when the source is 18.0 and the target is 19.0.
        self.assertLess(version_info[0], 19, 'behaviour changed in 19.0')
