class A(models.Model):
    @api.multi
    def f(self):
        return fields.Char(size=64, string='X')
