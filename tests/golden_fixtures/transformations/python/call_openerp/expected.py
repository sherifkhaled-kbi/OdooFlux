import openerp
from openerp import fields

class A(openerp.models.Model):
    _name = 'openerp.fields.Char'
    name = odoo.fields.Char(size=64)
