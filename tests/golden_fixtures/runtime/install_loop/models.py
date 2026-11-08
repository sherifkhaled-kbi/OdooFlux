from odoo import fields, models


class OdoofluxFixture(models.Model):
    _name = 'odooflux.fixture'
    _description = 'OdooFlux runtime fixture'

    name = fields.Char()
