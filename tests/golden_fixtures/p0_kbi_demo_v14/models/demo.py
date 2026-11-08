# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import Warning


class KbiDemo(models.Model):
    _name = 'kbi.demo'
    _description = 'KBI Demo'

    name = fields.Char(size=64, string='Name')
    code = fields.Char(
        string='Code',
        size=32,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')],
        states={'done': [('readonly', True)]},
        default='draft',
    )

    @api.multi
    def name_get(self):
        return [(rec.id, rec.name or '') for rec in self]

    @api.one
    def action_check(self):
        if not self.name:
            raise Warning('Name is required.')
        return True

    @api.returns('self')
    def action_copy_all(self):
        return self.search([]).copy()

    def action_unrestricted(self):
        return self.sudo(False).search([])
