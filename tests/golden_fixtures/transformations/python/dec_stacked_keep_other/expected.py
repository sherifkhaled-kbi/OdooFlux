class A(models.Model):
    @api.constrains('value')
    def f(self):
        return 1
