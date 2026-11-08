# -*- coding: utf-8 -*-
{
    'name': 'KBI Demo',
    'version': '14.0.2.3.1',
    'summary': 'Reproduction fixture for the OdooFlux P0 safety tests',
    'depends': ['base', 'kbi_nonexistent_dependency'],
    'qweb': ['static/src/xml/demo.xml'],
    'data': [
        'security/ir.model.access.csv',
        'views/demo_views.xml',
    ],
    'installable': True,
}
