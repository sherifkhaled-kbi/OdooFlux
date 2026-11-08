# -*- coding: utf-8 -*-
class Société(models.Model):
    _name = 'société'

    @api.multi
    def définir(self):
        return 'é'
