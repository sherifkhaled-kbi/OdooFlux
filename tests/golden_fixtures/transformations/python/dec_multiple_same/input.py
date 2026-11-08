class A(models.Model):
    @api.one
    def f(self):
        return 1

    @api.one
    def g(self):
        return 2
