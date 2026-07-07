"""Common agent validation error — Section 10 EH3 ("Validation failure = always
unrecoverable"), Gate G-04 ("All defined failure scenarios return correct structured
errors — no silent failures across all 13 agents").

Every agent module raises AgentValidationError (or a named subclass) for any output
that fails schema or math validation, never a bare exception — this is what lets
arx/api/agents.py handle all four Phase 2 agents with one error-handling code path
that writes a complete error_log record (EH4) instead of one bespoke handler per agent.
"""


class AgentValidationError(Exception):
    def __init__(self, message: str, *, raw_output: dict, failed_checks: dict | None = None):
        super().__init__(message)
        self.raw_output = raw_output
        self.failed_checks = failed_checks
