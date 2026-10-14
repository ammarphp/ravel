"""Shared local-only framework guards; provider dispatch runs in a fresh Context."""
from contextvars import Context


class GuardError(ValueError):
    """A framework option or identity cannot grant effect authority."""


def local_context():
    from langchain_core import globals as settings
    from langchain_core.tracers import context as tracing
    from langchain_core.callbacks.manager import env_var_is_set

    for name in ('LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER', 'LANGCHAIN_TRACING_V2', 'LANGSMITH_TRACING'):
        if env_var_is_set(name):
            raise GuardError('charged service refuses ambient cloud tracing')
    if settings.get_debug() or settings.get_verbose() or tracing._tracing_v2_is_enabled():
        raise GuardError('charged service requires local callbacks only')
    for var, _, handler_class, env_var in tracing._configure_hooks:
        if var.get() is not None or (handler_class is not None and env_var and env_var_is_set(env_var)):
            raise GuardError('charged service refuses ambient callback hooks')


def callbacks_allowed(callbacks):
    """Exact local classes only; subclasses cannot replace their behavior."""
    from langgraph.pregel._messages import StreamMessagesHandler
    from .langchain_service import _LocalTrace
    handlers = getattr(callbacks, 'handlers', callbacks) or []
    inherited = getattr(callbacks, 'inheritable_handlers', [])
    if any(type(handler) not in (_LocalTrace, StreamMessagesHandler) for handler in [*handlers, *inherited]):
        raise GuardError('provider refuses nonlocal callback classes')


def guarded(function, *, current, callbacks=()):
    # Check the invoking context too, before discarding its callback hooks.
    # ChargedService retains its established inherited-context behavior.
    local_context()
    callbacks_allowed(callbacks)

    def dispatch():
        local_context()
        current()
        result = function()
        current()
        local_context()
        return result
    return Context().run(dispatch)


class SingleEffect:
    def with_retry(self, *args, **kwargs):
        raise GuardError('retry belongs to the effect ledger')

    def with_fallbacks(self, *args, **kwargs):
        raise GuardError('provider fallback needs an explicit decision turn')

    def batch(self, *args, **kwargs):
        raise GuardError('one receipted provider turn per invocation')

    def stream(self, *args, **kwargs):
        raise GuardError('streaming belongs to the declared turn transport; never stream as retry')
