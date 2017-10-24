from tornado.ioloop import IOLoop
from tornado.stack_context import StackContextInconsistentError, _state

from ...context import Context


class TracerStackContext(object):
    """
    A context manager that manages ``Context`` instances in a thread-local state.
    It must be used everytime a Tornado's handler or coroutine is used within a
    tracing Context. It is meant to work like a traditional ``StackContext``,
    preserving the state across asynchronous calls.

    Everytime a new manager is initialized, a new ``Context()`` is created for
    this execution flow. A context created in a ``TracerStackContext`` is not
    shared between different threads.

    This implementation follows some suggestions provided here:
    https://github.com/tornadoweb/tornado/issues/1063
    """
    def __init__(self):
        self.active = True
        self.context = Context()

    def enter(self):
        """
        Required to preserve the ``StackContext`` protocol.
        """
        pass

    def exit(self, type, value, traceback):
        """
        Required to preserve the ``StackContext`` protocol.
        """
        pass

    def __enter__(self):
        self.old_contexts = _state.contexts
        self.new_contexts = (self.old_contexts[0] + (self,), self)
        _state.contexts = self.new_contexts
        return self

    def __exit__(self, type, value, traceback):
        final_contexts = _state.contexts
        _state.contexts = self.old_contexts

        if final_contexts is not self.new_contexts:
            raise StackContextInconsistentError(
                'stack_context inconsistency (may be caused by yield '
                'within a "with TracerStackContext" block)')

        # break the reference to allow faster GC on CPython
        self.new_contexts = None

    def deactivate(self):
        self.active = False

    @classmethod
    def active(cls):
        """
        Return the ``Context`` from the current execution flow. This method can be
        used inside a Tornado coroutine to retrieve and use the current tracing context.
        If used in a separated Thread, the `_state` thread-local storage is used to
        propagate the current Active context from the `MainThread`.
        """
        io_loop = getattr(IOLoop._current, 'instance', None)
        if io_loop is None:
            # if a Tornado loop is not available, it means that this method
            # has been called from a synchronous code, so we can rely in a
            # thread-local storage
            return getattr(_state, '__datadog_context', None)
        else:
            # we're inside a Tornado loop so the TracerStackContext is used
            for ctx in reversed(_state.contexts[0]):
                if isinstance(ctx, cls) and ctx.active:
                    return ctx.context

    @classmethod
    def activate(cls, ctx):
        """
        Set the active ``Context`` for this async execution. If a ``TracerStackContext``
        is not found, the context is discarded.
        If used in a separated Thread, the `_state` thread-local storage is used to
        propagate the current Active context from the `MainThread`.
        """
        io_loop = getattr(IOLoop._current, 'instance', None)
        if io_loop is None:
            # because we're outside of an asynchronous execution, we store
            # the current context in a thread-local storage
            setattr(_state, '__datadog_context', ctx)
        else:
            # we're inside a Tornado loop so the TracerStackContext is used
            for stack_ctx in reversed(_state.contexts[0]):
                if isinstance(stack_ctx, cls) and stack_ctx.active:
                    stack_ctx.context = ctx


def run_with_trace_context(func, *args, **kwargs):
    """
    Run the given function within a traced StackContext. This function is used to
    trace Tornado web handlers, but can be used in your code to trace coroutines
    execution.
    """
    with TracerStackContext():
        return func(*args, **kwargs)
