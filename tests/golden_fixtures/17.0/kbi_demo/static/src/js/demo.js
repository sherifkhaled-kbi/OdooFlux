/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class KbiDemoWidget extends Component {
    static template = "kbi_demo.Widget";

    setup() {
        this.state = useState({ count: 0 });
        this.rpc = useService("rpc");
    }

    async load() {
        this.state.count = await this.rpc("/kbi_demo/count", {});
    }
}

registry.category("actions").add("kbi_demo.widget", KbiDemoWidget);
