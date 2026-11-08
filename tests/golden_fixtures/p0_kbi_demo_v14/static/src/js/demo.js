odoo.define('kbi_demo.demo', function (require) {
    'use strict';
    var Widget = require('web.Widget');
    var ajax = require('web.ajax');

    var KbiDemoWidget = Widget.extend({
        start: function () {
            ajax.jsonRpc('/kbi_demo/data', 'call', {});
            this.$el.on('click', function () {});
            return this._super.apply(this, arguments);
        },
    });
    return KbiDemoWidget;
});
