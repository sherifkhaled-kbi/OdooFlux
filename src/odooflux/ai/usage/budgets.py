"""Nested hard-stop budgets: request within file within module within job (contracts/budget-and-cache.md, FR-007).

A request is sent only if ``estimated_input + max_output`` fits the remaining budget at every scope. After the
response the actual usage is charged (the estimate is never reserved). A scope that cannot take a request is
latched as exhausted: later requests in that scope are skipped, and the exhaustion is recorded once.
"""

SCOPES = ("request", "file", "module", "job")


class BudgetTree:
    def __init__(self, *, job_tokens, module_tokens=None, file_tokens=None, request_tokens=None, job_cost=None):
        if job_tokens is None or job_tokens <= 0:
            raise ValueError("the job budget is mandatory when AI is enabled")
        self.limits = {"job": job_tokens, "module": module_tokens, "file": file_tokens, "request": request_tokens}
        self.job_cost = job_cost
        self._used = {"job": 0}
        self._used_module: dict = {}
        self._used_file: dict = {}
        self._cost = 0.0
        self._latched: set = set()
        self.events: list = []

    def _used_for(self, scope, module, file) -> int:
        if scope == "job":
            return self._used["job"]
        if scope == "module":
            return self._used_module.get(module, 0)
        return self._used_file.get((module, file), 0)

    def remaining(self, scope: str, module: str = "", file: str = "") -> int:
        limit = self.limits[scope]
        return 0 if limit is None else limit - self._used_for(scope, module, file)

    def _latch(self, scope, module, file) -> str:
        key = (scope, "" if scope == "job" else module, file if scope == "file" else "")
        if key not in self._latched:
            self._latched.add(key)
            self.events.append({"scope": scope, "module": module if scope != "job" else "",
                                "file": file if scope == "file" else "",
                                "limit": self.limits[scope] if scope != "job" or self.job_cost is None
                                else self.limits["job"],
                                "used": self._used_for(scope, module, file)})
        return f"budget_{scope}"

    def _is_latched(self, scope, module, file) -> bool:
        return (scope, "" if scope == "job" else module, file if scope == "file" else "") in self._latched

    def check(self, module: str, file: str, estimated_input: int, max_output: int, est_cost=None):
        """None when the request may be sent, else ``budget_<scope>`` for the innermost scope that cannot take it."""
        need = estimated_input + max_output
        if self.limits["request"] is not None and need > self.limits["request"]:
            return "budget_request"
        for scope in ("file", "module", "job"):
            limit = self.limits[scope]
            if limit is None:
                continue
            if self._is_latched(scope, module, file) or need > self.remaining(scope, module, file):
                return self._latch(scope, module, file)
        if self.job_cost is not None:
            if self._is_latched("job", module, file):
                return "budget_job"
            if est_cost is None:  # cannot prove the request fits: stop it, without latching the whole job
                if ("cost_unknown",) not in self._latched:
                    self._latched.add(("cost_unknown",))
                    self.events.append({"scope": "job", "module": "", "file": "", "limit": self.job_cost,
                                        "used": self._cost, "reason": "cost_unknown"})
                return "budget_job"
            if self._cost + est_cost > self.job_cost:
                return self._latch("job", module, file)
        return None

    def charge(self, module: str, file: str, tokens: int, cost=None) -> None:
        self._used["job"] += tokens
        self._used_module[module] = self._used_module.get(module, 0) + tokens
        self._used_file[(module, file)] = self._used_file.get((module, file), 0) + tokens
        if cost is not None:
            self._cost += cost
