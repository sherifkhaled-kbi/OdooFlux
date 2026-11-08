{
    'name': 'OdooFlux runtime fixture: install_loop',
    'version': '1.0',
    'depends': ['base'],
    'data': ['security/ir.model.access.csv', 'views/fixture_views.xml'],
    'license': 'LGPL-3',
    'installable': True,
    'post_init_hook': 'post_init',
    }
