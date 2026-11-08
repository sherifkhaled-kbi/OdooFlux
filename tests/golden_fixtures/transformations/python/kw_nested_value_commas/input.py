class A(models.Model):
    name = fields.Char(size=min(64, LIMIT), string='X')
