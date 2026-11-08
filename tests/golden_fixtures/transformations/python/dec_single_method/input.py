class A(models.Model):
    _name = 'a'

    @api.multi
    def f(self):
        return 1
