from odoo import fields, models


class Extend(models.Model):
    _inherit = "payment.acquirer"


class Multi(models.Model):
    _inherit = ['payment.acquirer', 'mail.thread']


class Own(models.Model):
    _name = 'x.own'
    _inherits = {'payment.acquirer': 'acquirer_id'}
    acquirer_id = fields.Many2one('payment.acquirer')
    other_id = fields.Many2one(comodel_name="payment.acquirer")
    many_ids = fields.One2many(comodel_name='payment.acquirer', inverse_name='x_id')

    def lookup(self):
        return self.env['payment.acquirer'].search([])


class Rename(models.Model):
    _name = 'payment.acquirer'
