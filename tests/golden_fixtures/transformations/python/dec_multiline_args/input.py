class A(models.Model):
    @api.returns(
        'self',
    )
    def g(self):
        return self.search([])
