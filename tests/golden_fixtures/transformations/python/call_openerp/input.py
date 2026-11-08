import openerp
from openerp import fields

class A(openerp.models.Model):
    _name = 'openerp.fields.Char'
    name = openerp.fields.Char(size=64)
