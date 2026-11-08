from odoo import fields, models

# _inherit = "payment.acquirer" is only mentioned in a comment


class Docstring(models.Model):
    """Replaces payment.acquirer; see env['payment.acquirer'] before 16.0."""
    _name = 'my.payment.acquirer'
    _inherit = ['payment.acquirer.custom', 'payment.provider']
    _description = "payment.acquirer"
    ref_id = fields.Many2one('payment.acquirer_extra')
    other_id = fields.Many2one(comodel_name='x.payment.acquirer')

    def lookup(self):
        _logger.info("loading payment.acquirer rows")
        return self.env['payment.provider'].search([('name', '=', 'payment.acquirer')])
