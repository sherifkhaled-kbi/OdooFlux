class A(models.Model):
    @api.multi
    def run(self, async=False):
        return async
