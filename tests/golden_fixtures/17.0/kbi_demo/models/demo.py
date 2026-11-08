from odoo import api, fields, models


class KbiDemo(models.Model):
    _name = 'kbi.demo'
    _description = 'KBI Demo'

    name = fields.Char(required=True)
    amount = fields.Float(group_operator='avg')
    total = fields.Float(group_operator="sum")
    canned_id = fields.Many2one('mail.shortcode')

    def name_get(self):
        return [(rec.id, rec.name) for rec in self]

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        return super()._name_search(name, domain, operator, limit, order)

    def can_edit(self):
        return self.env.user.user_has_groups('base.group_system')

    def action_open(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'kbi.demo',
            'view_mode': 'tree,form',
        }
