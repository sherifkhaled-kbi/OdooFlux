{
    'name': 'KBI Demo',
    'version': '17.0.1.0.0',
    'summary': 'Provisional validation addon for the 17.0 to 18.0 path',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/demo_views.xml',
        'data/cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kbi_demo/static/src/js/demo.js',
            'kbi_demo/static/src/xml/demo.xml',
        ],
    },
    'license': 'LGPL-3',
}
