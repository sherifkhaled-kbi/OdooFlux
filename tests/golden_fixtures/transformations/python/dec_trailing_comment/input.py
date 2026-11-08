class A(models.Model):
    @api.multi  # legacy
    def f(self):
        return 1
