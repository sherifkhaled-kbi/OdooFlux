class A(models.Model):
    @api.multi
    def f(self):
        return 1
