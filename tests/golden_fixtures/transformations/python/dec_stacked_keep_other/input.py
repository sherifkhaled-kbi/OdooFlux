class A(models.Model):
    @api.multi
    @api.constrains('value')
    def f(self):
        return 1
