class A(models.Model):
    @api.multi
    # keep this comment
    def f(self):
        return 1
